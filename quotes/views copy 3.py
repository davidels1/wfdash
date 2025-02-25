from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse  # Add HttpResponse here
from django.db.models import Q
from django.utils import timezone
from django.template.loader import render_to_string
from django.core.paginator import Paginator
from datetime import timedelta

from django.db import models
from django.conf import settings

from .models import QuoteRequest, QuoteItem
from .forms import QuoteRequestForm, QuoteItemFormSet
from wfdash.models import Suppliers  # Add this import

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image  # Add Image here
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from io import BytesIO
from django.core.files.base import ContentFile
import os
from decimal import Decimal, InvalidOperation


@login_required
def quote_list(request):
    """Display quotes based on user's group membership"""
    is_admin = request.user.is_superuser or request.user.groups.filter(name='ADMIN').exists()
    is_quoter = request.user.groups.filter(name='QUOTERS').exists()
    is_rep = request.user.groups.filter(name='REP').exists()
    is_buyer = request.user.groups.filter(name='BUYER').exists()

    if is_admin or is_quoter or is_buyer:
        quotes = QuoteRequest.objects.all()
    elif is_rep:
        quotes = QuoteRequest.objects.filter(rep=request.user)
    else:
        quotes = QuoteRequest.objects.none()

    context = {
        'quotes': quotes,
        'is_admin': is_admin,
        'is_quoter': is_quoter,
        'is_rep': is_rep,
        'is_buyer': is_buyer
    }
    return render(request, 'quotes/quote_list.html', context)

@login_required
def quote_create(request):
    if request.method == 'POST':
        form = QuoteRequestForm(request.POST)
        if form.is_valid():
            try:
                # Create quote
                quote = form.save(commit=False)
                quote.rep = request.user
                quote.status = 'new'
                
                # Generate quote number
                last_quote = QuoteRequest.objects.order_by('-id').first()
                next_number = 1 if not last_quote else int(last_quote.quote_number[1:]) + 1
                quote.quote_number = f"Q{next_number:06d}"
                
                quote.save()
                
                # Save items
                descriptions = request.POST.getlist('description[]')
                quantities = request.POST.getlist('quantity[]')
                notes = request.POST.getlist('notes[]')
                
                # Validate at least one item
                if not descriptions or not any(desc.strip() for desc in descriptions):
                    form.add_error(None, "At least one item is required")
                    raise ValueError("No items provided")
                
                # Create items
                for i in range(len(descriptions)):
                    if descriptions[i].strip():  # Only create if description is not empty
                        QuoteItem.objects.create(
                            quote=quote,
                            description=descriptions[i],
                            quantity=int(quantities[i] or 1),
                            notes=notes[i] if i < len(notes) else ''
                        )
                
                messages.success(request, 'Quote created successfully!')
                return redirect('quotes:quote_detail', pk=quote.pk)
                
            except Exception as e:
                messages.error(request, f'Error creating quote: {str(e)}')
                return render(request, 'quotes/quote_form.html', {'form': form})
    else:
        form = QuoteRequestForm()
    
    return render(request, 'quotes/quote_form.html', {'form': form})

@login_required
def quote_detail(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)
    
    if request.method == 'POST':
        if 'assign' in request.POST:
            quote.assigned_to = request.user
            quote.status = 'claimed'
            quote.save()
            messages.success(request, 'Quote assigned to you successfully!')
            return redirect('quotes:quote_process', pk=quote.pk)
        elif 'complete' in request.POST:
            if quote.can_complete():
                quote.status = 'complete'
                quote.save()
                messages.success(request, 'Quote marked as complete!')
            else:
                messages.error(request, 'Cannot complete quote - some items are missing information')
        elif 'problem' in request.POST:
            quote.has_problems = True
            quote.save()
            messages.warning(request, 'Quote marked as problematic!')
            
    items = quote.items.all()
    return render(request, 'quotes/quote_detail.html', {
        'quote': quote,
        'items': items,
        'segment': 'quotes'
    })

@login_required
def quote_edit(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)
    if quote.is_complete:
        messages.error(request, 'Cannot edit completed quotes!')
        return redirect('quotes:quote_detail', pk=quote.pk)
        
    if request.method == 'POST':
        form = QuoteRequestForm(request.POST, instance=quote)
        formset = QuoteItemFormSet(request.POST, instance=quote)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, 'Quote updated successfully!')
            return redirect('quotes:quote_detail', pk=quote.pk)
    else:
        form = QuoteRequestForm(instance=quote)
        formset = QuoteItemFormSet(instance=quote)
    
    return render(request, 'quotes/quote_form.html', {
        'form': form,
        'formset': formset,
        'quote': quote,
        'segment': 'quotes',
        'title': 'Edit Quote'
    })

