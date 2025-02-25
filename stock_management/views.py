from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db import models  # Add this import
from decimal import Decimal  # Add this import
from .models import StockItem
from driver_list.models import Collection
from itertools import groupby
from operator import attrgetter
import logging
import json  # Add this import
import os  # Add this import
from django.views.decorators.http import require_POST, require_http_methods  # Add require_http_methods here
from django.views.decorators.csrf import ensure_csrf_cookie  # Add this import
from reportlab.lib import colors  # Add this import
from reportlab.lib.pagesizes import letter, A4  # Add A4 import
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer  # Add this import
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle  # Add ParagraphStyle import
from reportlab.lib.units import inch, cm, mm  # Add cm import
from io import BytesIO  # Add this import
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image
from django.db import transaction
from django.core.exceptions import ValidationError
from django.contrib import messages
from .utils import is_mobile

logger = logging.getLogger(__name__)

# Add this function to check status changes
def debug_item_status(item, before_status, after_status):
    logger.info(f"""
    Item Status Change:
    ID: {item.id}
    Before: {before_status}
    After: {after_status}
    Picked: {item.picked}
    Picked By: {item.picked_by}
    """)

@login_required
def stock_verification(request):
    collections = Collection.objects.filter(
        status='collected',
        stockitem__isnull=True  # Only show unverified collections
    ).select_related(
        'order_item__order',
        'supplier',
        'driver'
    ).order_by('supplier__suppliername')
    template_name = (
        'stock_management/stock_verification_mobile.html' 
        if is_mobile(request) 
        else 'stock_management/stock_verification.html'
    )
    return render(request, template_name, {'collections': collections})

@login_required
def verify_stock(request, collection_id):
    if request.method == 'POST':
        collection = get_object_or_404(Collection, id=collection_id)        
        
        try:
            external_invoice_number = request.POST.get('external_invoice_number')
            external_invoice_date = request.POST.get('external_invoice_date')
            verified_quantity = Decimal(request.POST.get('verified_quantity'))
            notes = request.POST.get('notes', '')

            # Get required quantity from original order item
            required_quantity = collection.order_item.quantity  # Original required quantity

            # If verified quantity matches collected quantity
            if verified_quantity != collection.received_qty:
                messages.error(request, 'Verified quantity must match received quantity')
                return redirect('stock_management:stock_verification')

            # Create main stock item with required quantity
            if verified_quantity > required_quantity:
                # Create stock item for required quantity
                main_stock = StockItem.objects.create(
                    collection=collection,
                    order_item=collection.order_item,
                    received_qty=required_quantity,
                    verified_quantity=required_quantity,
                    external_invoice_number=external_invoice_number,
                    external_invoice_date=external_invoice_date,
                    verified_by=request.user,
                    notes=notes,
                    status='in_stock'
                )

                # Create office stock item for excess quantity
                excess_qty = verified_quantity - required_quantity
                office_stock = StockItem.objects.create(
                    collection=collection,
                    order_item=collection.order_item,
                    received_qty=excess_qty,
                    verified_quantity=excess_qty,
                    external_invoice_number=external_invoice_number,
                    external_invoice_date=external_invoice_date,
                    verified_by=request.user,
                    notes=f"Excess stock from collection {collection.id}. {notes}",
                    status='office_stock'
                )

                messages.success(
                    request, 
                    f'Stock verified. {excess_qty} units moved to office stock.'
                )

            else:
                # If verified quantity equals or is less than required, create single stock item
                StockItem.objects.create(
                    collection=collection,
                    order_item=collection.order_item,
                    received_qty=verified_quantity,
                    verified_quantity=verified_quantity,
                    external_invoice_number=external_invoice_number,
                    external_invoice_date=external_invoice_date,
                    verified_by=request.user,
                    notes=notes,
                    status='in_stock'
                )
                messages.success(request, 'Stock verified successfully')        
            return redirect('stock_management:stock_verification')            
        except Exception as e:
            messages.error(request, f'Error verifying stock: {str(e)}')
            return redirect('stock_management:stock_verification')
    return redirect('stock_management:stock_verification')

@login_required
def stock_list(request):
    """View all stock items"""
    stock_items = StockItem.objects.filter(
        status='in_stock'
    ).select_related(
        'order_item__order',
        'order_item__purchase_order',
        'collection__supplier'
    ).order_by('order_item__order__order_number', 'created_at')

    # Group items by order number
    grouped_items = {}
    for item in stock_items:
        order_number = item.order_item.order.order_number
        if order_number not in grouped_items:
            grouped_items[order_number] = []
        grouped_items[order_number].append(item)

    context = {
        'grouped_items': grouped_items,
        'page_title': 'Current Stock'
    }
    return render(request, 'stock_management/stock_list.html', context)

