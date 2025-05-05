from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse
from datetime import datetime, timedelta  # Import timedelta separately

from .models import Repair, RepairPhoto, RepairQuote, RepairOrder
from .forms import RepairForm, RepairPhotoForm, RepairQuoteForm, RepairOrderForm, RepairStatusForm

@login_required(login_url='/accounts/login-v1/')
def repair_list(request):
    repairs = Repair.objects.all()
    
    # Filter by status if provided
    status = request.GET.get('status')
    if status:
        repairs = repairs.filter(status=status)
    
    # Filter by customer if provided
    customer = request.GET.get('customer')
    if customer:
        repairs = repairs.filter(customer_id=customer)
    
    context = {
        'segment': 'repairs',
        'parent': 'repairs',
        'repairs': repairs,
        'status_choices': Repair.STATUS_CHOICES
    }
    return render(request, 'repairs/repair_list.html', context)

@login_required(login_url='/accounts/login-v1/')
def repair_dashboard(request):
    # Get counts for each status
    status_counts = Repair.objects.values('status').annotate(count=Count('id'))
    
    # Get repairs that need attention (no updates in past 7 days)
    seven_days_ago = datetime.now().date() - timedelta(days=7)  # Fixed this line
    need_attention = Repair.objects.filter(
        ~Q(status__in=['returned', 'cancelled']),
        updated_at__lt=seven_days_ago
    )
    
    # Get recent quotes waiting for approval
    pending_quotes = Repair.objects.filter(status='quote_sent')
    
    # Get repairs in progress
    in_progress = Repair.objects.filter(status='repair_in_progress')
    
    context = {
        'segment': 'repairs_dashboard',
        'parent': 'repairs',
        'status_counts': status_counts,
        'need_attention': need_attention,
        'pending_quotes': pending_quotes,
        'in_progress': in_progress
    }
    return render(request, 'repairs/dashboard.html', context)

@login_required(login_url='/accounts/login-v1/')
def repair_detail(request, repair_id):
    repair = get_object_or_404(Repair, pk=repair_id)
    photos = repair.photos.all()
    quotes = repair.quotes.all()
    orders = repair.orders.all()
    
    context = {
        'segment': 'repairs',
        'parent': 'repairs',
        'repair': repair,
        'photos': photos,
        'quotes': quotes,
        'orders': orders,
        'status_form': RepairStatusForm(instance=repair)
    }
    return render(request, 'repairs/repair_detail.html', context)

@login_required(login_url='/accounts/login-v1/')
def repair_create(request):
    if request.method == 'POST':
        form = RepairForm(request.POST)
        if form.is_valid():
            repair = form.save(commit=False)
            repair.created_by = request.user
            repair.save()
            messages.success(request, 'Repair record created successfully.')
            return redirect('repairs:repair_detail', repair_id=repair.id)
    else:
        form = RepairForm()
    
    context = {
        'segment': 'repairs',
        'parent': 'repairs',
        'form': form,
        'title': 'Create New Repair'
    }
    return render(request, 'repairs/repair_form.html', context)

@login_required(login_url='/accounts/login-v1/')
def repair_update(request, repair_id):
    repair = get_object_or_404(Repair, pk=repair_id)
    
    if request.method == 'POST':
        form = RepairForm(request.POST, instance=repair)
        if form.is_valid():
            form.save()
            messages.success(request, 'Repair record updated successfully.')
            return redirect('repairs:repair_detail', repair_id=repair.id)
    else:
        form = RepairForm(instance=repair)
    
    context = {
        'segment': 'repairs',
        'parent': 'repairs',
        'form': form,
        'repair': repair,
        'title': 'Update Repair'
    }
    return render(request, 'repairs/repair_form.html', context)

@login_required(login_url='/accounts/login-v1/')
def repair_delete(request, repair_id):
    repair = get_object_or_404(Repair, pk=repair_id)
    
    if request.method == 'POST':
        repair.delete()
        messages.success(request, 'Repair record deleted successfully.')
        return redirect('repairs:repair_list')
    
    context = {
        'segment': 'repairs',
        'parent': 'repairs',
        'repair': repair
    }
    return render(request, 'repairs/repair_confirm_delete.html', context)