@login_required
def quote_delete(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)
    if request.method == 'POST':
        quote.delete()
        messages.success(request, 'Quote deleted successfully!')
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'})

@login_required
def quote_claim(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)
    if request.method == 'POST':
        quote.assigned_to = request.user
        quote.status = 'claimed'
        quote.save()
        messages.success(request, f'Quote #{quote.quote_number} has been claimed')
        return redirect('quotes:quote_process', pk=quote.pk)
    return redirect('quotes:quote_list')

@login_required
def quote_process(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)
    
    if request.method == 'POST':
        # Process existing items
        for item in quote.items.all():
            item_id = str(item.id)
            
            # Process text fields
            item.quote_number = request.POST.get(f'quote_number_{item_id}', '')
            item.quote_reference = request.POST.get(f'quote_reference_{item_id}', '')
            item.description = request.POST.get(f'description_{item_id}', '')
            item.notes = request.POST.get(f'notes_{item_id}', '')
            item.quantity = request.POST.get(f'quantity_{item_id}', item.quantity)
            
            # Process decimal fields
            try:
                item.cost_price = float(request.POST.get(f'cost_price_{item_id}', 0))
                item.markup = float(request.POST.get(f'markup_{item_id}', 0))
                item.selling_price = float(request.POST.get(f'selling_price_{item_id}', 0))
            except ValueError:
                pass
            
            # Process supplier
            supplier_id = request.POST.get(f'supplier_{item_id}')
            if supplier_id:
                item.supplier_id = supplier_id
            
            item.save()
        
        quote.status = 'processed'
        quote.save()
        
        messages.success(request, 'Quote processed successfully!')
        return JsonResponse({'status': 'success'})
    
    context = {
        'quote': quote,
        'items': quote.items.all(),
        'segment': 'quotes'
    }
    
    return render(request, 'quotes/quote_process.html', context)

def get_decimal_or_none(field_name, request):
    """Helper function to convert form values to decimal or None"""
    value = request.POST.get(field_name, '').strip()
    try:
        return Decimal(value) if value else None
    except (ValueError, InvalidOperation):
        return None

@login_required
def add_quote_item(request):
    if request.method == 'POST':
        index = int(request.POST.get('index', 0))
        context = {'index': index}
        html = render_to_string('quotes/partials/quote_item_row.html', context)
        return JsonResponse({'html': html})

def clean_customer(self):
    customer = self.cleaned_data.get('customer')
    if not customer:
        raise forms.ValidationError("Customer is required")
    return customer

def get_total(self):
    if self.quantity and self.selling_price:
        return self.quantity * self.selling_price
    return 0