@login_required
def update_invoice(request, stock_id):
    """Update invoice details and split excess stock"""
    if request.method == 'POST':
        stock_item = get_object_or_404(StockItem, id=stock_id)
        invoice_number = request.POST.get('invoice_number')
        invoice_date = request.POST.get('invoice_date')
        
        try:
            # Get order quantity and already invoiced quantity
            order_qty = stock_item.order_item.quantity
            already_invoiced = StockItem.objects.filter(
                order_item=stock_item.order_item,
                status='invoiced'
            ).aggregate(total=models.Sum('received_qty'))['total'] or 0
            
            remaining_needed = order_qty - already_invoiced
            if stock_item.received_qty > remaining_needed and remaining_needed > 0:
                # Create new stock item for excess
                excess_qty = stock_item.received_qty - remaining_needed
                # Update original item with needed quantity
                stock_item.received_qty = remaining_needed
                stock_item.invoice_number = invoice_number
                stock_item.invoice_date = invoice_date
                stock_item.status = 'invoiced'
                stock_item.save()
                
                # Create new item for excess
                StockItem.objects.create(
                    collection=stock_item.collection,
                    order_item=stock_item.order_item,
                    received_qty=excess_qty,
                    verified_quantity=excess_qty,
                    external_invoice_number=stock_item.external_invoice_number,
                    external_invoice_date=stock_item.external_invoice_date,
                    verified_by=stock_item.verified_by,
                    status='office_stock'
                )
                
                messages.success(
                    request, 
                    f'Invoice updated. {excess_qty} units moved to office stock.'
                )
            else:
                # Update original item as normal
                stock_item.invoice_number = invoice_number
                stock_item.invoice_date = invoice_date
                stock_item.status = 'invoiced'
                stock_item.save()
                messages.success(request, 'Invoice details updated successfully')
                
        except Exception as e:
            messages.error(request, f'Error updating invoice: {str(e)}')
    return redirect('stock_management:stock_list')

@login_required
def ready_for_delivery(request):
    """View items ready for delivery"""
    stock_items = StockItem.objects.filter(
        status='ready_for_delivery',
        picked=True
    ).select_related(
        'order_item__order',
        'collection__supplier'
    ).order_by('invoice_date')
    
    # Group items by invoice
    grouped_items = {}
    for item in stock_items:
        if item.invoice_number not in grouped_items:
            grouped_items[item.invoice_number] = {
                'items': [],
                'total_items': 0,
                'invoice_date': item.invoice_date,
                'customer': item.order_item.order.company.company,
                'item_ids': []  # Add this line
            }
        grouped_items[item.invoice_number]['items'].append(item)
        grouped_items[item.invoice_number]['total_items'] += 1
        grouped_items[item.invoice_number]['item_ids'].append(str(item.id))  # Add this line

    context = {
        'grouped_items': grouped_items,
        'page_title': 'Ready for Delivery'
    }
    return render(request, 'stock_management/ready_for_delivery.html', context)

@login_required
@ensure_csrf_cookie
def ready_to_pick(request):
    """View items ready to pick grouped by invoice"""
    stock_items = StockItem.objects.filter(
        status='invoiced',
        picked=False
    ).select_related(
        'order_item__order__company',
        'collection__supplier',
        'order_item__purchase_order'  # Add this line
    ).order_by('invoice_number', 'invoice_date')

    # Group items by invoice number
    invoices = {}
    picking_data = {}
    
    for item in stock_items:
        if item.invoice_number:
            if item.invoice_number not in invoices:
                invoices[item.invoice_number] = []
            invoices[item.invoice_number].append(item)
            # Prepare data for JavaScript
            if item.invoice_number not in picking_data:
                picking_data[item.invoice_number] = []
            
            # Get PO number safely
            po_number = item.order_item.purchase_order.po_number if item.order_item.purchase_order else 'N/A'
            
            picking_data[item.invoice_number].append({
                'id': item.id,
                'description': item.order_item.description,
                'quantity': str(item.received_qty),
                'supplier': item.collection.supplier.suppliername if item.collection and item.collection.supplier else 'N/A',
                'po_number': po_number,  # Add PO number here
                'customer': item.order_item.order.company.company
            })

    context = {
        'invoices': invoices,
        'picking_data': json.dumps(picking_data),
        'page_title': 'Ready to Pick'
    }
    return render(request, 'stock_management/ready_to_pick.html', context)

