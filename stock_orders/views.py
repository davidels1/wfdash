from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.db import transaction
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.urls import reverse
from django.utils import timezone

from datetime import datetime
from decimal import Decimal
from io import BytesIO
import json
import logging
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from .models import StockOrder, StockOrderItem
from .forms import StockOrderForm, StockOrderItemFormSet, StockOrderProcessForm, SupplierForm, AssignDriverForm
from wfdash.models import Suppliers, CompanyDetails
from driver_list.models import DriverListPool, Collection

from PIL import Image as PILImage
from datetime import datetime

logger = logging.getLogger(__name__)

@login_required
def stock_order_list(request):
    """View all stock orders"""
    # Get the status filter from URL parameters
    status_filter = request.GET.get('status', '')
    
    if status_filter:
        stock_orders = StockOrder.objects.filter(status=status_filter).order_by('-created_at')
    else:
        stock_orders = StockOrder.objects.all().order_by('-created_at')
    
    # Search functionality
    search_query = request.GET.get('q', '')
    if (search_query):
        stock_orders = stock_orders.filter(
            Q(order_number__icontains=search_query) |
            Q(supplier__suppliername__icontains=search_query) |  # Changed from supplier__name
            Q(items__description__icontains=search_query)
        ).distinct()
    
    # Add status choices for tab grouping
    status_choices = StockOrder.STATUS_CHOICES
    
    context = {
        'stock_orders': stock_orders,
        'status_filter': status_filter,
        'search_query': search_query,
        'status_choices': status_choices,  # Add this line
    }
    
    return render(request, 'stock_orders/stock_order_list.html', context)

@login_required
def stock_order_detail(request, pk):
    """View details of a specific stock order"""
    stock_order = get_object_or_404(StockOrder, pk=pk)
    
    # Calculate total amount and add total to each item
    total_amount = 0
    items = stock_order.items.all()
    for item in items:
        item.total = item.quantity * item.unit_price
        total_amount += item.total
    
    context = {
        'stock_order': stock_order,
        'total_amount': total_amount,
        'items': items
    }
    
    return render(request, 'stock_orders/stock_order_detail.html', context)

@login_required
def stock_order_create(request):
    """Create a new stock order"""
    # Use your existing Suppliers model
    suppliers = Suppliers.objects.all().order_by('suppliername')
    
    # Get the last order for the success message
    last_order = None
    if request.user.is_authenticated:
        last_order = StockOrder.objects.filter(created_by=request.user).order_by('-created_at').first()
    
    if request.method == 'POST':
        form = StockOrderForm(request.POST)
        
        # Check if this is an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if form.is_valid():
            stock_order = form.save(commit=False)
            stock_order.created_by = request.user
            
            # If order_number wasn't provided, generate one
            if not stock_order.order_number:
                from .utils import generate_stock_order_number
                stock_order.order_number = generate_stock_order_number()
                
            stock_order.save()
            
            # Process items
            descriptions = request.POST.getlist('description[]')
            skus = request.POST.getlist('sku[]')
            quantities = request.POST.getlist('quantity[]')
            unit_prices = request.POST.getlist('unit_price[]')
            item_notes = request.POST.getlist('item_notes[]')
            
            item_count = 0
            
            for i in range(len(descriptions)):
                if descriptions[i]:  # Only create item if description exists
                    try:
                        StockOrderItem.objects.create(
                            stock_order=stock_order,
                            description=descriptions[i],
                            sku=skus[i] if i < len(skus) else '',
                            quantity=int(quantities[i]) if i < len(quantities) and quantities[i] else 1,
                            unit_price=float(unit_prices[i]) if i < len(unit_prices) and unit_prices[i] else 0,
                            notes=item_notes[i] if i < len(item_notes) else ''
                        )
                        item_count += 1
                    except (ValueError, TypeError) as e:
                        # Log the error but continue processing other items
                        print(f"Error creating item: {e}")
            
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'order_number': stock_order.order_number,
                    'order_id': stock_order.id,
                    'item_count': item_count,
                    'message': f'Stock Order #{stock_order.order_number} created successfully with {item_count} items!',
                    'supplier_name': stock_order.supplier.suppliername  # Add this line
                })
            else:
                messages.success(request, f'Stock Order #{stock_order.order_number} created successfully with {item_count} items!')
                return redirect('stock_orders:detail', pk=stock_order.pk)
        else:
            # Form is invalid
            if is_ajax:
                return JsonResponse({
                    'success': False,
                    'message': 'There were errors in your form',
                    'errors': {field: errors for field, errors in form.errors.items()}
                }, status=400)
    else:
        form = StockOrderForm(initial={'created_by': request.user})
    
    return render(request, 'stock_orders/stock_order_create.html', {
        'form': form,
        'suppliers': suppliers,
        'last_order': last_order
    })