@login_required
def generate_quote_pdf(request, quote_id):
    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id)
        items = quote.items.all()

        # Create PDF buffer with A4 size
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,  # Reduced margins for better space usage
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )

        # Enhanced styles
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name='RightAlign',
            parent=styles['Normal'],
            alignment=2,
            spaceBefore=6,
            spaceAfter=6
        ))
        styles.add(ParagraphStyle(
            name='LeftAlign',
            parent=styles['Normal'],
            alignment=0,
            spaceBefore=6,
            spaceAfter=6
        ))
        styles.add(ParagraphStyle(
            name='CompanyName',
            parent=styles['Heading1'],
            fontSize=14,
            textColor=colors.HexColor('#000000'),  # Dark Olive Green
            alignment=0,  # Center alignment
            spaceBefore=12,
            spaceAfter=12
        ))

        # Add a new style for the grand total (add this where other styles are defined)
        styles.add(ParagraphStyle(
            name='GrandTotal',
            parent=styles['Normal'],
            fontSize=12,  # Bigger font size
            fontName='Helvetica-Bold',  # Bold font
            alignment=2,  # Right alignment
            spaceBefore=6,
            spaceAfter=6
        ))

        elements = []

        # Header with logo and company info side by side
        if quote.company_letterhead == 'CNL':
            company_details = [
                [Paragraph("<b>CNL Mining Supplies (Pty) Ltd</b>", styles['CompanyName'])],
                [Paragraph("47 Station Street", styles['LeftAlign'])],
                [Paragraph("Carletonville, Gauteng 2499", styles['LeftAlign'])],
              
                [Paragraph("+27 18 786 2897", styles['LeftAlign'])],
                [Paragraph("laura@wfsales.co.za", styles['LeftAlign'])],

                [Paragraph("VAT No: 4840229449", styles['LeftAlign'])],
                [Paragraph("Business ID No: 2014/004024/07", styles['LeftAlign'])]
                
            ]
        else:
            company_details = [
                [Paragraph("<b>ISHERWOOD ENGINEERING (PTY) LTD</b>", styles['CompanyName'])],
                [Paragraph("Registration No: xxx/xxxxxx/xx", styles['LeftAlign'])],
                [Paragraph("VAT No: xxxxxxxxxx", styles['LeftAlign'])],
                [Paragraph("Physical Address: xxx Street Name", styles['LeftAlign'])],
                [Paragraph("Contact: xxx-xxx-xxxx", styles['LeftAlign'])],
                [Paragraph("Email: sales@isherwood.com", styles['LeftAlign'])]
            ]

        # Create header table with company info left and logo right
        header_data = [[
            Table(company_details, colWidths=[4*inch]),
            Image(
                os.path.join(settings.STATIC_ROOT, 'assets', 'images',
                'cnl_logo.png' if quote.company_letterhead == 'CNL' else 'isherwood_logo.png'),
                width=2.5*inch,
                height=1.56*inch
            )
        ]]
        
        header_table = Table(header_data, colWidths=[6*inch, 2*inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 20))

        # Create a table for QUOTATION title with proper left alignment and bigger font
        quotation_style = ParagraphStyle(
            name='QuotationTitle',
            parent=styles['Normal'],
            fontSize=18,  # Increased font size
            fontName='Helvetica-Bold',
            alignment=0,  # Left alignment
            spaceBefore=2,
            spaceAfter=10
        )
        quotation_title = [[Paragraph("<b>QUOTATION</b>", quotation_style)]]
        quotation_table = Table(quotation_title, colWidths=[8*inch])
        quotation_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0)
        ]))
        elements.append(quotation_table)
        elements.append(Spacer(1, 10))

        # Customer info and Quote details side by side
        customer_info = [
            [Paragraph("<b>TO:</b>", styles['LeftAlign'])],
            [Paragraph(f"{quote.customer.company}", styles['LeftAlign'])],
            [Paragraph(f"{quote.customer.email if quote.customer.email else ''}", styles['LeftAlign'])],
            [Paragraph(f"{quote.customer.number if quote.customer.number else ''}", styles['LeftAlign'])]
        ]

        # Move quote details to right side under logo
        quote_info = [
            [Paragraph(f"<b>Quote No:</b> {quote.quote_number}", styles['RightAlign'])],
            [Paragraph(f"<b>Date:</b> {quote.created_at.strftime('%d %B %Y')}", styles['RightAlign'])],
            [Paragraph(f"<b>Reference:</b> {quote.quote_reference}", styles['RightAlign'])],
            [Paragraph(f"<b>Valid until:</b> {(quote.created_at + timezone.timedelta(days=30)).strftime('%d %B %Y')}", styles['RightAlign'])]
        ]

        info_data = [[
            Table(customer_info, colWidths=[4*inch]),
            Table(quote_info, colWidths=[4*inch])
        ]]
        info_table = Table(info_data, colWidths=[4*inch, 4*inch])
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 20))

        # Items table with improved styling
        table_data = [['Description', 'Qty', 'Unit Price', 'Total']]
        total = 0
        
        for item in items:
            amount = item.quantity * item.selling_price
            total += amount
            table_data.append([
                Paragraph(item.quote_reference, styles['LeftAlign']),
                str(item.quantity),
                f"R {item.selling_price:,.2f}",
                f"R {amount:,.2f}"
            ])

        # Add VAT and total with right alignment
        vat = total * Decimal('0.15')
        grand_total = total + vat
        
        # Then modify the table_data.extend section:
        table_data.extend([
            ['', '', Paragraph('<b>Subtotal:</b>', styles['RightAlign']), f"R {total:,.2f}"],
            ['', '', Paragraph('<b>VAT (15%):</b>', styles['RightAlign']), f"R {vat:,.2f}"],
            ['', '', Paragraph('<b>Total:</b>', styles['GrandTotal']), f"R {grand_total:,.2f}"]  # Using new style
        ])

        # Update the items table styling with olive green colors
        table = Table(table_data, colWidths=[4*inch, 1*inch, 1.5*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#B2BE80')),  # Light Olive Green
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#5B6711')),  # Dark Olive Green text
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -4), colors.white),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('ALIGN', (-2, -3), (-1, -1), 'RIGHT'),
            ('FONTNAME', (-2, -3), (-2, -1), 'Helvetica-Bold'),
            ('LINEBELOW', (0, 0), (-1, -4), 0.25, colors.black),
            ('LINEABOVE', (-2, -3), (-1, -3), 1, colors.black),
            ('LINEABOVE', (-2, -1), (-1, -1), 2, colors.black),
            ('FONTSIZE', (-1, -1), (-1, -1), 12),  # Bigger font for grand total amount
            ('FONTNAME', (-1, -1), (-1, -1), 'Helvetica-Bold'),  # Bold font for grand total amount
        ]))
        elements.append(table)

        # Terms and conditions with better formatting
        elements.append(Spacer(1, 30))
        elements.append(Paragraph("<b>Terms and Conditions:</b>", styles['Heading4']))
        terms = [
            "1. This quotation is valid for 30 days from the date of issue.",
            "2. Prices are quoted excluding VAT unless otherwise stated.",
            "3. Lead time will be confirmed upon receipt of order.",
        ]
        for term in terms:
            elements.append(Paragraph(term, styles['LeftAlign']))

        elements.append(Spacer(1, 30))

        # Add banking details style
        banking_style = ParagraphStyle(
            name='Banking',
            parent=styles['Normal'],
            fontSize=10,
            alignment=0,  # Left alignment
            spaceBefore=6,
            spaceAfter=6
        )

        # Banking details section
        if quote.company_letterhead == 'CNL':
            elements.append(Paragraph("<b>Banking Details:</b>", banking_style))
            banking_info = [
                "Standard Bank - Carletonville",
                "Current Account",
                "Branch Code: 016141",
                "Account Number: 022196552"
            ]
            
            for info in banking_info:
                elements.append(Paragraph(info, banking_style))

        elements.append(Spacer(1, 20))

        # Only one build call at the end
        doc.build(elements)
        
        # Save and return PDF
        buffer.seek(0)
        quote.pdf_file.save(
            f"Quote-{quote.quote_number}.pdf",
            ContentFile(buffer.getvalue())
        )

        # Update the generated timestamp
        quote.pdf_generated_at = timezone.now()
        quote.save()

        return HttpResponse(
            buffer.getvalue(),
            content_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="Quote-{quote.quote_number}.pdf"'}
        )
        
    except Exception as e:
        messages.error(request, f'Error generating quote: {str(e)}')
        return redirect('quotes:quote_detail', pk=quote_id)