@login_required
@require_POST
def mark_picked(request, item_id):
    """Mark an item as picked and move to delivery pick list"""
    try:
        item = StockItem.objects.get(id=item_id)
        # Store current status for debugging
        before_status = item.status
        
        # Toggle picked status
        item.picked = not item.picked
        
        if item.picked:
            # When marking as picked
            item.picked_by = request.user
            item.picked_date = timezone.now()
            item.status = 'picked'  # Set status to 'picked' for delivery pick list
        else:
            # When unmarking
            item.picked_by = None
            item.picked_date = None
            item.status = 'invoiced'  # Reset to previous status
        
        item.save()
        # Log status change for debugging
        debug_item_status(item, before_status, item.status)
        
        return JsonResponse({
            'status': 'success',
            'message': 'Item marked as picked' if item.picked else 'Item unmarked',
            'new_status': item.status
        })
    except StockItem.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Item not found'
        })
    except Exception as e:
        logger.error(f"Error in mark_picked: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        })

@login_required
@require_http_methods(["POST"])
def save_picking_progress(request):
    try:
        data = json.loads(request.body)
        invoice = data.get('invoice')
        items = data.get('items', [])
        logger.info(f"Saving picking progress - Invoice: {invoice}, Items: {len(items)}")
        if not invoice:
            return JsonResponse({'status': 'error', 'message': 'Invoice number required'})
        
        for item_data in items:
            item_id = item_data.get('id')
            picked = item_data.get('picked', False)
            
            try:
                item = StockItem.objects.get(id=item_id)
                if picked:
                    item.status = 'picked'  # Changed from 'ready_for_delivery' to 'picked'
                    item.picked = True
                    item.picked_by = request.user
                    item.picked_date = timezone.now()
                item.save()
                # Log status change
                logger.info(f"Item {item_id} status updated to: {item.status}")
                
            except StockItem.DoesNotExist:
                logger.error(f"Item not found: {item_id}")
                continue
                
        return JsonResponse({
            'status': 'success',
            'message': 'Picking progress saved'
        })
        
    except Exception as e:
        logger.error(f"Error saving picking progress: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
def generate_picking_slip_pdf(request, invoice_number):
    """Generate PDF picking slip with modern styling"""
    stock_items = StockItem.objects.filter(
        invoice_number=invoice_number
    ).select_related(
        'order_item__order__company',
        'collection__supplier',
        'order_item__purchase_order'
    )
    
    if not stock_items.exists():
        return HttpResponse('No items found', status=404)

    # Create the PDF document
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30*mm,
        leftMargin=30*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )

    elements = []
    styles = getSampleStyleSheet()

    # Add company logo
    logo_path = 'static/images/company-logo.png'  # Update with your logo path
    if os.path.exists(logo_path):
        img = Image(logo_path, width=60*mm, height=30*mm)
        elements.append(img)

    # Modern title style
    title_style = ParagraphStyle(
        'ModernTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=HexColor('#1a237e'),  # Dark blue
        spaceAfter=30,
        spaceBefore=30,
        alignment=1  # Center alignment
    )
    elements.append(Paragraph('Picking Slip', title_style))

    # Modern header style
    header_style = ParagraphStyle(
        'ModernHeader',
        parent=styles['Normal'],
        fontSize=12,
        textColor=HexColor('#37474f'),  # Dark gray
        spaceBefore=6,
        spaceAfter=6
    )

    # Add header information in a more structured way
    header_data = [
        [Paragraph(f'<b>Invoice #:</b> {invoice_number}', header_style), Paragraph(f'<b>Date:</b> {timezone.now().strftime("%Y-%m-%d")}', header_style)],
        [Paragraph(f'<b>Customer:</b> {stock_items[0].order_item.order.company.company}', header_style), Paragraph('', header_style)]  # Empty cell for alignment
    ]
    header_table = Table(header_data, colWidths=[250, 250])
    header_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 20))

    # Modern table style
    data = [['Description', 'Qty', 'Supplier', 'PO #', 'Picked']]
    for item in stock_items:
        data.append([
            item.order_item.description,
            str(item.received_qty),
            item.collection.supplier.suppliername if item.collection and item.collection.supplier else 'N/A',
            item.order_item.purchase_order.po_number if item.order_item.purchase_order else 'N/A',
            '☐'  # Modern checkbox symbol
        ])

    table = Table(data, colWidths=[220, 60, 100, 70, 50])
    table.setStyle(TableStyle([
        # Header style
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a237e')),  # Dark blue header
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        # Table body
        ('GRID', (0, 0), (-1, -1), 1, HexColor('#e0e0e0')),  # Light gray grid
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 12),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#f5f5f5'), HexColor('#ffffff')]),  # Zebra striping
    ]))
    elements.append(table)

    # Modern signature section
    elements.append(Spacer(1, 40))
    signature_style = ParagraphStyle(
        'SignatureStyle',
        parent=styles['Normal'],
        fontSize=11,
        textColor=HexColor('#37474f')
    )
    
    signature_data = [
        [Paragraph('Picked by:', signature_style), '_' * 40],
        [Paragraph('Date:', signature_style), '_' * 40],
        [Paragraph('Signature:', signature_style), '_' * 40]
    ]
    signature_table = Table(signature_data, colWidths=[100, 200])
    signature_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(signature_table)

    # Build PDF
    doc.build(elements)
    # FileResponse sets the Content-Disposition header
    buffer.seek(0)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="picking_slip_{invoice_number}.pdf"'
    response.write(buffer.getvalue())
    buffer.close()

    return response