@login_required
def stock_order_process(request, pk):
    """Process a stock order - generate PO and send to supplier"""
    stock_order = get_object_or_404(StockOrder, pk=pk)
    
    if request.method == 'POST':
        form = StockOrderProcessForm(request.POST, instance=stock_order)
        
        # Check if this is an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if form.is_valid():
            stock_order = form.save(commit=False)
            
            try:
                # Generate the purchase order PDF
                # This redirects to preview when successful
                return generate_stock_purchase_order(request, stock_order.pk)
            except Exception as e:
                logger.error(f"Error generating PO: {str(e)}")
                messages.error(request, f'Error generating PO: {str(e)}')
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'message': f'Error generating purchase order: {str(e)}'
                    }, status=500)
        else:
            if is_ajax:
                return JsonResponse({
                    'success': False,
                    'message': 'There were errors in your form',
                    'errors': {field: errors for field, errors in form.errors.items()}
                }, status=400)
    else:
        form = StockOrderProcessForm(instance=stock_order)
    
    # Calculate total amount and add total to each item
    total_amount = 0
    items = stock_order.items.all()
    for item in items:
        item.total = item.quantity * item.unit_price
        total_amount += item.total
    
    # Calculate VAT and grand total
    vat_amount = total_amount * Decimal('0.15')
    grand_total = total_amount + vat_amount
    
    # Use hardcoded company details - don't try to access the CompanyDetails model
    company_info = {
        'company_name': 'CNL Mining Supplies (Pty) Ltd',
        'company_address': '47 Station Street, Carletonville, Gauteng 2499',
        'company_phone': '+27 18 786 2897',
        'company_email': 'laura@wfsales.co.za',
        'delivery_address': '47 Station Street, Carletonville, Gauteng 2499'
    }
    
    context = {
        'stock_order': stock_order,
        'form': form,
        'total_amount': total_amount,
        'vat_amount': vat_amount,
        'grand_total': grand_total,
        'items': items,
        **company_info
    }
    
    return render(request, 'stock_orders/stock_order_process.html', context)

@login_required
def assign_driver(request, pk):
    """Assign a driver to collect the stock order"""
    stock_order = get_object_or_404(StockOrder, pk=pk)
    
    # Only assign if it's in processed status
    if stock_order.status != 'processed':
        messages.error(request, f"Driver can only be assigned to processed stock orders.")
        return redirect('stock_orders:detail', pk=stock_order.pk)
    
    if request.method == 'POST':
        form = AssignDriverForm(request.POST, instance=stock_order)
        
        if form.is_valid():
            stock_order = form.save(commit=False)
            
            # Get the selected driver
            driver = form.cleaned_data['driver']
            planned_date = form.cleaned_data.get('planned_date', timezone.now().date())
            
            # Assign driver to all collection entries for this stock order
            collections = Collection.objects.filter(stock_order=stock_order)
            if collections.exists():
                for collection in collections:
                    collection.driver = driver
                    collection.planned_date = planned_date
                    collection.status = 'assigned'
                    collection.save()
                
                # Update stock order status
                stock_order.assign_to_driver(driver)
                messages.success(request, f"Driver {driver.get_full_name()} has been assigned to Stock Order #{stock_order.order_number}.")
            else:
                messages.warning(request, f"No collection entries found for Stock Order #{stock_order.order_number}.")
            
            return redirect('stock_orders:detail', pk=stock_order.pk)
    else:
        form = AssignDriverForm(instance=stock_order)
    
    context = {
        'stock_order': stock_order,
        'form': form,
    }
    
    return render(request, 'stock_orders/assign_driver.html', context)