@login_required
def generated_quotes(request):
    quotes_list = QuoteRequest.objects.filter(pdf_file__isnull=False).order_by('-pdf_generated_at')
    
    # Search functionality
    search_query = request.GET.get('search')
    if search_query:
        quotes_list = quotes_list.filter(
            Q(quote_number__icontains=search_query) |
            Q(customer__company__icontains=search_query) |
            Q(quote_reference__icontains=search_query)
        )
    
    # Company filter
    company = request.GET.get('company')
    if company:
        quotes_list = quotes_list.filter(company_letterhead=company)
    
    # Date range filter
    date_range = request.GET.get('date_range')
    if date_range:
        today = timezone.now().date()
        if date_range == 'today':
            quotes_list = quotes_list.filter(pdf_generated_at__date=today)
        elif date_range == 'week':
            week_ago = today - timedelta(days=7)
            quotes_list = quotes_list.filter(pdf_generated_at__date__gte=week_ago)
        elif date_range == 'month':
            month_ago = today - timedelta(days=30)
            quotes_list = quotes_list.filter(pdf_generated_at__date__gte=month_ago)
    
    # Pagination
    paginator = Paginator(quotes_list, 10)  # Show 10 quotes per page
    page = request.GET.get('page')
    quotes = paginator.get_page(page)
    
    context = {
        'quotes': quotes,
        'segment': 'generated_quotes',
        'title': 'Generated Quotes'
    }
    return render(request, 'quotes/generated_quotes.html', context)