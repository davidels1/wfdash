from itertools import groupby
from operator import attrgetter
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count, Q
from .models import Collection, CollectionProblem
from stock_management.models import StockItem  # Import StockItem from the correct app
from orders.models import OrderItem
from driver_list.models import DriverListPool, Collection
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
        Q(status="pending") | Q(status="problem")
    ).select_related("order_item__order", "supplier")

    # When collections are created in generate_purchase_order,
    # they should already have the correct order_qty stored in their quantity field
    # but we can verify this here:
    for collection in collections:
        if collection.quantity is None:
            collection.quantity = (
                collection.order_item.order_qty or collection.order_item.quantity
            )
            collection.save()
        collection.is_future = (
            collection.planned_date is not None and collection.planned_date > tomorrow
        )

    # Group collections by supplier and include count
    grouped_collections = []
    for supplier, items in groupby(collections, key=attrgetter("supplier")):
        items_list = list(items)  # Convert iterator to list
        grouped_collections.append(
            {
                "supplier": supplier,
                "items": items_list,
                "count": len(items_list),  # Add count of items
            }
        )

    users = User.objects.filter(is_active=True).order_by("first_name")
    logger.info(f"Found {users.count()} active users")

    # Find Joachim in the users
    default_driver = None
    for user in users:
        if (
            "joachim" in user.get_full_name().lower()
            or "joachim" in user.username.lower()
        ):
            default_driver = user.id
            break

    context = {
        "grouped_collections": grouped_collections,
        "users": users,
        "page_title": "Collection Pool",
        "default_driver": default_driver,
    }
    return render(request, "driver_list/collection_pool.html", context)


@login_required
def assign_driver(request, collection_id):
    logger.info(f"Assign driver request for collection {collection_id}")

    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Invalid method"})

    try:
        collection = get_object_or_404(Collection, id=collection_id)
        driver_id = request.POST.get("driver")
        planned_date = request.POST.get("planned_date")
        notes = request.POST.get("notes", "")

        logger.info(f"Received data - Driver: {driver_id}, Date: {planned_date}")

        if not driver_id or not planned_date:
            messages.error(request, "Please select both a driver and date")
            return redirect("driver_list:collection_pool")

        try:
            planned_date = datetime.strptime(planned_date, "%Y-%m-%d").date()
            today = date.today()
            tomorrow = today + timedelta(days=1)

            collection.driver_id = driver_id
            collection.planned_date = planned_date
            collection.notes = notes
            collection.status = "assigned"
            collection.save()

            return JsonResponse(
                {
                    "status": "success",
                    "message": "Collection assigned successfully",
                    "is_future": planned_date > tomorrow,
                }
            )

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})

    except Exception as e:
        logger.error(f"Error assigning collection: {str(e)}")
        messages.error(request, f"Error assigning collection: {str(e)}")
        return redirect("driver_list:collection_pool")

    return redirect("driver_list:collection_pool")


@login_required
def assigned_collections(request):
    today = date.today()
    tomorrow = today + timedelta(days=1)

    # Base query for assigned collections with proper related objects
    collections_query = Collection.objects.filter(
        status="assigned", planned_date__lte=tomorrow  # Only show today and tomorrow
    ).select_related(
        "order_item__order",
        "order_item__purchase_order",
        "stock_order",
        "stock_item",
        "supplier",
        "driver",
    )

    # Check for specific roles - be more explicit
    is_admin = request.user.is_superuser
    is_staff = request.user.is_staff
    is_buyer = request.user.groups.filter(
        name__in=["Buyers", "Buyer", "Purchasing"]
    ).exists()
    is_driver = request.user.groups.filter(name="Driver").exists()

    # Drivers ONLY see their own collections
    if is_driver and not (is_admin or is_staff or is_buyer):
        collections_query = collections_query.filter(driver=request.user)
        page_title = f"Your Assigned Collections"
        is_admin_view = False
    else:
        page_title = "All Assigned Collections"
        is_admin_view = True

    # Special case for Joachim - hardcoded fix
    if (
        request.user.username == "joachim"
        or "joachim" in request.user.get_full_name().lower()
    ):
        collections_query = collections_query.filter(driver=request.user)
        page_title = f"Your Assigned Collections"
        is_admin_view = False

    # Order the results
    collections = collections_query.order_by("supplier__suppliername")

    # Group collections by supplier
    grouped_collections = []
    for supplier, items in groupby(collections, key=attrgetter("supplier")):
        items_list = list(items)
        grouped_collections.append(
            {"supplier": supplier, "items": items_list, "count": len(items_list)}
        )

    context = {
        "grouped_collections": grouped_collections,
        "page_title": page_title,
        "is_admin_view": is_admin_view,
        "user_role": (
            "Driver"
            if is_driver
            else "Admin/Buyer" if (is_admin or is_staff or is_buyer) else "Unknown"
        ),
    }
    return render(request, "driver_list/assigned_collections.html", context)


