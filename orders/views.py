from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages 
from django.db.models import Q, Case, When  # Add Case and When here
from .models import Order, OrderItem, PurchaseOrder
from wfdash.models import Company, Suppliers, CompanyDetails  # Add CompanyDetails import
from .utils import is_mobile
from django.http import JsonResponse, HttpResponse
from .forms import OrderForm, OrderItemFormSet
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Image, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from decimal import Decimal, InvalidOperation
from io import BytesIO
from django.utils import timezone
from django.core.files.base import ContentFile
from driver_list.models import Collection, DriverListPool  # Add DriverListPool import
import json  # Add this import
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
import logging
from django.db import transaction  # Add this import at the top
from django.urls import reverse
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
logger = logging.getLogger(__name__)

def is_mobile(request):
    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    return any(device in user_agent for device in ['mobile', 'android', 'iphone', 'ipad'])

@login_required
def order_list(request):
    # Add status colors to context
    STATUS_COLORS = {
        'new': 'primary',
        'processing': 'info',
        'order_ready': 'warning',
        'po_generated': 'secondary',
        'completed': 'success',
        'cancelled': 'danger'
    }
    
    search_query = request.GET.get('search', '')
    orders = Order.objects.filter(rep=request.user).select_related('company')
    
    if search_query:
        orders = orders.filter(
            Q(order_number__icontains=search_query) |
            Q(company__company__icontains=search_query)
        )
    
    orders = orders.order_by(
        Case(
            When(status='new', then=0),
            When(status='processing', then=1),
            When(status='order_ready', then=2),
            When(status='po_generated', then=3),
            When(status='completed', then=4),
            When(status='cancelled', then=5),
            default=6,
        ),
        '-created_at'
    )
    
    return render(request, 'orders/order_list.html', {
        'orders': orders,
        'search_query': search_query,
        'status_colors': STATUS_COLORS
    })

@login_required
def order_create(request):
    if request.method == 'POST':
        order_form = OrderForm(request.POST)
        if order_form.is_valid():
            order = order_form.save(commit=False)
            order.rep = request.user
            order.save()

            # Process items
            descriptions = request.POST.getlist('description[]')
            quantities = request.POST.getlist('quantity[]')
            selling_prices = request.POST.getlist('selling_price[]')
            notes = request.POST.getlist('notes[]')

            for i in range(len(descriptions)):
                if descriptions[i]:  # Only create item if description exists
                    OrderItem.objects.create(
                        order=order,
                        description=descriptions[i],
                        quantity=quantities[i],
                        selling_price=selling_prices[i] or 0,
                        notes=notes[i]
                    )

            return redirect('orders:order_list')
    else:
        order_form = OrderForm()

    return render(request, 'orders/order_form.html', {
        'form': order_form,
    })

@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    suppliers = Suppliers.objects.filter(
        id__in=order.items.filter(supplier__isnull=False).values_list('supplier', flat=True).distinct()
    )
    
    context = {
        'order': order,
        'suppliers': suppliers,
        'segment': 'orders',
        'title': f'Order #{order.order_number}'
    }
    return render(request, 'orders/order_detail.html', context)

