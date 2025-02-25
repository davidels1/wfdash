from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from django.utils import timezone
from django.template.loader import render_to_string
from decimal import Decimal, InvalidOperation

from django.db import models
from django.conf import settings

from .models import QuoteRequest, QuoteItem
from .forms import QuoteRequestForm, QuoteItemFormSet
from wfdash.models import Suppliers  # Add this import
from .utils import is_mobile


@login_required
def quote_list(request):
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    
    # Filter quotes by current user (rep)
    quotes = QuoteRequest.objects.filter(rep=request.user)
    
    if search_query:
        quotes = quotes.filter(
            Q(quote_number__icontains=search_query) |
            Q(customer__company__icontains=search_query)
        )
    
    quotes = quotes.order_by('-created_at')
    
    template = 'quotes/mobile/quote_list.html' if is_mobile(request) else 'quotes/quote_list.html'
    
    return render(request, template, {
        'quotes': quotes,
        'segment': 'quotes',
        'search_query': search_query,
        'status_filter': status_filter
    })

@login_required
def quote_create(request):
    if request.method == 'POST':
        form = QuoteRequestForm(request.POST)
        if form.is_valid():
            quote = form.save(commit=False)
            quote.rep = request.user
            quote.quote_number = f"Q{QuoteRequest.objects.count() + 1:06d}"
            quote.save()
            
            # Save items
            descriptions = request.POST.getlist('description[]')
            quantities = request.POST.getlist('quantity[]')
            notes = request.POST.getlist('notes[]')
            
            for i in range(len(descriptions)):
                if descriptions[i]:
                    QuoteItem.objects.create(
                        quote=quote,
                        description=descriptions[i],
                        quantity=quantities[i],
                        notes=notes[i]
                    )
            
            messages.success(request, 'Quote created successfully!')
            return redirect('quotes:quote_detail', pk=quote.pk)
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
        all_items_complete = True
        
        for item in quote.items.all():
            item_id = str(item.id)
            
            # Save text fields
            item.quote_number = request.POST.get(f'quote_number_{item_id}', '')
            item.quote_reference = request.POST.get(f'quote_reference_{item_id}', '')
            item.notes = request.POST.get(f'notes_{item_id}', '')
            
            # Save supplier
            supplier_id = request.POST.get(f'supplier_{item_id}')
            if supplier_id:
                item.supplier_id = supplier_id
            
            # Get float values
            try:
                item.cost_price = float(request.POST.get(f'cost_price_{item_id}', 0)) or None
                item.selling_price = float(request.POST.get(f'selling_price_{item_id}', 0)) or None
            except ValueError:
                item.cost_price = None
                item.selling_price = None
            
            # Calculate markup
            if item.cost_price and item.selling_price:
                item.markup = item.calculate_markup()
            
            # Check if item is complete
            item.is_complete = all([
                item.quote_number,
                item.quote_reference,
                item.supplier_id,
                item.cost_price,
                item.selling_price
            ])
            
            if not item.is_complete:
                all_items_complete = False
                
            item.save()
        
        # Update quote status if all items complete
        if all_items_complete:
            quote.status = 'complete'
            messages.success(request, 'Quote completed successfully!')
        else:
            quote.status = 'processed'
            messages.success(request, 'Items saved successfully')
        
        quote.save()
        return redirect('quotes:quote_detail', pk=quote.pk)

    return render(request, 'quotes/quote_process.html', {
        'quote': quote,
        'items': quote.items.all(),
        'suppliers': Suppliers.objects.all().order_by('suppliername')
    })

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