@login_required
@require_POST
def mark_collected(request, pk):
    """Mark a stock order as collected by the driver"""
    stock_order = get_object_or_404(StockOrder, pk=pk)
    
    # Only mark as collected if it's in assigned status
    if stock_order.status != 'assigned':
        messages.error(request, f"Stock Order #{stock_order.order_number} cannot be marked as collected in its current status.")
    else:
        stock_order.mark_as_collected()
        
        # Move directly to in-stock (bypassing verification)
        stock_order.move_to_stock()
        
        messages.success(request, f"Stock Order #{stock_order.order_number} has been collected and moved to In-Stock!")
    
    return redirect('stock_orders:detail', pk=stock_order.pk)

@login_required
def supplier_list(request):
    """View all suppliers"""
    suppliers = Suppliers.objects.all().order_by('suppliername')  # Changed from Supplier to Suppliers
    
    context = {
        'suppliers': suppliers
    }
    
    return render(request, 'stock_orders/supplier_list.html', context)

@login_required
def supplier_create(request):
    """Create a new supplier"""
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        
        if form.is_valid():
            supplier = form.save()
            messages.success(request, f"Supplier {supplier.suppliername} created successfully!")  # Changed from name to suppliername
            return redirect('stock_orders:supplier_list')
    else:
        form = SupplierForm()
    
    context = {
        'form': form,
        'is_create': True
    }
    
    return render(request, 'stock_orders/supplier_form.html', context)

@login_required
def check_order_number(request):
    """API to check if a stock order number already exists"""
    order_number = request.GET.get('order_number')
    
    if not order_number:
        return JsonResponse({'exists': False})
    
    exists = StockOrder.objects.filter(order_number=order_number).exists()
    
    return JsonResponse({'exists': exists})

# Add this function to your views.py file
@login_required
def supplier_search(request):
    """API endpoint for searching suppliers"""
    search = request.GET.get('q', '')
    
    # Add debug output
    print(f"Supplier search request received: '{search}'")
    
    # Return all suppliers if search is empty or too short
    if not search or len(search) < 2:
        suppliers = Suppliers.objects.all().order_by('suppliername')[:10]
    else:
        # Search in both supplier name and address
        suppliers = Suppliers.objects.filter(
            Q(suppliername__icontains=search) |
            Q(supplieraddress__icontains=search) |
            Q(supply_tags__icontains=search)
        ).order_by('suppliername')[:10]
    
    # Format for Select2
    results = []
    for s in suppliers:
        results.append({
            'id': s.id,
            'text': s.suppliername,
            'address': s.supplieraddress or ''
        })
    
    print(f"Returning {len(results)} suppliers")
    return JsonResponse({'results': results})

@login_required
def check_duplicates(request):
    """API to check for duplicate stock orders"""
    # For now, return empty result as this is complex to implement
    return JsonResponse({'duplicates': []})

@login_required
@require_POST
def cancel_stock_order(request, pk):
    """Cancel a stock order"""
    stock_order = get_object_or_404(StockOrder, pk=pk)
    
    # Don't allow cancellation of already processed orders that are in-stock
    if stock_order.status == 'in_stock':
        messages.error(request, "Cannot cancel a stock order that is already in stock.")
        return redirect('stock_orders:detail', pk=stock_order.pk)
    
    # Update the order status
    stock_order.status = 'canceled'
    stock_order.notes += f"\n\nCANCELLED on {timezone.now().strftime('%Y-%m-%d %H:%M')}\nReason: {request.POST.get('cancel_reason', 'No reason provided')}"
    stock_order.save()
    
    messages.success(request, f"Stock Order #{stock_order.order_number} has been canceled.")
    return redirect('stock_orders:detail', pk=stock_order.pk)