@login_required
def order_edit(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if order.status != 'new':
        messages.error(request, 'Only new orders can be edited')
        return redirect('orders:order_detail', pk=order.pk)
        
    template = 'orders/mobile/order_form.html' if is_mobile(request) else 'orders/order_form.html'
    
    if request.method == 'POST':
        form = OrderForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            
            # Update existing items and add new ones
            order.items.all().delete()  # Remove existing items
            
            descriptions = request.POST.getlist('description[]')
            quantities = request.POST.getlist('quantity[]')
            suppliers = request.POST.getlist('supplier[]')
            
            for description, quantity, supplier in zip(descriptions, quantities, suppliers):
                if description and quantity and supplier:
                    try:
                        OrderItem.objects.create(
                            order=order,
                            description=description,
                            quantity=int(quantity),
                            supplier_id=supplier
                        )
                    except ValueError:
                        messages.error(request, "Invalid quantity value provided")
                        break
            else:
                messages.success(request, 'Order updated successfully')
                return redirect('orders:order_detail', pk=order.pk)
    else:
        form = OrderForm(instance=order)
    
    return render(request, template, {
        'form': form,
        'order': order,
        'customers': Customers.objects.all().order_by('company'),
        'suppliers': Suppliers.objects.all().order_by('suppliername')
    })

@login_required
def order_delete(request, pk):
    if request.method == 'POST':
        order = get_object_or_404(Order, pk=pk)
        order.delete()
        messages.success(request, 'Order deleted successfully')
        return redirect('orders:order_list')
    return redirect('orders:order_list')

@login_required
def process_order(request, pk):
    order = get_object_or_404(Order, pk=pk)
    items = OrderItem.objects.filter(order=order)
    suppliers = Suppliers.objects.all()
    
    # Group items by supplier for PO generation
    suppliers_items = {}
    has_items_with_suppliers = False
    
    for item in items:
        if item.supplier:
            has_items_with_suppliers = True
            if item.supplier not in suppliers_items:
                suppliers_items[item.supplier] = []
            suppliers_items[item.supplier].append(item)
    
    context = {
        'order': order,
        'items': items,
        'suppliers': suppliers,
        'suppliers_items': suppliers_items,
        'has_items_with_suppliers': has_items_with_suppliers
    }
    
    return render(request, 'orders/order_process.html', context)

@login_required
def generate_purchase_order(request, order_id, supplier_id):
    try:
        with transaction.atomic():
            order = get_object_or_404(Order, id=order_id)
            supplier = get_object_or_404(Suppliers, id=supplier_id)
            
            # Get company details - update this part
            company_details = CompanyDetails.objects.first()  # Get the company details
            if not company_details:
                messages.error(request, 'Company details not found')
                return redirect('orders:order_detail', pk=order_id)

            # Get items for this supplier that aren't in a PO yet
            items = order.items.filter(
                supplier=supplier,
                item_status='processed',
                purchase_order__isnull=True
            )
            
            if not items.exists():
                messages.error(request, 'No items found for this supplier')
                return redirect('orders:order_detail', pk=order_id)

            # Generate PO number
            last_po = PurchaseOrder.objects.filter(
                po_number__startswith='PO'
            ).order_by('-po_number').first()

            if last_po:
                try:
                    last_number = int(last_po.po_number.split('-')[0][2:])
                    next_number = str(last_number + 1).zfill(5)
                except (ValueError, IndexError):
                    next_number = '00001'
            else:
                next_number = '00001'
            
            # Format PO number with company prefix
            company_prefix = ''.join(order.company.company.split()[:1])[0:3].upper()
            po_number = f'PO{next_number}-{company_prefix}'

            # Create PO
            po = PurchaseOrder.objects.create(
                po_number=po_number,
                order=order,
                supplier=supplier,
                status='draft'
            )

            # Update items and calculate total
            total_amount = Decimal('0')
            for item in items:
                item.purchase_order = po
                item.item_status = 'po_generated'
                item.save()
                
                # Use order_qty instead of quantity
                total_amount += item.order_qty * item.cost_price

                # Create driver list pool entry
                DriverListPool.objects.create(
                    order=order,
                    purchase_order=po,
                    item=item,
                    supplier=supplier,
                    quantity=item.order_qty,  # Use order_qty here
                    status='pending'
                )

                # Create Collection entry
                Collection.objects.create(
                    order_item=item,
                    supplier=supplier,
                    quantity=item.order_qty,  # Use order_qty here
                    status='pending'
                )

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
                    [Paragraph("<b>CNL Mining Supplies (Pty) Ltd</b>", styles['Heading1'])],
                    [Paragraph("47 Station Street", styles['Normal'])],
                    [Paragraph("Carletonville, Gauteng 2499", styles['Normal'])],
                    [Paragraph("+27 18 786 2897", styles['Normal'])],
                    [Paragraph("laura@wfsales.co.za", styles['Normal'])]
                ], colWidths=[4*inch]),
                Image(company_details.logo.path, width=2*inch, height=1.25*inch)
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
                    [Paragraph("<b>ORDER DETAILS:</b>", styles['Normal'])],
                    [Paragraph(f"Order #: {order.order_number}", styles['Normal'])],
                    [Paragraph(f"Customer: {order.company.company}", styles['Normal'])],
                ], colWidths=[3*inch])
            ]]
            
            details_table = Table(details_data, colWidths=[4*inch, 4*inch])
            elements.append(details_table)
            elements.append(Spacer(1, 20))

            # Items table
            table_data = [['Description', 'Quantity', 'Unit Price', 'Total']]
            for item in items:
                amount = item.order_qty * item.cost_price
                table_data.append([
                    item.description,
                    str(item.order_qty),
                    f"R {item.cost_price:,.2f}",
                    f"R {amount:,.2f}"
                ])

            # Add totals
            subtotal = total_amount
            vat = subtotal * Decimal('0.15')
            total = subtotal + vat

            table_data.extend([
                ['', '', 'Subtotal:', f"R {subtotal:,.2f}"],
                ['', '', 'VAT (15%):', f"R {vat:,.2f}"],
                ['', '', 'Total:', f"R {total:,.2f}"]
            ])

            items_table = Table(table_data, colWidths=[4*inch, 1.2*inch, 1.4*inch, 1.4*inch])
            items_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5B6711')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -4), 0.25, colors.grey),
                ('LINEABOVE', (-2, -3), (-1, -3), 1, colors.grey),
                ('LINEABOVE', (-2, -1), (-1, -1), 2, colors.HexColor('#5B6711')),
            ]))
            elements.append(items_table)

            # Build and save PDF
            doc.build(elements)
            
            # Save to PO
            po.pdf_file.save(
                f'PO_{po_number}.pdf',
                ContentFile(buffer.getvalue()),
                save=True
            )

            # Update PO total and save
            po.total_amount = total_amount
            po.save()

            # Update order status
            order.update_order_status()

            messages.success(request, f'Purchase Order {po_number} generated successfully')
            return redirect('orders:preview_po', po_id=po.id)  # Updated redirect

    except Exception as e:
        logger.error(f"Error generating PO: {str(e)}")
        messages.error(request, f'Error generating PO: {str(e)}')
        return redirect('orders:order_detail', pk=order_id)

