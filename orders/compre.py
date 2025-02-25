from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages 
from django.db.models import Q
from .models import Order, OrderItem, PurchaseOrder
from wfdash.models import Customers, Suppliers, CompanyDetails
from .utils import is_mobile
from django.http import JsonResponse, HttpResponse
from .forms import OrderForm, OrderItemFormSet
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Image, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from decimal import Decimal
from io import BytesIO
from django.utils import timezone
from django.core.files.base import ContentFile

@login_required
def order_list(request):
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    
    orders = Order.objects.filter(rep=request.user)
    
    if search_query:
        orders = orders.filter(
            Q(order_number__icontains=search_query) |
            Q(customer__company__icontains=search_query)
        )
    
    if status_filter:
        orders = orders.filter(status=status_filter)
        
    orders = orders.order_by('-created_at')
    template = 'orders/mobile/order_list.html' if is_mobile(request) else 'orders/order_list.html'
    
    return render(request, template, {
        'orders': orders,
        'search_query': search_query,
        'status_filter': status_filter,
        'status_choices': Order.STATUS_CHOICES
    })

@login_required
def order_create(request):
    template = 'orders/mobile/order_form.html' if is_mobile(request) else 'orders/order_form.html'
    
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.rep = request.user
            order.save()
            
            descriptions = request.POST.getlist('description[]')
            quantities = request.POST.getlist('quantity[]')
            selling_prices = request.POST.getlist('selling_price[]')
            
            try:
                for description, quantity, price in zip(descriptions, quantities, selling_prices):
                    if description and quantity and price:
                        OrderItem.objects.create(
                            order=order,
                            description=description,
                            quantity=int(quantity),
                            selling_price=float(price)
                        )
                messages.success(request, 'Order created successfully')
                return redirect('orders:order_detail', pk=order.pk)
            except Exception as e:
                order.delete()
                messages.error(request, f"Error creating items: {str(e)}")
    else:
        form = OrderForm()
    
    return render(request, template, {
        'form': form,
        'customers': Customers.objects.all().order_by('company')
    })

@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    items = OrderItem.objects.filter(order=order).select_related('supplier')
    
    template = 'orders/mobile/order_detail.html' if is_mobile(request) else 'orders/order_detail.html'
    
    return render(request, template, {
        'order': order,
        'items': items
    })

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
    suppliers_items = {}
    
    # Group items by supplier
    for item in items:
        if item.supplier:
            if item.supplier not in suppliers_items:
                suppliers_items[item.supplier] = []
            suppliers_items[item.supplier].append(item)
    
    context = {
        'order': order,
        'items': items,
        'suppliers': Suppliers.objects.all(),
        'suppliers_items': suppliers_items,
        'has_items_with_suppliers': any(item.supplier for item in items)
    }
    
    return render(request, 'orders/order_process.html', context)

@login_required
def generate_purchase_order(request, order_id, supplier_id):
    try:
        order = get_object_or_404(Order, id=order_id)
        supplier = get_object_or_404(Suppliers, id=supplier_id)
        company = CompanyDetails.objects.first()
        
        items = OrderItem.objects.filter(
            order=order,
            supplier_id=supplier_id
        )
        
        if not items.exists():
            messages.error(request, 'No items found for this supplier')
            return redirect('orders:order_detail', pk=order_id)

        po = PurchaseOrder.objects.create(
            order=order,
            supplier=supplier,
            status='draft'
        )

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=50)
        elements = []
        styles = getSampleStyleSheet()

        # Header with Logo and Company Info
        if company and company.logo:
            img = Image(company.logo.path)
            img.drawHeight = 1.5*inch
            img.drawWidth = 1.5*inch
            elements.append(img)
        
        elements.append(Spacer(1, 20))
        
        # Company Details
        if company:
            elements.append(Paragraph(company.name, styles['Heading1']))
            elements.append(Paragraph(company.address, styles['Normal']))
            elements.append(Paragraph(f"Tel: {company.phone}", styles['Normal']))
            elements.append(Paragraph(f"VAT: {company.vat_number}", styles['Normal']))
        
        elements.append(Spacer(1, 30))
        
        # PO Details
        elements.append(Paragraph(f"Purchase Order: {po.po_number}", styles['Heading2']))
        elements.append(Paragraph(f"Date: {timezone.now().strftime('%Y-%m-%d')}", styles['Normal']))
        
        elements.append(Spacer(1, 20))
        
        # Supplier Info
        elements.append(Paragraph("Supplier Details:", styles['Heading3']))
        elements.append(Paragraph(supplier.suppliername, styles['Normal']))
        elements.append(Paragraph(supplier.supplieraddress, styles['Normal']))
        elements.append(Paragraph(f"Tel: {supplier.suppliernumber}", styles['Normal']))
        
        elements.append(Spacer(1, 30))
        
        # Items Table
        data = [['Description', 'Quantity', 'Unit Price', 'Total']]
        total = Decimal('0')
        
        for item in items:
            amount = item.quantity * item.cost_price
            total += amount
            data.append([
                item.description,
                str(item.quantity),
                f"R {item.cost_price:.2f}",
                f"R {amount:.2f}"
            ])
        
        # Add total row
        data.append(['', '', 'Total:', f"R {total:.2f}"])
        
        table = Table(data, colWidths=[250, 70, 100, 100])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#333333')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.whitesmoke),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ]))
        
        elements.append(table)
        
        # Footer
        elements.append(Spacer(1, 40))
        elements.append(Paragraph("Terms and Conditions:", styles['Heading4']))
        elements.append(Paragraph("1. Please quote PO number on invoice", styles['Normal']))
        elements.append(Paragraph("2. Goods to be delivered to specified address", styles['Normal']))
        
        doc.build(elements)
        buffer.seek(0)
        
        po.pdf_file.save(
            f"{po.po_number}.pdf",
            ContentFile(buffer.getvalue())
        )

        items.update(purchase_order=po)
        po.total_amount = total
        po.save()

        return HttpResponse(
            buffer.getvalue(),
            content_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="{po.po_number}.pdf"'}
        )
        
    except Exception as e:
        print(f"Error generating PO: {str(e)}")
        messages.error(request, f'Error generating PO: {str(e)}')
        return redirect('orders:order_detail', pk=order_id)

@login_required
def save_order_item(request, item_id):
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        item = get_object_or_404(OrderItem, id=item_id)
        
        cost_price = data.get('cost_price')
        supplier_id = data.get('supplier_id')
        
        if cost_price and supplier_id:
            item.cost_price = Decimal(cost_price)
            item.supplier_id = supplier_id
            
            # Calculate markup
            if item.selling_price:
                item.markup = ((item.selling_price - item.cost_price) / item.cost_price) * 100
            
            item.save()
            
            return JsonResponse({
                'status': 'success',
                'markup': f"{item.markup:.2f}"
            })
            
    return JsonResponse({'status': 'error'}, status=400)

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
        if not po.pdf_file:
            raise ValueError("PDF file not found")

        response = HttpResponse(po.pdf_file.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{po.pdf_file.name}"'
        return response
    except Exception as e:
        messages.error(request, f'Error downloading PO: {str(e)}')
        return redirect('orders:po_list')