@login_required
def office_stock(request):
    """View office stock items"""
    stock_items = StockItem.objects.filter(
        status='office_stock'
    ).select_related(
        'order_item__order',
        'collection__supplier'
    ).order_by('external_invoice_date')    
    
    context = {
        'stock_items': stock_items,
        'page_title': 'Office Stock'
    }
    return render(request, 'stock_management/office_stock.html', context)

@login_required
@ensure_csrf_cookie
def delivery_pick_list(request):
    """View items that have been picked and are ready to be loaded"""
    stock_items = StockItem.objects.filter(
        status='picked',  # Only show items with 'picked' status
        picked=True      # Ensure they are actually marked as picked
    ).select_related(
        'order_item__order__company',
        'collection__supplier',
        'order_item__purchase_order'
    ).order_by('invoice_number', 'invoice_date')
    # Add debug logging
    logger.info(f"Delivery Pick List - Found {stock_items.count()} items")
    
    # Group items by invoice number
    invoices = {}
    loading_data = {}
    
    for item in stock_items:
        if item.invoice_number:
            if item.invoice_number not in invoices:
                invoices[item.invoice_number] = []
            invoices[item.invoice_number].append(item)
            if item.invoice_number not in loading_data:
                loading_data[item.invoice_number] = []
            
            po_number = item.order_item.purchase_order.po_number if item.order_item.purchase_order else 'N/A'
            
            loading_data[item.invoice_number].append({
                'id': item.id,
                'description': item.order_item.description,
                'quantity': str(item.received_qty),
                'supplier': item.collection.supplier.suppliername if item.collection and item.collection.supplier else 'N/A',
                'po_number': po_number,
                'customer': item.order_item.order.company.company
            })
    context = {
        'invoices': invoices,
        'loading_data': json.dumps(loading_data),
        'page_title': 'Delivery Pick List'
    }
    return render(request, 'stock_management/delivery_pick_list.html', context)

@login_required
@require_POST
def mark_loaded(request, item_id):
    """Mark an item as loaded for delivery"""
    try:
        item = StockItem.objects.get(id=item_id)
        
        # Log the status change
        logger.info(f"Marking item {item_id} as loaded. Current status: {item.status}")
        
        # Update item status
        item.status = 'ready_for_delivery'
        item.loaded_by = request.user
        item.loaded_date = timezone.now()
        item.save()
        logger.info(f"Item {item_id} marked as loaded. New status: {item.status}")
        
        return JsonResponse({
            'status': 'success',
            'message': 'Item marked as loaded'
        })
    except StockItem.DoesNotExist:
        logger.error(f"Item {item_id} not found")
        return JsonResponse({
            'status': 'error',
            'message': 'Item not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error marking item {item_id} as loaded: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
@require_POST
def mark_group_delivered(request):
    logger.info("Processing mark_group_delivered request")
    try:
        data = json.loads(request.body)
        item_ids = data.get('item_ids', [])
        delivery_date = data.get('delivery_date')
        invoice_number = data.get('invoice_number')
        logger.info(f"Received data: items={item_ids}, date={delivery_date}, invoice={invoice_number}")
        if not all([item_ids, delivery_date, invoice_number]):
            raise ValidationError('Missing required fields')

        with transaction.atomic():
            # Convert item_ids to list if it's not already
            if isinstance(item_ids, str):
                item_ids = item_ids.split(',')

            items = StockItem.objects.filter(id__in=item_ids)
            
            if not items.exists():
                raise ValidationError('No items found with provided IDs')

            for item in items:
                logger.info(f"Processing item {item.id}: current status={item.status}")
                if item.invoice_number != invoice_number:
                    raise ValidationError(f'Invoice number mismatch for item {item.id}')
                
                item.status = 'delivered'
                item.delivered_by = request.user
                item.delivered_date = delivery_date
                item.save()
                logger.info(f"Updated item {item.id} to delivered status")

        return JsonResponse({
            'status': 'success',
            'message': f'Successfully marked {len(item_ids)} items as delivered'
        })
    except ValidationError as e:
        logger.error(f"Validation error: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid request format'
        }, status=400)
    except Exception as e:
        logger.error(f"Unexpected error in mark_group_delivered: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'An error occurred: {str(e)}'
        }, status=500)

def some_view(request):
    new_stock_items_count = StockItem.objects.filter(seen=False).count()
    return render(request, 'your_template.html', {
        'new_stock_items_count': new_stock_items_count,
        # other context variables
    })