from itertools import groupby
from operator import attrgetter
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count
from .models import Collection, CollectionProblem
from orders.models import OrderItem
from django.contrib.auth import get_user_model
import logging
import json
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta, datetime

logger = logging.getLogger(__name__)

User = get_user_model()

@login_required
def collection_pool(request):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    collections = Collection.objects.filter(
        status='pending'
    ).select_related(
        'order_item__order',
        'supplier'
    )

    # When collections are created in generate_purchase_order, 
    # they should already have the correct order_qty stored in their quantity field
    # but we can verify this here:
    for collection in collections:
        if collection.quantity is None:
            collection.quantity = collection.order_item.order_qty or collection.order_item.quantity
            collection.save()
        collection.is_future = (collection.planned_date is not None and 
                              collection.planned_date > tomorrow)
    
    # Group collections by supplier and include count
    grouped_collections = []
    for supplier, items in groupby(collections, key=attrgetter('supplier')):
        items_list = list(items)  # Convert iterator to list
        grouped_collections.append({
            'supplier': supplier,
            'items': items_list,
            'count': len(items_list)  # Add count of items
        })
    
    users = User.objects.filter(is_active=True).order_by('first_name')
    logger.info(f"Found {users.count()} active users")
    
    context = {
        'grouped_collections': grouped_collections,
        'users': users,
        'page_title': 'Collection Pool'
    }
    return render(request, 'driver_list/collection_pool.html', context)

@login_required 
def assign_driver(request, collection_id):
    logger.info(f"Assign driver request for collection {collection_id}")
    
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid method'})
    
    try:
        collection = get_object_or_404(Collection, id=collection_id)
        driver_id = request.POST.get('driver')
        planned_date = request.POST.get('planned_date')
        notes = request.POST.get('notes', '')
        
        logger.info(f"Received data - Driver: {driver_id}, Date: {planned_date}")
        
        if not driver_id or not planned_date:
            messages.error(request, 'Please select both a driver and date')
            return redirect('driver_list:collection_pool')
        
        try:
            planned_date = datetime.strptime(planned_date, '%Y-%m-%d').date()
            today = date.today()
            tomorrow = today + timedelta(days=1)

            collection.driver_id = driver_id
            collection.planned_date = planned_date
            collection.notes = notes
            collection.status = 'assigned'
            collection.save()

            return JsonResponse({
                'status': 'success',
                'message': 'Collection assigned successfully',
                'is_future': planned_date > tomorrow
            })

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            })
            
    except Exception as e:
        logger.error(f"Error assigning collection: {str(e)}")
        messages.error(request, f'Error assigning collection: {str(e)}')
        return redirect('driver_list:collection_pool')
    
    return redirect('driver_list:collection_pool')

@login_required
def assigned_collections(request):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    collections = Collection.objects.filter(
        status='assigned',
        planned_date__lte=tomorrow  # Only show today and tomorrow
    ).select_related(
        'order_item__order',
        'order_item__purchase_order',
        'supplier',
        'driver'
    ).order_by('supplier__suppliername')
    
    # Group collections by supplier
    grouped_collections = []
    for supplier, items in groupby(collections, key=attrgetter('supplier')):
        items_list = list(items)
        grouped_collections.append({
            'supplier': supplier,
            'items': items_list,
            'count': len(items_list)
        })
    
    context = {
        'grouped_collections': grouped_collections,
        'page_title': 'Assigned Collections'
    }
    return render(request, 'driver_list/assigned_collections.html', context)