@require_http_methods(["POST"])
@login_required
def save_order_item(request, item_id):
    try:
        data = json.loads(request.body)
        item = get_object_or_404(OrderItem, id=item_id)
        
        # Update item details
        if 'supplier_id' in data:
            item.supplier_id = data['supplier_id']
        if 'cost_price' in data:
            item.cost_price = Decimal(str(data['cost_price']))
        if 'quantity' in data:
            item.order_qty = int(data['quantity'])
            
        item.item_status = 'processed'
        item.save()
        
        # Calculate markup
        if item.cost_price and item.selling_price:
            markup = ((item.selling_price - item.cost_price) / item.cost_price) * 100
        else:
            markup = 0
            
        return JsonResponse({
            'status': 'success',
            'message': 'Item saved successfully',
            'data': {
                'id': item.id,
                'markup': round(markup, 2),
                'status': item.item_status
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
def split_order_item(request, item_id):
    if request.method == 'POST':
        item = get_object_or_404(OrderItem, id=item_id)
        split_qty = int(request.POST.get('split_quantity', 0))
        
        if split_qty > 0 and split_qty < item.quantity:
            # Create new item
            new_item = OrderItem.objects.create(
                order=item.order,
                description=item.description,
                quantity=split_qty,
                selling_price=item.selling_price,
                cost_price=item.cost_price,
                markup=item.markup
            )
            
            # Update original item quantity
            item.quantity -= split_qty
            item.save()
            
            return JsonResponse({
                'status': 'success',
                'original_qty': item.quantity,
                'new_item': {
                    'id': new_item.id,
                    'quantity': new_item.quantity,
                    'description': new_item.description
                }
            })
    
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def purchase_order_list(request):
    purchase_orders = PurchaseOrder.objects.all().order_by('-created_at')
    return render(request, 'orders/purchase_order_list.html', {
        'purchase_orders': purchase_orders
    })

@login_required
def download_purchase_order(request, po_id):
    try:
        po = get_object_or_404(PurchaseOrder, id=po_id)
        if po.pdf_file:
            response = HttpResponse(po.pdf_file, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{po.po_number}.pdf"'
            return response
        raise ValueError("PDF file not found")
    except Exception as e:
        messages.error(request, f'Error downloading PO: {str(e)}')
        return redirect('orders:order_detail', pk=po.order.id)

@login_required
def check_available_po_items(request, order_id, supplier_id):
    items = OrderItem.objects.filter(
        order_id=order_id,
        supplier_id=supplier_id,
        purchase_order__isnull=True,
        item_status='processed'
    )
    
    data = {
        'available_items': [
            {
                'id': item.id,
                'description': item.description,
                'quantity': item.order_qty,
                'cost_price': str(item.cost_price)
            }
            for item in items
        ]
    }
    
    return JsonResponse(data)

@login_required
def preview_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    return render(request, 'orders/po_preview.html', {'po': po})

@login_required
def download_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    if po.pdf_file:
        response = HttpResponse(po.pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{po.po_number}.pdf"'
        return response
    messages.error(request, 'PDF file not found')
    return redirect('orders:order_detail', pk=po.order.id)

@login_required
def email_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    if po.pdf_file:
        # Create mailto URL with attachment
        mailto_url = (
            f"mailto:{po.supplier.email if hasattr(po.supplier, 'email') else ''}"
            f"?subject=Purchase Order - {po.po_number}"
            f"&body=Please find attached purchase order {po.po_number}."
        )
        return HttpResponse(
            f'<script>window.location.href = "{mailto_url}";</script>'
        )
    messages.error(request, 'PDF file not found')
    return redirect('orders:order_detail', pk=po.order.id)

@login_required
def preview_purchase_order(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    context = {
        'po': po,
        'title': f'Preview PO - {po.po_number}'
    }
    return render(request, 'orders/po_preview.html', context)

@login_required
def email_purchase_order(request, po_id):
    try:
        po = get_object_or_404(PurchaseOrder, id=po_id)
        
        if not po.pdf_file:
            messages.error(request, 'PDF file not found')
            return redirect('orders:preview_po', po_id=po.id)

        # Get supplier email
        supplier_email = getattr(po.supplier, 'email', None)
        if not supplier_email:
            messages.error(request, 'Supplier email not found')
            return redirect('orders:preview_po', po_id=po.id)

        # Prepare email
        subject = f'Purchase Order - {po.po_number}'
        message = render_to_string('orders/email/po_email.html', {
            'po': po,
            'supplier': po.supplier,
        })
        
        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[supplier_email],
        )
        
        # Attach PO PDF
        email.attach(
            f'{po.po_number}.pdf',
            po.pdf_file.read(),
            'application/pdf'
        )
        
        email.send()
        
        messages.success(request, f'Purchase Order {po.po_number} sent to {supplier_email}')
        return redirect('orders:preview_po', po_id=po.id)

    except Exception as e:
        messages.error(request, f'Error sending email: {str(e)}')
        return redirect('orders:preview_po', po_id=po.id)

@login_required
def generate_quote_pdf(request, quote_id):
    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id)
        items = quote.items.all()

        # Create PDF buffer
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

        # Add custom styles
        styles.add(ParagraphStyle(
            name='CompanyName',
            parent=styles['Heading1'],
            fontSize=14,
            alignment=0,
            spaceBefore=12,
            spaceAfter=12
        ))

        # Choose company details based on letterhead selection
        if quote.company_letterhead == 'CNL':
            company_details = [
                [Paragraph("<b>CNL Mining Supplies (Pty) Ltd</b>", styles['CompanyName'])],
                [Paragraph("47 Station Street", styles['Normal'])],
                [Paragraph("Carletonville, Gauteng 2499", styles['Normal'])],
                [Paragraph("+27 18 786 2897", styles['Normal'])],
                [Paragraph("laura@wfsales.co.za", styles['Normal'])],
                [Paragraph("VAT No: 4840229449", styles['Normal'])],
                [Paragraph("Business ID No: 2014/004024/07", styles['Normal'])]
            ]
            logo_path = os.path.join(settings.STATIC_ROOT, 'assets', 'images', 'cnl_logo.png')
            banking_details = [
                "Banking Details:",
                "Standard Bank - Carletonville",
                "Current Account",
                "Branch Code: 016141",
                "Account Number: 022196552"
            ]
        else:  # ISHERWOOD
            company_details = [
                [Paragraph("<b>ISHERWOOD ENGINEERING (PTY) LTD</b>", styles['CompanyName'])],
                [Paragraph("Registration No: 2014/004024/07", styles['Normal'])],
                [Paragraph("VAT No: 4840229449", styles['Normal'])],
                [Paragraph("Physical Address: 47 Station Street", styles['Normal'])],
                [Paragraph("Carletonville, Gauteng 2499", styles['Normal'])],
                [Paragraph("Contact: +27 18 786 2897", styles['Normal'])],
                [Paragraph("Email: laura@wfsales.co.za", styles['Normal'])]
            ]
            logo_path = os.path.join(settings.STATIC_ROOT, 'assets', 'images', 'isherwood_logo.png')
            banking_details = [
                "Banking Details:",
                "Standard Bank",
                "Current Account",
                "Branch Code: XXXXX",
                "Account Number: XXXXXXXXX"
            ]

        # Create header with logo
        header_data = [[
            Table(company_details, colWidths=[4*inch]),
            Image(logo_path, width=2*inch, height=1.25*inch)
        ]]

        # ... rest of your PDF generation code ...

        # Add banking details at the end
        elements.append(Spacer(1, 20))
        for detail in banking_details:
            elements.append(Paragraph(detail, styles['Normal']))

        # Build PDF
        doc.build(elements)
        
        # Save and return PDF
        buffer.seek(0)
        quote.pdf_file.save(
            f"Quote-{quote.quote_number}.pdf",
            ContentFile(buffer.getvalue())
        )

        return HttpResponse(
            buffer.getvalue(),
            content_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="Quote-{quote.quote_number}.pdf"'}
        )

    except Exception as e:
        messages.error(request, f'Error generating quote: {str(e)}')
        return redirect('quotes:quote_detail', pk=quote_id)

def create_order(request):
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('orders:order_list')
    else:
        form = OrderForm()
    return render(request, 'orders/create_order.html', {'form': form})







