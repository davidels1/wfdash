from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import timedelta
from quotes.models import QuoteRequest
from orders.models import Order
from wfdash.models import Customers
from driver_list.models import Collection

@login_required
def index(request):
    # Get today's date
    today = timezone.now().date()
    month_start = today.replace(day=1)
    
    # Get counts
    total_drivers = Collection.objects.count()
    active_drivers = Collection.objects.filter(status='active').count()
    
    # Calculate percentage (avoid division by zero)
    driver_percentage = (active_drivers / total_drivers * 100) if total_drivers > 0 else 0
    
    context = {
        'page_title': 'Dashboard',
        'total_quotes': QuoteRequest.objects.count(),
        'total_orders': Order.objects.count(),
        'total_collections': Collection.objects.count(),
        'total_customers': Customers.objects.count(),
        
        # Driver statistics
        'total_drivers': total_drivers,
        'active_drivers': active_drivers,
        'driver_percentage': driver_percentage,
        
        # Collection statistics
        'pending_collections': Collection.objects.filter(status='pending').count(),
        'assigned_collections': Collection.objects.filter(status='assigned').count(),
        'completed_collections': Collection.objects.filter(status='completed').count(),
        
        # Recent items
        'recent_quotes': QuoteRequest.objects.order_by('-created_at')[:5],
        'recent_orders': Order.objects.order_by('-created_at')[:5],
        'recent_collections': Collection.objects.order_by('-created_at')[:5],
        
        'segment': 'dashboard'
    }
    
    return render(request, 'dashboard/index.html', context)