@login_required
def update_collection_status(request, collection_id):
    if request.method == "POST":
        try:
            collection = get_object_or_404(Collection, id=collection_id)
            status = request.POST.get("status")

            # Basic validation - status is required
            if not status:
                return JsonResponse({"status": "error", "message": "Invalid request"})

            if status == "collected":
                # Get received quantity - required for collected status
                received_qty = request.POST.get("received_qty")
                if not received_qty:
                    return JsonResponse(
                        {"status": "error", "message": "Please enter received quantity"}
                    )

                # Convert to Decimal and validate
                try:
                    received_qty = Decimal(received_qty)
                    expected_qty = collection.quantity
                except (InvalidOperation, TypeError):
                    return JsonResponse(
                        {"status": "error", "message": "Invalid quantity format"}
                    )

                # Update collection status
                collection.received_qty = received_qty
                collection.status = "collected"
                collection.driver = request.user
                collection.actual_date = timezone.now().date()

                # Add notes about partial collection if applicable
                notes = request.POST.get("notes", "")
                if received_qty != expected_qty:
                    notes = f"Partial collection: {received_qty} of {expected_qty} units collected. {notes}"
                collection.notes = notes
                collection.save()

                # Check if this is a stock order collection
                if collection.stock_order_id or collection.stock_item_id:
                    # If it's a stock order collection, move directly to stock
                    if collection.stock_order:
                        collection.stock_order.move_to_stock()

                    return JsonResponse(
                        {
                            "status": "success",
                            "message": "Stock order collected and moved directly to inventory",
                        }
                    )
                else:
                    # It's a regular collection, handle normally
                    return JsonResponse(
                        {
                            "status": "success",
                            "message": "Collection updated successfully",
                        }
                    )

            elif status == "problem":
                # Handle "problem" status
                problem_type = request.POST.get("problem_type")
                problem_description = request.POST.get("problem_description", "")

                if not problem_type:
                    return JsonResponse(
                        {"status": "error", "message": "Please select a problem type"}
                    )

                collection.status = "problem"
                collection.notes = problem_description
                collection.save()

                # Create a problem record
                CollectionProblem.objects.create(
                    collection=collection,
                    problem_type=problem_type,
                    description=problem_description,
                )

                return JsonResponse(
                    {"status": "success", "message": "Problem reported successfully"}
                )

            else:
                return JsonResponse(
                    {"status": "error", "message": f"Unsupported status: {status}"}
                )

        except Exception as e:
            logger.error(f"Error updating collection {collection_id}: {str(e)}")
            return JsonResponse({"status": "error", "message": str(e)})

    return JsonResponse({"status": "error", "message": "Invalid request method"})


@login_required
def bulk_assign_driver(request):
    if request.method == "POST":
        driver_id = request.POST.get("driver")
        planned_date = request.POST.get("planned_date")
        items = request.POST.getlist("items[]")

        if not all([driver_id, planned_date]):
            messages.error(request, "Please select a driver and date")
            return redirect("driver_list:collection_pool")

        if not items:
            messages.warning(request, "No items selected for assignment")
            return redirect("driver_list:collection_pool")

        try:
            driver = User.objects.get(id=driver_id)
            planned_date = datetime.strptime(planned_date, "%Y-%m-%d").date()
            today = date.today()
            tomorrow = today + timedelta(days=1)

            collections = Collection.objects.filter(id__in=items)
            for collection in collections:
                collection.driver = driver
                collection.planned_date = planned_date
                # Only assign if date is today or tomorrow
                if planned_date <= tomorrow:
                    collection.status = "assigned"
                else:
                    collection.status = "pending"  # Keep as pending for future dates
                collection.save()

            if planned_date > tomorrow:
                messages.warning(
                    request, f"Collections scheduled for future date ({planned_date})"
                )
            else:
                messages.success(
                    request,
                    f"{len(items)} collections assigned to {driver.get_full_name()}",
                )

        except Exception as e:
            logger.error(f"Error in bulk assign: {str(e)}")
            messages.error(request, f"Error assigning collections: {str(e)}")

    return redirect("driver_list:collection_pool")