@login_required(login_url='/accounts/login-v1/')
def upload_photo(request, repair_id):
    repair = get_object_or_404(Repair, pk=repair_id)
    
    if request.method == 'POST':
        form = RepairPhotoForm(request.POST, request.FILES)
        if form.is_valid():
            photo = form.save(commit=False)
            photo.repair = repair
            photo.save()
            messages.success(request, 'Photo uploaded successfully.')
            return redirect('repairs:repair_detail', repair_id=repair.id)
    else:
        form = RepairPhotoForm()
    
    context = {
        'segment': 'repairs',
        'parent': 'repairs',
        'form': form,
        'repair': repair
    }
    return render(request, 'repairs/upload_photo.html', context)

@login_required(login_url='/accounts/login-v1/')
def create_quote(request, repair_id):
    repair = get_object_or_404(Repair, pk=repair_id)
    
    if request.method == 'POST':
        form = RepairQuoteForm(request.POST, request.FILES)
        if form.is_valid():
            quote = form.save(commit=False)
            quote.repair = repair
            quote.save()
            
            # Update repair status
            repair.status = 'quote_received'
            repair.quote_received_date = datetime.now().date()
            repair.save()
            
            messages.success(request, 'Quote created successfully.')
            return redirect('repairs:repair_detail', repair_id=repair.id)
    else:
        form = RepairQuoteForm()
    
    context = {
        'segment': 'repairs',
        'parent': 'repairs',
        'form': form,
        'repair': repair
    }
    return render(request, 'repairs/create_quote.html', context)

@login_required(login_url='/accounts/login-v1/')
def approve_quote(request, repair_id, quote_id):
    repair = get_object_or_404(Repair, pk=repair_id)
    quote = get_object_or_404(RepairQuote, pk=quote_id, repair=repair)
    
    quote.approved = True
    quote.approved_date = datetime.now().date()
    quote.save()
    
    # Update repair status
    repair.status = 'quote_approved'
    repair.quote_approved_date = datetime.now().date()
    repair.save()
    
    messages.success(request, 'Quote approved successfully.')
    return redirect('repairs:repair_detail', repair_id=repair.id)

@login_required(login_url='/accounts/login-v1/')
def create_order(request, repair_id):
    repair = get_object_or_404(Repair, pk=repair_id)
    
    if request.method == 'POST':
        form = RepairOrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.repair = repair
            order.save()
            
            # Update repair status
            repair.status = 'repair_ordered'
            repair.repair_ordered_date = datetime.now().date()
            repair.save()
            
            messages.success(request, 'Repair order created successfully.')
            return redirect('repairs:repair_detail', repair_id=repair.id)
    else:
        # Pre-fill supplier from repair if available
        initial_data = {}
        if repair.supplier:
            initial_data['supplier'] = repair.supplier
        
        # Get amount from approved quote if available
        approved_quote = repair.quotes.filter(approved=True).first()
        if approved_quote:
            initial_data['amount'] = approved_quote.supplier_quote_amount
            
        form = RepairOrderForm(initial=initial_data)
    
    context = {
        'segment': 'repairs',
        'parent': 'repairs',
        'form': form,
        'repair': repair
    }
    return render(request, 'repairs/create_order.html', context)

@login_required(login_url='/accounts/login-v1/')
def update_status(request, repair_id):
    repair = get_object_or_404(Repair, pk=repair_id)
    
    if request.method == 'POST':
        form = RepairStatusForm(request.POST, instance=repair)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            repair.status = new_status
            
            # Set date fields based on status
            if new_status == 'sent_for_quote' and not repair.sent_for_quote_date:
                repair.sent_for_quote_date = datetime.now().date()
            elif new_status == 'quote_received' and not repair.quote_received_date:
                repair.quote_received_date = datetime.now().date()
            elif new_status == 'quote_sent' and not repair.quote_sent_date:
                repair.quote_sent_date = datetime.now().date()
            elif new_status == 'quote_approved' and not repair.quote_approved_date:
                repair.quote_approved_date = datetime.now().date()
            elif new_status == 'repair_ordered' and not repair.repair_ordered_date:
                repair.repair_ordered_date = datetime.now().date()
            elif new_status == 'repaired' and not repair.completed_date:
                repair.completed_date = datetime.now().date()
            elif new_status == 'returned' and not repair.returned_date:
                repair.returned_date = datetime.now().date()
                
            repair.save()
            messages.success(request, f'Status updated to {repair.get_status_display()}')
            
    return redirect('repairs:repair_detail', repair_id=repair.id)