@login_required
def update_collection_status(request, collection_id):
    if request.method == 'POST':
        try:
            collection = get_object_or_404(Collection, id=collection_id)
            status = request.POST.get('status')
            received_qty = request.POST.get('received_qty')
            notes = request.POST.get('notes', '')
            
            if status == 'collected':
                if not received_qty:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Please enter received quantity'
                    })
                
                received_qty = Decimal(received_qty)
                # Change this line to use collection.quantity instead of order_item.quantity
                expected_qty = collection.quantity  # This now uses the PO quantity
                
                # Handle partial collection
                if received_qty < expected_qty:
                    remaining_qty = expected_qty - received_qty
                    
                    # Update original order item with collected quantity
                    order_item = collection.order_item
                    order_item.order_qty = received_qty  # Update order_qty instead of quantity
                    order_item.save()
                    
                    # Create new order item for remaining quantity
                    new_order_item = collection.order_item
                    new_order_item.pk = None  # Create new instance
                    new_order_item.order_qty = remaining_qty  # Set order_qty instead of quantity
                    new_order_item.quantity = remaining_qty  # Also update quantity
                    new_order_item.cost_price = None
                    new_order_item.item_status = 'pending'
                    new_order_item.purchase_order = None
                    new_order_item.supplier = None
                    new_order_item.save()
                    
                    # Update the order status
                    order = new_order_item.order
                    order.status = 'processing'
                    order.save()
                    
                    logger.info(f"Order {order.order_number} split: {remaining_qty} units returned for reprocessing")
                else:
                    remaining_qty = Decimal('0')
                
                # Update current collection
                collection.received_qty = received_qty
                collection.status = 'collected'
                collection.driver = request.user
                collection.actual_date = timezone.now().date()
                collection.notes = notes if received_qty == expected_qty else f"Partial collection: {received_qty} of {expected_qty} units collected. {notes}"
                collection.save()
                
                return JsonResponse({
                    'status': 'success',
                    'message': 'Collection updated successfully' if received_qty == expected_qty else f'Collection updated successfully. {remaining_qty} units returned for reprocessing.',
                    'split_created': received_qty < expected_qty,
                    'remaining_qty': str(remaining_qty)
                })
                
            elif status == 'problem':
                if not notes:
                    return JsonResponse({
                        'status': 'error',
                        'message': 'Please describe the problem'
                    })
                
                collection.status = 'problem'
                collection.notes = notes
                collection.save()
                
                return JsonResponse({
                    'status': 'success',
                    'message': 'Problem reported successfully'
                })
                
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            })
    
    return JsonResponse({
        'status': 'error',
        'message': 'Invalid request'
    })

@login_required
def bulk_assign_driver(request):
    if request.method == 'POST':
        driver_id = request.POST.get('driver')
        planned_date = request.POST.get('planned_date')
        items = request.POST.getlist('items[]')
        
        if not all([driver_id, planned_date, items]):
            messages.error(request, 'Please select a driver, date, and at least one item')
            return redirect('driver_list:collection_pool')
        
        try:
            driver = User.objects.get(id=driver_id)
            planned_date = datetime.strptime(planned_date, '%Y-%m-%d').date()
            today = date.today()
            tomorrow = today + timedelta(days=1)
            
            collections = Collection.objects.filter(id__in=items)
            for collection in collections:
                collection.driver = driver
                collection.planned_date = planned_date
                # Only assign if date is today or tomorrow
                if planned_date <= tomorrow:
                    collection.status = 'assigned'
                else:
                    collection.status = 'pending'  # Keep as pending for future dates
                collection.save()
            
            if planned_date > tomorrow:
                messages.warning(request, f'Collections scheduled for future date ({planned_date})')
            else:
                messages.success(request, f'{len(items)} collections assigned to {driver.get_full_name()}')
            
        except Exception as e:
            logger.error(f"Error in bulk assign: {str(e)}")
            messages.error(request, f'Error assigning collections: {str(e)}')
            
    return redirect('driver_list:collection_pool')

@login_required
def completed_collections(request):
    collections = Collection.objects.filter(
        status='collected'
    ).select_related(
        'order_item__order',
        'order_item__purchase_order',
        'supplier',
        'driver'
    ).order_by('-actual_date', 'supplier__suppliername')
    
    # Group collections by supplier
    grouped_collections = []
    for supplier, items in groupby(collections, key=attrgetter('supplier')):
        items_list = list(items)
        grouped_collections.append({
            'supplier': supplier,
            'items': items_list,
            'count': len(items_list)
        })
    
    context = {
        'grouped_collections': grouped_collections,
        'page_title': 'Completed Collections'
    }
    return render(request, 'driver_list/completed_collections.html', context)

@login_required
def activate_collection(request, collection_id):
    if request.method == 'POST':
        collection = get_object_or_404(Collection, id=collection_id)
        collection.status = 'pending'
        collection.save()
        return JsonResponse({
            'status': 'success',
            'message': 'Collection activated successfully'
        })
    return JsonResponse({
        'status': 'error',
        'message': 'Invalid request method'
    })