@login_required
def generate_stock_purchase_order(request, stock_order_id):
    try:
        with transaction.atomic():
            stock_order = get_object_or_404(StockOrder, id=stock_order_id)
            supplier = stock_order.supplier
            
            if not supplier:
                messages.error(request, 'No supplier specified for this stock order')
                return redirect('stock_orders:detail', pk=stock_order_id)

            # Get company details - use hardcoded values
            company_name = "CNL Mining Supplies (Pty) Ltd"
            company_address = "47 Station Street, Carletonville, Gauteng 2499"
            company_phone = "+27 18 786 2897"
            company_email = "laura@wfsales.co.za"
            
            # Get logo path
            try:
                # Look for the logo in common locations
                possible_logo_paths = [
                    os.path.join(settings.BASE_DIR, 'static', 'assets', 'images', 'cnl_logo.png'),
                    os.path.join(settings.BASE_DIR, 'static', 'images', 'cnl_logo.png'),
                    os.path.join(settings.BASE_DIR, 'wfdash', 'static', 'assets', 'images', 'cnl_logo.png'),
                ]
                
                logo_path = None
                for path in possible_logo_paths:
                    if path and os.path.exists(path):
                        logo_path = path
                        break
                        
                # If no logo found, create a blank image
                if not logo_path:
                    temp_logo = os.path.join(settings.BASE_DIR, 'temp_logo.png')
                    img = PILImage.new('RGB', (200, 100), color = (255, 255, 255))
                    img.save(temp_logo)
                    logo_path = temp_logo
            except Exception as e:
                logger.error(f"Error finding logo: {str(e)}")
                # Create a blank image as fallback
                temp_logo = os.path.join(settings.BASE_DIR, 'temp_logo.png')
                img = PILImage.new('RGB', (200, 100), color = (255, 255, 255))
                img.save(temp_logo)
                logo_path = temp_logo

            # Get items for this stock order
            items = stock_order.items.all()
            
            if not items.exists():
                messages.error(request, 'No items found for this stock order')
                return redirect('stock_orders:detail', pk=stock_order_id)

            # Get PO number from form or generate new one
            if request.method == 'POST':
                po_number = request.POST.get('po_number')
                email_to = request.POST.get('email_to')  # Get email from form
                email_cc = request.POST.get('email_cc')  # Get CC email from form
                email_message = request.POST.get('email_message')
            else:
                # Generate PO number
                po_number = f"{stock_order.order_number}-PO{datetime.now().strftime('%d%m%y')}"
                email_to = None
                email_cc = None  # Initialize CC email
                email_message = None
            
            # Update stock order with PO number and status
            stock_order.po_number = po_number
            stock_order.status = 'processed'
            stock_order.po_date = timezone.now()
            stock_order.save()

            # Generate PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=letter,
                rightMargin=36,
                leftMargin=36,
                topMargin=36,
                bottomMargin=36
            )
            elements = []
            styles = getSampleStyleSheet()

            # Header with logo and company info
            header_data = [[
                Table([
                    [Paragraph(f"<b>{company_name}</b>", styles['Heading1'])],
                    [Paragraph(company_address, styles['Normal'])],
                    [Paragraph(company_phone, styles['Normal'])],
                    [Paragraph(company_email, styles['Normal'])]
                ], colWidths=[4*inch]),
                Image(logo_path, width=2*inch, height=1.25*inch)
            ]]

            header_table = Table(header_data, colWidths=[4*inch, 4*inch])
            header_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
            ]))
            elements.append(header_table)
            elements.append(Spacer(1, 20))

            # PO Title and Reference
            elements.append(Paragraph("<b>PURCHASE ORDER</b>", styles['Heading1']))
            elements.append(Paragraph(f"PO Number: {po_number}", styles['Normal']))
            elements.append(Paragraph(f"Date: {timezone.now().strftime('%d %B %Y')}", styles['Normal']))
            elements.append(Spacer(1, 20))

            # Supplier and Order details
            details_data = [[
                Table([
                    [Paragraph("<b>SUPPLIER:</b>", styles['Normal'])],
                    [Paragraph(f"{supplier.suppliername}", styles['Normal'])],
                    [Paragraph(f"{getattr(supplier, 'contact', '')}", styles['Normal'])],
                ], colWidths=[3*inch]),
                Table([
                    [Paragraph("<b>STOCK ORDER DETAILS:</b>", styles['Normal'])],
                    [Paragraph(f"Order #: {stock_order.order_number}", styles['Normal'])],
                    [Paragraph(f"Type: Stock Order", styles['Normal'])],
                ], colWidths=[3*inch])
            ]]

            details_table = Table(details_data, colWidths=[4*inch, 4*inch])
            elements.append(details_table)
            elements.append(Spacer(1, 20))

            # Items table
            table_data = [['Description', 'Quantity', 'Unit Price', 'Total']]
            
            # Calculate total
            total_amount = Decimal('0')
            
            for item in items:
                amount = item.quantity * item.unit_price
                total_amount += amount
                
                description_text = item.description
                description_paragraph = Paragraph(description_text, styles['Normal'])
                
                table_data.append([
                    description_paragraph,
                    str(item.quantity),
                    f"R {item.unit_price:,.2f}",
                    f"R {amount:,.2f}"
                ])

                # Try to create driver list pool entry AND collection entry
                try:
                    # Create or update driver list pool entry
                    driver_pool, created = DriverListPool.objects.get_or_create(
                        stock_order=stock_order,
                        stock_item=item,
                        defaults={
                            'order': None,
                            'purchase_order': None,
                            'item': None,
                            'supplier': supplier,
                            'quantity': item.quantity,
                            'status': 'pending'
                        }
                    )
                    
                    # Also create a Collection entry to appear in the driver's collection pool
                    collection, created = Collection.objects.get_or_create(
                        order_item=None,  # Not associated with a regular order item
                        stock_order=stock_order,
                        stock_item=item,
                        defaults={
                            'supplier': supplier,
                            'quantity': item.quantity,
                            'status': 'pending',
                            'description': item.description,
                            'is_manual': False,
                            'unit': 'units'  # Default unit
                        }
                    )
                    
                    logger.info(f"{'Created' if created else 'Updated'} collection entry for {item.description}")
                    
                except Exception as e:
                    logger.error(f"Error creating collection entries: {str(e)}")

                # Create or update collection entry
                try:
                    # Check if a collection already exists
                    collection, created = Collection.objects.get_or_create(
                        stock_order=stock_order,
                        stock_item=item,
                        defaults={
                            'supplier': supplier,
                            'quantity': item.quantity,
                            'description': item.description,  # Ensure description is populated
                            'status': 'pending',
                            'is_manual': False,
                            'notes': f"Stock Order #{stock_order.order_number} | PO: {po_number}"
                        }
                    )
                    
                    # If the collection already existed, update relevant fields
                    if not created:
                        collection.quantity = item.quantity
                        collection.description = item.description  # Make sure description is set
                        collection.notes = f"Stock Order #{stock_order.order_number} | PO: {po_number}"
                        collection.save()
                        
                    logger.info(f"{'Created' if created else 'Updated'} collection entry for stock item: {item.description}")
                except Exception as e:
                    logger.error(f"Error creating collection entry: {str(e)}")

            # Add totals
            subtotal = total_amount
            vat = subtotal * Decimal('0.15')
            total = subtotal + vat

            table_data.extend([
                ['', '', 'Subtotal:', f"R {subtotal:,.2f}"],
                ['', '', 'VAT (15%):', f"R {vat:,.2f}"],
                ['', '', 'Total:', f"R {total:,.2f}"]
            ])

            # Adjust column widths and update table style
            items_table = Table(table_data, colWidths=[4*inch, 1.2*inch, 1.4*inch, 1.4*inch])
            items_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edae41')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
                ('ALIGN', (0, 1), (0, -4), 'LEFT'),  # Left-align description column
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # Vertically center all cells
                ('GRID', (0, 0), (-1, -4), 0.25, colors.grey),
                ('LINEABOVE', (-2, -3), (-1, -3), 1, colors.grey),
                ('LINEABOVE', (-2, -1), (-1, -1), 2, colors.HexColor('#edae41')),
                ('LEFTPADDING', (0, 1), (0, -4), 6),  # Add some padding to description cells
                ('RIGHTPADDING', (0, 1), (0, -4), 6),
                ('TOPPADDING', (0, 1), (-1, -4), 4),  # Add vertical padding for all cells
                ('BOTTOMPADDING', (0, 1), (-1, -4), 4),
            ]))
            elements.append(items_table)

            # Build and save PDF
            doc.build(elements)

            # Save PDF to stock order
            stock_order.pdf_file.save(
                f'PO_{po_number}.pdf',
                ContentFile(buffer.getvalue()),
                save=True
            )

            # Update totals
            stock_order.total_amount = total_amount
            stock_order.save()

            # Send email if email_to is provided
            if email_to:
                try:
                    # Prepare email
                    subject = f'Stock Purchase Order - {po_number}'
                    
                    # Use the custom message if provided, or use a default
                    if not email_message:
                        email_message = f"Please find attached our purchase order #{po_number}.\n\nWe would appreciate your confirmation of this order.\n\nThank you,\n{request.user.get_full_name() or request.user.username}"

                    # Create and send the email
                    email = EmailMessage(
                        subject=subject,
                        body=email_message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        to=[email_to],
                        cc=[email_cc] if email_cc else [],
                        bcc=['gary@wfsales.co.za'],  # Hardcoded BCC
                       
                        
                    )

                    # Attach PO PDF
                    email.attach(
                        f'{po_number}.pdf',
                        stock_order.pdf_file.read(),
                        'application/pdf'
                    )

                    email.send()
                    
                    # Update sent status
                    stock_order.po_sent = True
                    stock_order.email_sent_to = email_to
                    stock_order.save()
                    
                    messages.success(request, f'Purchase Order {po_number} generated and sent to {email_to}' + (f' with CC to {email_cc}' if email_cc else ''))
                except Exception as e:
                    logger.error(f"Error sending email: {str(e)}")
                    messages.warning(request, f'Purchase Order generated but email could not be sent: {str(e)}')
            else:
                messages.success(request, f'Purchase Order {po_number} generated successfully')

            # Check if this is an AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Purchase Order {po_number} processed successfully',
                    'redirect_url': reverse('stock_orders:detail', kwargs={'pk': stock_order.id})
                })

            return redirect('stock_orders:detail', pk=stock_order.id)

    except Exception as e:
        logger.error(f"Error generating stock PO: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': f'Error generating PO: {str(e)}'
            }, status=500)
        
        messages.error(request, f'Error generating PO: {str(e)}')
        return redirect('stock_orders:detail', pk=stock_order_id)