@login_required
def completed_collections(request):
    # Get filter parameters
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    search_query = request.GET.get("search", "").strip().lower()

    # Default to today if no date filter
    today = date.today()
    start_date = today
    end_date = today

    # Parse date filters if provided
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            start_date = today

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            end_date = today

    # Build the base queryset
    collections = Collection.objects.filter(status="collected").select_related(
        "order_item__order", "order_item__purchase_order", "supplier", "driver"
    )

    # Apply date filter
    collections = collections.filter(
        actual_date__gte=start_date, actual_date__lte=end_date
    )

    # Apply search filter if provided
    if search_query:
        collections = collections.filter(
            Q(order_item__description__icontains=search_query)
            | Q(order_item__order__order_number__icontains=search_query)
            | Q(order_item__purchase_order__po_number__icontains=search_query)
            | Q(supplier__suppliername__icontains=search_query)
            | Q(notes__icontains=search_query)
        )

    # Order by date (newest first) then supplier
    collections = collections.order_by("-actual_date", "supplier__suppliername")

    # Group collections by supplier
    grouped_collections = []
    for supplier, items in groupby(collections, key=attrgetter("supplier")):
        items_list = list(items)
        grouped_collections.append(
            {"supplier": supplier, "items": items_list, "count": len(items_list)}
        )

    context = {
        "grouped_collections": grouped_collections,
        "page_title": "Completed Collections",
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "search_query": search_query,
    }
    return render(request, "driver_list/completed_collections.html", context)


@login_required
def activate_collection(request, collection_id):
    if request.method == "POST":
        collection = get_object_or_404(Collection, id=collection_id)
        collection.status = "pending"
        collection.save()
        return JsonResponse(
            {"status": "success", "message": "Collection activated successfully"}
        )
    return JsonResponse({"status": "error", "message": "Invalid request method"})


from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from decimal import Decimal
import logging

from wfdash.models import Suppliers  # Import Suppliers from wfdash app
from .models import Collection

logger = logging.getLogger(__name__)


@login_required
def add_manual_collection(request):
    if request.method == "POST":
        try:
            supplier_id = request.POST.get("supplier")
            driver_id = request.POST.get("driver")
            description = request.POST.get("description")
            quantity = request.POST.get("quantity")
            unit = request.POST.get("unit", "units")
            planned_date = request.POST.get("planned_date")
            notes = request.POST.get("notes", "")

            # Validation
            if not all([supplier_id, description, quantity]):
                return JsonResponse(
                    {"status": "error", "message": "Please fill all required fields"}
                )

            # Create the collection
            collection = Collection.objects.create(
                supplier_id=supplier_id,
                driver_id=driver_id if driver_id else None,
                description=description,
                quantity=Decimal(quantity),
                unit=unit,
                planned_date=planned_date if planned_date else None,
                notes=notes,
                is_manual=True,
                status="assigned" if driver_id else "pending",
            )

            return JsonResponse(
                {
                    "status": "success",
                    "message": "Manual collection added successfully",
                    "collection_id": collection.id,
                }
            )

        except Exception as e:
            logger.error(f"Error adding manual collection: {str(e)}")
            return JsonResponse({"status": "error", "message": str(e)})

    # GET request - render form
    suppliers = Suppliers.objects.all().order_by("suppliername")
    users = User.objects.filter(is_active=True).order_by("first_name")

    # Find Joachim for default selection
    default_driver_id = None
    joachim_found = False
    for user in users:
        if (
            "joachim" in user.get_full_name().lower()
            or "joachim" in user.username.lower()
        ):
            default_driver_id = user.id
            joachim_found = True
            break

    context = {
        "suppliers": suppliers,
        "users": users,
        "page_title": "Add Manual Collection",
        "default_driver_id": default_driver_id,
        "Joachim_found": joachim_found,
    }
    return render(request, "driver_list/add_manual_collection.html", context)