@login_required
def preview_stock_po(request, po_id):
    """Preview the stock purchase order PDF"""
    stock_order = get_object_or_404(StockOrder, id=po_id)
    context = {
        'stock_order': stock_order,
        'title': f'Preview PO - {stock_order.po_number}'
    }
    return render(request, 'stock_orders/po_preview.html', context)

@login_required
def download_stock_po(request, po_id):
    """Download the stock purchase order PDF"""
    stock_order = get_object_or_404(StockOrder, id=po_id)
    if (stock_order.pdf_file):
        response = HttpResponse(stock_order.pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{stock_order.po_number}.pdf"'
        return response
    messages.error(request, 'PDF file not found')
    return redirect('stock_orders:detail', pk=stock_order.id)

@login_required
def email_stock_po(request, po_id):
    """Email the stock purchase order to the supplier"""
    stock_order = get_object_or_404(StockOrder, id=po_id)
    
    try:
        if not stock_order.pdf_file:
            messages.error(request, 'PDF file not found')
            return redirect('stock_orders:preview_po', po_id=stock_order.id)

        # Get supplier email
        supplier_email = getattr(stock_order.supplier, 'email', None)
        if not supplier_email:
            messages.error(request, 'Supplier email not found')
            return redirect('stock_orders:preview_po', po_id=stock_order.id)

        # Prepare email
        subject = f'Stock Purchase Order - {stock_order.po_number}'
        message = render_to_string('stock_orders/email/po_email.html', {
            'stock_order': stock_order,
            'supplier': stock_order.supplier,
        })

        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[supplier_email],
        )

        # Attach PO PDF
        email.attach(
            f'{stock_order.po_number}.pdf',
            stock_order.pdf_file.read(),
            'application/pdf'
        )

        email.send()
        
        # Update sent status
        stock_order.po_sent = True
        stock_order.save()

        messages.success(request, f'Purchase Order {stock_order.po_number} sent to {supplier_email}')
    except Exception as e:
        messages.error(request, f'Error sending email: {str(e)}')
    
    return redirect('stock_orders:preview_po', po_id=stock_order.id)

@login_required
def download_po(request, pk):
    try:
        stock_order = get_object_or_404(StockOrder, id=pk)
        items = stock_order.items.all()
        
        # Create a file-like buffer to receive PDF data
        buffer = BytesIO()
        
        # Create the PDF object, using the buffer as its "file"
        doc = SimpleDocTemplate(buffer, pagesize=letter, 
                               rightMargin=36, leftMargin=36,
                               topMargin=36, bottomMargin=36)
        
        # Container for the 'Flowable' objects
        elements = []
        styles = getSampleStyleSheet()
        
        # Company information
        elements.append(Paragraph("<b>CNL Mining Supplies (Pty) Ltd</b>", styles['Heading1']))
        elements.append(Paragraph("47 Station Street<br/>Carletonville, Gauteng 2499<br/>+27 18 786 2897<br/>laura@wfsales.co.za", styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # PO Header
        elements.append(Paragraph("<b>PURCHASE ORDER</b>", styles['Heading1']))
        elements.append(Paragraph(f"PO #: {stock_order.order_number}", styles['Normal']))
        elements.append(Paragraph(f"Date: {stock_order.created_at.strftime('%B %d, %Y')}", styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # Supplier information - Fix the attribute name here
        elements.append(Paragraph("<b>SUPPLIER:</b>", styles['Normal']))
        elements.append(Paragraph(f"{stock_order.supplier.suppliername}", styles['Normal']))  # Changed name to suppliername
        elements.append(Spacer(1, 20))
        
        # Create table for items
        data = [['Description', 'Quantity', 'Unit Price', 'Total']]
        
        # Calculate totals
        total_amount = Decimal('0.00')
        
        # Add items to table
        for item in items:
            total = item.quantity * item.unit_price
            total_amount += total
            data.append([
                item.description,
                str(item.quantity),
                f"R {item.unit_price:.2f}",
                f"R {total:.2f}"
            ])
        
        # Add totals to table
        vat = total_amount * Decimal('0.15')
        grand_total = total_amount + vat
        
        data.append(['', '', 'Subtotal:', f"R {total_amount:.2f}"])
        data.append(['', '', 'VAT (15%):', f"R {vat:.2f}"])
        data.append(['', '', 'Total:', f"R {grand_total:.2f}"])
        
        # Create the table
        table = Table(data)
        
        # Add style to table
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (3, 0), colors.lightgreen),
            ('TEXTCOLOR', (0, 0), (3, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (3, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (3, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (3, 0), 12),
            ('BACKGROUND', (0, 1), (3, -4), colors.beige),
            ('GRID', (0, 0), (3, -1), 1, colors.black),
            ('ALIGN', (1, 1), (3, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (3, -1), 'MIDDLE'),
        ]))
        
        elements.append(table)
        
        # Build the document
        doc.build(elements)
        
        # FileResponse sets the Content-Disposition header so that browsers
        # present the option to save the file.
        buffer.seek(0)
        return FileResponse(buffer, as_attachment=True, filename=f'PO_{stock_order.order_number}.pdf')
    
    except Exception as e:
        messages.error(request, f"Error generating PDF: {str(e)}")
        return redirect('stock_orders:detail', pk=pk)