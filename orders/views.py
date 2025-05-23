import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Case, When
from .models import Order, OrderItem, PurchaseOrder
from wfdash.models import (
    Company,
    Suppliers,
    CompanyDetails,
    Customers,
)  # Added Customers here
from .utils import is_mobile
from django.http import JsonResponse, HttpResponse
from .forms import OrderForm, OrderItemFormSet
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Image,
    Spacer,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from decimal import Decimal, InvalidOperation
from io import BytesIO
from django.utils import timezone
from django.core.files.base import ContentFile
from driver_list.models import Collection, DriverListPool  # Add DriverListPool import

import json  # Add this import
from django.views.decorators.http import require_http_methods, require_POST
from django.core.exceptions import ValidationError
import logging
from django.db import transaction  # Add this import at the top
from django.urls import reverse
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
from quotes.models import QuoteRequest  # Add this line
from django.core.cache import cache
from django.views.decorators.cache import cache_control
import hashlib

logger = logging.getLogger(__name__)


def is_mobile(request):
    user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
    return any(
        device in user_agent for device in ["mobile", "android", "iphone", "ipad"]
    )


# Define status colors for order status indicators
STATUS_COLORS = {
    "new": "primary",
    "processing": "info",
    "order_ready": "warning",
    "po_generated": "secondary",
    "completed": "success",
    "cancelled": "danger",
}


@login_required
def order_list(request):
    # Get filter parameters
    search_query = request.GET.get("search", "")
    status_filter = request.GET.get("status", "")
    show_all = request.GET.get("show_all", "") == "1"

    # Determine user permissions
    is_admin = (
        request.user.is_superuser or request.user.groups.filter(name="ADMIN").exists()
    )
    is_invoice = request.user.groups.filter(name="INVOICING").exists()
    is_buyer = request.user.groups.filter(name="BUYER").exists()
    can_view_all = is_admin or is_invoice or is_buyer

    # Base queryset - determine which orders the user can see
    if can_view_all:
        # Admin, Invoice, and Buyer groups see all orders by default
        orders = Order.objects.all()
    else:
        # Other users (like REP) only see their own orders
        orders = Order.objects.filter(rep=request.user)

    # ENHANCED SEARCH: Apply comprehensive search across all relevant fields
    if search_query:
        # Clean up the search query
        search_query = search_query.strip()

        # Create a complex query to search across multiple fields
        orders = orders.filter(
            # Main order fields
            Q(order_number__icontains=search_query)
            | Q(company__company__icontains=search_query)
            | Q(notes__icontains=search_query)
            |
            # Search in rep name
            Q(rep__first_name__icontains=search_query)
            | Q(rep__last_name__icontains=search_query)
            | Q(rep__email__icontains=search_query)
            |
            # Search in linked quotes
            Q(quote__quote_number__icontains=search_query)
            | Q(potential_quote__quote_number__icontains=search_query)
            |
            # Search in items (descriptions, suppliers, notes)
            Q(items__description__icontains=search_query)
            | Q(items__supplier__suppliername__icontains=search_query)
            | Q(items__notes__icontains=search_query)
            |
            # Search in purchase orders
            Q(purchase_orders__po_number__icontains=search_query)
            | Q(purchase_orders__supplier__suppliername__icontains=search_query)
        ).distinct()  # Use distinct to avoid duplicate results

    if status_filter:
        orders = orders.filter(status=status_filter)

    # Add select_related and prefetch_related for performance
    orders = orders.select_related("company", "rep", "quote").prefetch_related("items")

    # Order by status and creation date
    orders = orders.order_by(
        Case(
            When(status="new", then=0),
            When(status="processing", then=1),
            When(status="order_ready", then=2),
            When(status="po_generated", then=3),
            When(status="completed", then=4),
            When(status="cancelled", then=5),
            default=6,
        ),
        "-created_at",
    )

    # Add sub-status information
    for order in orders:
        # Count items in various sub-statuses
        order.pending_count = order.items.filter(item_status="pending").count()
        order.assigned_count = order.items.filter(item_status="assigned").count()
        order.processed_count = order.items.filter(item_status="processed").count()
        order.po_generated_count = order.items.filter(
            item_status="po_generated"
        ).count()
        order.collected_count = order.items.filter(item_status="collected").count()

        # Determine primary sub-status
        if order.po_generated_count > 0:
            order.sub_status = "po_generated"
            order.sub_status_display = "PO Generated"
            order.sub_status_color = "info"
        elif order.processed_count > 0:
            order.sub_status = "processed"
            order.sub_status_display = "Processed"
            order.sub_status_color = "success"
        elif order.assigned_count > 0:
            order.sub_status = "assigned"
            order.sub_status_display = "Supplier Assigned"
            order.sub_status_color = "warning"
        else:
            order.sub_status = "pending"
            order.sub_status_display = "Pending"
            order.sub_status_color = "danger"

    # Use the existing template
    return render(
        request,
        "orders/order_list.html",
        {
            "orders": orders,
            "search_query": search_query,
            "status_filter": status_filter,
            "status_colors": STATUS_COLORS,
            "total_orders": Order.objects.count(),
            "user_orders_count": Order.objects.filter(rep=request.user).count(),
            "show_all": show_all,
            "can_view_all": can_view_all,
        },
    )


@login_required
def order_list_optimized(request):
    # Get search query from GET parameters
    search_query = request.GET.get("search", "")

    # Add this parameter to determine whether to show completed orders
    show_completed = request.GET.get("show_completed", "") == "true"

    # Use select_related for foreign keys
    base_query = Order.objects.select_related(
        "company", "rep", "quote"
    ).prefetch_related(
        "items", "items__supplier"  # Prefetch related items
    )

    # Apply search filter if provided
    if search_query:
        base_query = base_query.filter(
            Q(order_number__icontains=search_query)
            | Q(company__company__icontains=search_query)
            | Q(items__description__icontains=search_query)
        ).distinct()

    # Define the status choices (exclude completed by default)
    status_choices = [
        choice
        for choice in Order.STATUS_CHOICES
        if show_completed or choice[0] != "completed"
    ]

    # Group by status efficiently
    status_orders = {}
    for status_code, _ in status_choices:
        if status_code == "completed" and not show_completed:
            continue
        status_orders[status_code] = list(
            base_query.filter(status=status_code).order_by("-created_at")[:100]
        )

    # Define status colors
    status_colors = STATUS_COLORS.copy()

    # Ensure all status codes have a color
    for status_code, _ in status_choices:
        if status_code not in status_colors:
            status_colors[status_code] = "secondary"

    context = {
        "status_choices": status_choices,
        "status_orders": status_orders,
        "search_query": search_query,
        "status_colors": status_colors,
        "show_completed": show_completed,
    }

    return render(request, "orders/order_list_optimized.html", context)


def invalidate_order_cache(user_id=None):
    """Helper function to invalidate order cache"""
    from django.core.cache import cache

    if user_id:
        # Find and delete all cache entries for this user
        keys_to_delete = [
            k for k in cache._cache.keys() if f"order_list_{user_id}" in k
        ]
        for key in keys_to_delete:
            cache.delete(key)
    else:
        # Clear all order list caches
        keys_to_delete = [k for k in cache._cache.keys() if "order_list_" in k]
        for key in keys_to_delete:
            cache.delete(key)


@login_required
def order_create(request):
    # Get sales reps - users in REP or ADMIN groups
    from django.contrib.auth.models import Group, User

    rep_group = Group.objects.filter(name="REP").first()
    admin_group = Group.objects.filter(name="ADMIN").first()

    user_queryset = (
        User.objects.filter(
            Q(groups=rep_group) | Q(groups=admin_group) | Q(is_superuser=True)
        )
        .distinct()
        .order_by("first_name", "last_name")
    )

    if request.method == "POST":
        order_form = OrderForm(request.POST, user_queryset=user_queryset)
        if order_form.is_valid():
            order = order_form.save(commit=False)
            order.save()

            # Process items
            descriptions = request.POST.getlist("description[]")
            quantities = request.POST.getlist("quantity[]")
            selling_prices = request.POST.getlist("selling_price[]")
            notes = request.POST.getlist("notes[]")

            item_count = 0
            for i in range(len(descriptions)):
                if descriptions[i]:  # Only create item if description exists
                    OrderItem.objects.create(
                        order=order,
                        description=descriptions[i],
                        quantity=quantities[i] if i < len(quantities) else 1,
                        selling_price=(
                            selling_prices[i] if i < len(selling_prices) else 0
                        ),
                        notes=notes[i] if i < len(notes) else "",
                    )
                    item_count += 1

            # Attempt quote matching
            from .utils import attempt_quote_matching

            was_matched, matched_quote, confidence = attempt_quote_matching(order)

            if was_matched:
                messages.info(
                    request,
                    f"Order automatically linked to Quote #{matched_quote.quote_number} with {confidence}% confidence.",
                )

            # Check if this is an AJAX request
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": True,
                        "order_number": order.order_number,
                        "order_id": order.id,
                        "item_count": item_count,
                        "message": f"Order #{order.order_number} created successfully with {item_count} items.",
                    }
                )
            else:
                messages.success(
                    request,
                    f"Order #{order.order_number} created successfully with {item_count} items.",
                )
                invalidate_order_cache()
                return redirect("orders:order_detail", pk=order.pk)
        else:
            # Form is invalid
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": False,
                        "message": "There were errors in your form",
                        "errors": order_form.errors,
                    },
                    status=400,
                )
    else:
        # Set the logged-in user as the default rep
        order_form = OrderForm(
            user_queryset=user_queryset, initial={"rep": request.user}
        )

    template = (
        "orders/mobile/order_form.html"
        if is_mobile(request)
        else "orders/order_form.html"
    )
    return render(request, template, {"form": order_form})


# Add this function before the order_detail view
def get_suppliers_for_order(order):
    """
    Get unique suppliers associated with processed items in an order
    that are ready for PO generation.
    """
    # Get all items for this order that have been processed but don't have a PO yet
    items = order.items.filter(item_status="processed", purchase_order__isnull=True)

    # Extract unique suppliers
    suppliers = set()
    for item in items:
        if item.supplier:
            suppliers.add(item.supplier)

    return list(suppliers)


# Add this function before the process_order view
def get_suppliers_with_items(order):
    """
    Get suppliers with their associated items for an order that are
    processed but don't have a purchase order yet.
    """
    suppliers_items = {}

    # Get all processed items without PO
    items = order.items.filter(item_status="processed", purchase_order__isnull=True)

    # Group by supplier
    for item in items:
        if item.supplier:
            if item.supplier.id not in suppliers_items:
                suppliers_items[item.supplier.id] = {
                    "supplier": item.supplier,
                    "items": [],
                }
            suppliers_items[item.supplier.id]["items"].append(item)

    return list(suppliers_items.values())


@login_required
def order_detail(request, pk):
    # Determine if user has view-all permission
    is_admin = (
        request.user.is_superuser or request.user.groups.filter(name="ADMIN").exists()
    )
    is_invoice = request.user.groups.filter(name="INVOICING").exists()
    is_buyer = request.user.groups.filter(name="BUYER").exists()
    can_view_all = is_admin or is_invoice or is_buyer

    # Get the order
    if can_view_all:
        # These groups can view any order
        order = get_object_or_404(Order, pk=pk)
    else:
        # Other users can only view their own orders
        order = get_object_or_404(Order, pk=pk, rep=request.user)

    # Get other data needed for the template
    suppliers = get_suppliers_for_order(order)

    # Add all possible item statuses for the timeline
    order_item_statuses = OrderItem.ITEM_STATUS_CHOICES

    # Create a nested dictionary to track which statuses each item has reached
    item_status_reached = {}
    status_progression = [status[0] for status in OrderItem.ITEM_STATUS_CHOICES]

    for item in order.items.all():
        item_status_reached[item.id] = {}
        current_status_index = status_progression.index(item.item_status)

        # Mark all previous statuses as reached
        for i, status_code in enumerate(status_progression):
            if i <= current_status_index:
                item_status_reached[item.id][status_code] = True
            else:
                item_status_reached[item.id][status_code] = False

    # Calculate item progress percentages
    item_progress = {}
    total_statuses = len(OrderItem.ITEM_STATUS_CHOICES)

    for item in order.items.all():
        current_status_index = next(
            (
                i
                for i, (code, _) in enumerate(OrderItem.ITEM_STATUS_CHOICES)
                if code == item.item_status
            ),
            0,
        )
        # Calculate percentage (position / total positions * 100)
        item_progress[item.id] = round(
            (current_status_index + 1) / total_statuses * 100
        )

    context = {
        "order": order,
        "suppliers": suppliers,
        "can_view_all": can_view_all,
        "is_admin": is_admin,
        "is_invoice": is_invoice,
        "is_buyer": is_buyer,
        "order_item_statuses": order_item_statuses,
        "item_status_reached": item_status_reached,
        "item_progress": item_progress,
    }

    return render(request, "orders/order_detail.html", context)


@login_required
def order_edit(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if order.status != "new":
        messages.error(request, "Only new orders can be edited")
        return redirect("orders:order_detail", pk=order.pk)

    # Get sales reps - users in REP or ADMIN groups
    from django.contrib.auth.models import Group, User

    rep_group = Group.objects.filter(name="REP").first()
    admin_group = Group.objects.filter(name="ADMIN").first()

    user_queryset = (
        User.objects.filter(
            Q(groups=rep_group) | Q(groups=admin_group) | Q(is_superuser=True)
        )
        .distinct()
        .order_by("first_name", "last_name")
    )

    template = (
        "orders/mobile/order_form.html"
        if is_mobile(request)
        else "orders/order_form.html"
    )

    # Get the existing items to pre-populate the form
    existing_items = order.items.all()

    if request.method == "POST":
        form = OrderForm(request.POST, instance=order, user_queryset=user_queryset)
        if form.is_valid():
            form.save()

            # Update existing items and add new ones
            order.items.all().delete()  # Remove existing items

            descriptions = request.POST.getlist("description[]")
            quantities = request.POST.getlist("quantity[]")
            selling_prices = request.POST.getlist("selling_price[]")
            notes = request.POST.getlist("notes[]")

            # For debugging
            print(
                f"Descriptions: {len(descriptions)}, Quantities: {len(quantities)}, Prices: {len(selling_prices)}, Notes: {len(notes)}"
            )

            item_count = 0
            for i in range(len(descriptions)):
                if descriptions[i]:  # Only create item if description exists
                    try:
                        # Safely get values with proper index checks
                        qty = (
                            int(quantities[i])
                            if i < len(quantities) and quantities[i]
                            else 1
                        )

                        # Safely get selling price
                        price = 0
                        if i < len(selling_prices) and selling_prices[i]:
                            try:
                                price = float(selling_prices[i])
                            except ValueError:
                                price = 0

                        # Safely get notes
                        note = notes[i] if i < len(notes) else ""

                        OrderItem.objects.create(
                            order=order,
                            description=descriptions[i],
                            quantity=qty,
                            selling_price=price,
                            notes=note,
                        )
                        item_count += 1
                    except Exception as e:
                        messages.error(request, f"Error with item {i+1}: {str(e)}")
                        continue

            if item_count > 0:
                messages.success(
                    request, f"Order updated successfully with {item_count} items"
                )
                invalidate_order_cache()

                # If AJAX request
                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return JsonResponse(
                        {
                            "success": True,
                            "redirect_url": reverse(
                                "orders:order_detail", kwargs={"pk": order.pk}
                            ),
                            "order_id": order.pk,
                            "message": f"Order updated successfully with {item_count} items",
                        }
                    )

                return redirect("orders:order_detail", pk=order.pk)
            else:
                messages.error(request, "No valid items were provided")
        else:
            # Handle form validation errors
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {"success": False, "errors": form.errors}, status=400
                )
    else:
        form = OrderForm(instance=order, user_queryset=user_queryset)

    # Add the existing items to the context
    return render(
        request,
        template,
        {
            "form": form,
            "order": order,
            "existing_items": existing_items,
            "customers": Company.objects.all().order_by("company"),
            "suppliers": Suppliers.objects.all().order_by("suppliername"),
        },
    )


@login_required
def order_delete(request, pk):
    if request.method == "POST":
        order = get_object_or_404(Order, pk=pk)
        order.delete()
        messages.success(request, "Order deleted successfully")
        invalidate_order_cache()
        return redirect("orders:order_list")
    return redirect("orders:order_list")


@login_required
def process_order(request, pk):
    order = get_object_or_404(Order, pk=pk)
    items = order.items.all()

    # Get all suppliers for the dropdown
    suppliers = Suppliers.objects.all().order_by("suppliername")

    # If the order has a linked quote, prepare to pre-fill supplier and cost info
    quote_items_map = {}
    if order.quote:
        for quote_item in order.quote.items.all():
            # Create a simplified version of the quote item description for matching
            simplified_desc = "".join(
                c.lower() for c in quote_item.description if c.isalnum()
            )
            quote_items_map[simplified_desc] = {
                "supplier": quote_item.supplier,
                "cost_price": quote_item.cost_price,
                "notes": quote_item.notes,
            }

    # Process form submission
    if request.method == "POST":
        # Your existing processing code...
        pass

    # Pre-process data for the template
    suppliers_for_order = get_suppliers_for_order(order)
    has_items_with_suppliers = any(
        item.supplier and item.item_status == "processed" for item in items
    )

    # For each order item without supplier info, try to find a matching quote item
    for item in items:
        if not item.supplier and not item.cost_price and order.quote:
            # Create simplified description for matching
            simplified_desc = "".join(
                c.lower() for c in item.description if c.isalnum()
            )

            # Look for a matching quote item
            if simplified_desc in quote_items_map:
                quote_item_data = quote_items_map[simplified_desc]
                item.suggested_supplier = quote_item_data["supplier"]
                item.suggested_cost = quote_item_data["cost_price"]
                item.quote_notes = quote_item_data["notes"]

    return render(
        request,
        "orders/order_process.html",
        {
            "order": order,
            "items": items,
            "suppliers": suppliers,
            "suppliers_items": suppliers_for_order,
            "has_items_with_suppliers": has_items_with_suppliers,
            "linked_quote": order.quote,
        },
    )


@login_required
def generate_purchase_order(request, order_id, supplier_id):
    try:
        with transaction.atomic():
            order = get_object_or_404(Order, id=order_id)
            supplier = get_object_or_404(Suppliers, id=supplier_id)

            # Special handling for CNL - IN STOCK
            is_internal_stock = supplier.suppliername == "CNL - IN STOCK"

            # Get company details with fallback values
            company_info = {
                "company_name": "CNL Mining Supplies (Pty) Ltd",
                "address": "47 Station Street, Carletonville, Gauteng 2499",
                "phone": "+27 18 786 2897",
                "email": "laura@wfsales.co.za",
            }

            # Initialize company_details variable outside the try block
            company_details = None

            try:
                company_details = CompanyDetails.objects.first()
                if company_details:
                    # Use getattr with fallbacks to handle different field names
                    if hasattr(company_details, "company_name"):
                        company_info["company_name"] = company_details.company_name
                    elif hasattr(company_details, "name"):
                        company_info["company_name"] = company_details.name

                    company_info["address"] = getattr(
                        company_details, "address", company_info["address"]
                    )
                    company_info["phone"] = getattr(
                        company_details,
                        "phone",
                        getattr(company_details, "number", company_info["phone"]),
                    )
                    company_info["email"] = getattr(
                        company_details, "email", company_info["email"]
                    )
            except Exception as e:
                logger.error(f"Error getting company details: {str(e)}")
                # Continue with default values

            # Get items for this supplier that aren't in a PO yet
            items = order.items.filter(
                supplier=supplier, item_status="processed", purchase_order__isnull=True
            )

            if not items.exists():
                messages.error(request, "No items found for this supplier")
                return redirect("orders:order_detail", pk=order_id)

            # Generate PO number
            last_po = (
                PurchaseOrder.objects.filter(po_number__startswith="PO")
                .order_by("-po_number")
                .first()
            )

            if last_po:
                try:
                    last_number = int(last_po.po_number.split("-")[0][2:])
                    next_number = str(last_number + 1).zfill(5)
                except (ValueError, IndexError):
                    next_number = "00001"
            else:
                next_number = "00001"

            # Format PO number with company prefix
            company_prefix = "".join(order.company.company.split()[:1])[0:3].upper()
            po_number = f"PO{next_number}-{company_prefix}"

            # Create PO
            po = PurchaseOrder.objects.create(
                po_number=po_number,
                order=order,
                supplier=supplier,
                status=(
                    "processed" if is_internal_stock else "draft"
                ),  # Auto-process internal stock
            )

            # Update items and calculate total
            total_amount = Decimal("0")
            for item in items:
                item.purchase_order = po
                item.item_status = "po_generated"
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
                    status="pending",
                )

                # Create Collection entry
                collection = Collection.objects.create(
                    order_item=item,
                    supplier=supplier,
                    quantity=item.order_qty,  # Use order_qty here
                    status=(
                        "collected" if is_internal_stock else "pending"
                    ),  # Auto-collect internal stock
                )

                # For internal stock, immediately create a stock item
                if is_internal_stock:
                    from stock_management.models import StockItem

                    StockItem.objects.create(
                        collection=collection,
                        order_item=item,
                        received_qty=item.order_qty,
                        verified_quantity=item.order_qty,
                        status="verified",  # Auto-verify since it's internal
                        external_invoice_number="INTERNAL-STOCK",
                        external_invoice_date=timezone.now().date(),
                        notes="Internal stock item",
                        verified_by=request.user,
                        received_date=timezone.now().date(),
                    )

            # Generate PDF
            buffer = BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=letter,
                rightMargin=36,
                leftMargin=36,
                topMargin=36,
                bottomMargin=36,
            )
            elements = []
            styles = getSampleStyleSheet()

            # Header with logo and company info
            # Create left column with company info
            company_info_table = Table(
                [
                    [
                        Paragraph(
                            f"<b>{company_info['company_name']}</b>", styles["Heading1"]
                        )
                    ],
                    [Paragraph(company_info["address"], styles["Normal"])],
                    [Paragraph(company_info["phone"], styles["Normal"])],
                    [Paragraph(company_info["email"], styles["Normal"])],
                ],
                colWidths=[4 * inch],
            )

            # Handle logo with fallback
            logo_element = None
            try:
                if (
                    company_details
                    and hasattr(company_details, "logo")
                    and company_details.logo
                ):
                    logo_element = Image(
                        company_details.logo.path, width=2 * inch, height=1.25 * inch
                    )
                else:
                    # Create a blank space or use a default logo
                    logo_element = Spacer(2 * inch, 1.25 * inch)
            except Exception as e:
                logger.error(f"Error loading logo: {str(e)}")
                logo_element = Spacer(2 * inch, 1.25 * inch)

            header_data = [[company_info_table, logo_element]]
            header_table = Table(header_data, colWidths=[4 * inch, 4 * inch])
            header_table.setStyle(
                TableStyle(
                    [
                        ("ALIGN", (0, 0), (0, -1), "LEFT"),
                        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
                    ]
                )
            )
            elements.append(header_table)
            elements.append(Spacer(1, 20))

            # PO Title and Reference
            elements.append(Paragraph("<b>PURCHASE ORDER</b>", styles["Heading1"]))
            elements.append(Paragraph(f"PO Number: {po_number}", styles["Normal"]))
            elements.append(
                Paragraph(
                    f"Date: {timezone.now().strftime('%d %B %Y')}", styles["Normal"]
                )
            )
            elements.append(Spacer(1, 20))

            # Supplier and Order details
            details_data = [
                [
                    Table(
                        [
                            [Paragraph("<b>SUPPLIER:</b>", styles["Normal"])],
                            [Paragraph(f"{supplier.suppliername}", styles["Normal"])],
                            [
                                Paragraph(
                                    f"{getattr(supplier, 'contact', '')}",
                                    styles["Normal"],
                                )
                            ],
                        ],
                        colWidths=[3 * inch],
                    ),
                    Table(
                        [
                            [Paragraph("<b>ORDER DETAILS:</b>", styles["Normal"])],
                            [
                                Paragraph(
                                    f"Order #: {order.order_number}", styles["Normal"]
                                )
                            ],
                            #        [Paragraph(f"Customer: {order.company.company}", styles['Normal'])],
                        ],
                        colWidths=[3 * inch],
                    ),
                ]
            ]

            details_table = Table(details_data, colWidths=[4 * inch, 4 * inch])
            elements.append(details_table)
            elements.append(Spacer(1, 20))

            # Items table
            table_data = [["Description", "Quantity", "Unit Price", "Total"]]
            for item in items:
                amount = item.order_qty * item.cost_price
                # Use po_description instead of description
                description_text = (
                    item.po_description if item.po_description else item.description
                )
                description_paragraph = Paragraph(description_text, styles["Normal"])
                table_data.append(
                    [
                        description_paragraph,
                        str(item.order_qty),
                        f"R {item.cost_price:,.2f}",
                        f"R {amount:,.2f}",
                    ]
                )

            # Add totals
            subtotal = total_amount
            vat = subtotal * Decimal("0.15")
            total = subtotal + vat

            table_data.extend(
                [
                    ["", "", "Subtotal:", f"R {subtotal:,.2f}"],
                    ["", "", "VAT (15%):", f"R {vat:,.2f}"],
                    ["", "", "Total:", f"R {total:,.2f}"],
                ]
            )

            # Adjust column widths and update table style
            items_table = Table(
                table_data, colWidths=[4 * inch, 1.2 * inch, 1.4 * inch, 1.4 * inch]
            )
            items_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5B6711")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 12),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                        (
                            "ALIGN",
                            (0, 1),
                            (0, -4),
                            "LEFT",
                        ),  # Left-align description column
                        (
                            "VALIGN",
                            (0, 0),
                            (-1, -1),
                            "MIDDLE",
                        ),  # Vertically center all cells
                        ("GRID", (0, 0), (-1, -4), 0.25, colors.grey),
                        ("LINEABOVE", (-2, -3), (-1, -3), 1, colors.grey),
                        (
                            "LINEABOVE",
                            (-2, -1),
                            (-1, -1),
                            2,
                            colors.HexColor("#5B6711"),
                        ),
                        (
                            "LEFTPADDING",
                            (0, 1),
                            (0, -4),
                            6,
                        ),  # Add some padding to description cells
                        ("RIGHTPADDING", (0, 1), (0, -4), 6),
                        (
                            "TOPPADDING",
                            (0, 1),
                            (-1, -4),
                            4,
                        ),  # Add vertical padding for all cells
                        ("BOTTOMPADDING", (0, 1), (-1, -4), 4),
                    ]
                )
            )
            elements.append(items_table)

            # Build and save PDF
            doc.build(elements)

            # Save to PO
            po.pdf_file.save(
                f"PO_{po_number}.pdf", ContentFile(buffer.getvalue()), save=True
            )

            # Update PO total and save
            po.total_amount = total_amount
            po.save()

            # Update order status
            order.update_order_status()

            if is_internal_stock:
                messages.success(
                    request,
                    f"Internal items automatically processed and added to stock inventory",
                )
            else:
                messages.success(
                    request,
                    f"Purchase Order {po_number} generated for {supplier.suppliername}",
                )

            return redirect("orders:preview_po", po_id=po.id)  # Updated redirect

    except Exception as e:
        logger.error(f"Error generating PO: {str(e)}")
        messages.error(request, f"Error generating PO: {str(e)}")
        return redirect("orders:order_detail", pk=order_id)


@require_http_methods(["POST"])
@login_required
def save_order_item(request, item_id):
    try:
        data = json.loads(request.body)
        item = get_object_or_404(OrderItem, id=item_id)

        # Extract and validate data
        supplier_id = data.get("supplier_id")
        cost_price_str = data.get("cost_price", "0")
        order_qty = data.get("quantity")
        po_description = data.get("po_description")  # Add this line

        if not supplier_id:
            return JsonResponse(
                {"status": "error", "message": "Supplier is required"}, status=400
            )

        # Convert cost price to Decimal safely
        try:
            # Convert the cost_price_str to a Decimal
            cost_price = Decimal(cost_price_str)
        except (ValueError, InvalidOperation) as e:
            return JsonResponse(
                {"status": "error", "message": f"Invalid cost price: {str(e)}"},
                status=400,
            )

        # Update item
        item.supplier_id = supplier_id
        item.cost_price = cost_price

        # Save PO description if provided
        if po_description is not None:
            item.po_description = po_description

        # Update order_qty if provided
        if order_qty:
            try:
                order_qty = int(order_qty)
                if order_qty > 0:
                    item.order_qty = order_qty
            except ValueError:
                return JsonResponse(
                    {"status": "error", "message": "Invalid quantity"}, status=400
                )

        # Calculate markup here before saving
        if item.selling_price:
            item.markup = (
                (item.selling_price - item.cost_price) / item.cost_price
            ) * 100

        # Only change status if it was pending
        if item.item_status == "pending":
            item.item_status = "processed"

        # Save the item
        item.save()

        # Return success with updated values
        return JsonResponse(
            {
                "status": "success",
                "message": "Item saved successfully",
                "data": {
                    "item_id": item.id,
                    "markup": float(item.markup) if item.markup is not None else 0,
                    "status": item.get_item_status_display(),
                    "status_code": item.item_status,
                    "po_description": item.po_description,
                },
            }
        )
    except Exception as e:
        logger.error(f"Error saving order item {item_id}: {str(e)}")
        return JsonResponse(
            {"status": "error", "message": "An error occurred while saving the item"},
            status=500,
        )


@login_required
def split_order_item(request, item_id):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            splits = data.get("splits", [])

            # Validate we have at least one split
            if not splits:
                return JsonResponse(
                    {"status": "error", "message": "No split data provided"}
                )

            # Get the original item
            original_item = get_object_or_404(OrderItem, id=item_id)

            # Check permission - only allow splitting for pending or processed items
            if original_item.item_status not in ["pending", "processed"]:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Cannot split items that have already been processed further",
                    }
                )

            # Validate total quantity matches original
            total_split_qty = sum(split.get("quantity", 0) for split in splits)
            if total_split_qty != original_item.quantity:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": f"Total quantity {total_split_qty} does not match original quantity {original_item.quantity}",
                    }
                )

            # Use transaction to ensure all or nothing
            with transaction.atomic():
                # Keep first split in the original item
                first_split = splits.pop(0)

                # Update original item with first split data
                original_item.quantity = first_split["quantity"]
                original_item.order_qty = first_split["quantity"]
                original_item.supplier_id = first_split["supplier_id"]

                # Convert cost price to Decimal properly for the first split
                # This is where the error is occurring
                try:
                    # Handle cost price specifically - we need to ensure we're creating a valid Decimal
                    cost_price_value = first_split["cost_price"]
                    if isinstance(cost_price_value, int) or isinstance(
                        cost_price_value, float
                    ):
                        cost_price_value = str(cost_price_value)

                    # Now create the Decimal from the string representation
                    original_item.cost_price = Decimal(cost_price_value)
                except (InvalidOperation, ValueError, TypeError) as e:
                    logger.error(
                        f"Error converting cost price '{first_split['cost_price']}' to Decimal: {str(e)}"
                    )
                    return JsonResponse(
                        {
                            "status": "error",
                            "message": f'Invalid cost price format: {first_split["cost_price"]}. Please use a number like 10.00',
                        },
                        status=400,
                    )

                # Recalculate markup if needed
                if original_item.selling_price:
                    try:
                        original_item.markup = (
                            (original_item.selling_price - original_item.cost_price)
                            / original_item.cost_price
                        ) * 100
                    except Exception as e:
                        logger.error(f"Error calculating markup: {str(e)}")
                        original_item.markup = 0

                if original_item.item_status == "pending":
                    original_item.item_status = "processed"

                # Save the original item with the new values
                try:
                    original_item.save()
                except Exception as e:
                    logger.error(f"Error saving original item: {str(e)}")
                    return JsonResponse(
                        {"status": "error", "message": f"Error saving item: {str(e)}"},
                        status=500,
                    )

                # Create new items for each additional split
                for split in splits:
                    # Convert cost price to Decimal properly for each split
                    try:
                        # Same careful handling for each split item
                        cost_price_value = split["cost_price"]
                        if isinstance(cost_price_value, int) or isinstance(
                            cost_price_value, float
                        ):
                            cost_price_value = str(cost_price_value)

                        cost_price = Decimal(cost_price_value)
                    except (InvalidOperation, ValueError, TypeError) as e:
                        logger.error(
                            f"Error converting cost price '{split['cost_price']}' to Decimal: {str(e)}"
                        )
                        return JsonResponse(
                            {
                                "status": "error",
                                "message": f'Invalid cost price format: {split["cost_price"]}. Please use a number like 10.00',
                            },
                            status=400,
                        )

                    # Create new OrderItem with careful error handling
                    try:
                        new_item = OrderItem.objects.create(
                            order=original_item.order,
                            description=original_item.description,
                            po_description=original_item.po_description,
                            quantity=split["quantity"],
                            order_qty=split["quantity"],
                            selling_price=original_item.selling_price,
                            supplier_id=split["supplier_id"],
                            cost_price=cost_price,
                            item_status="processed",
                            notes=f"Split from item #{original_item.id}",
                        )

                        # Calculate markup for the new item
                        if new_item.selling_price:
                            try:
                                new_item.markup = (
                                    (new_item.selling_price - new_item.cost_price)
                                    / new_item.cost_price
                                ) * 100
                                new_item.save(update_fields=["markup"])
                            except Exception as e:
                                logger.error(
                                    f"Error calculating markup for split item: {str(e)}"
                                )
                    except Exception as e:
                        logger.error(f"Error creating new split item: {str(e)}")
                        return JsonResponse(
                            {
                                "status": "error",
                                "message": f"Error creating split item: {str(e)}",
                            },
                            status=500,
                        )

            # Return success response
            return JsonResponse(
                {
                    "status": "success",
                    "message": "Item split successfully",
                    "original_item_id": original_item.id,
                }
            )
        except Exception as e:
            # Log the error
            logger.error(f"Error splitting item {item_id}: {str(e)}")
            return JsonResponse(
                {"status": "error", "message": f"Error splitting item: {str(e)}"},
                status=500,
            )

    return JsonResponse({"status": "error"}, status=400)


@login_required
def purchase_order_list(request):
    purchase_orders = PurchaseOrder.objects.all().order_by("-created_at")
    return render(
        request, "orders/purchase_order_list.html", {"purchase_orders": purchase_orders}
    )


@login_required
def download_purchase_order(request, po_id):
    try:
        po = get_object_or_404(PurchaseOrder, id=po_id)
        if po.pdf_file:
            response = HttpResponse(po.pdf_file, content_type="application/pdf")
            response["Content-Disposition"] = (
                f'attachment; filename="{po.po_number}.pdf"'
            )
            return response
        raise ValueError("PDF file not found")
    except Exception as e:
        messages.error(request, f"Error downloading PO: {str(e)}")
        return redirect("orders:order_detail", pk=po.order.id)


@login_required
def check_available_po_items(request, order_id, supplier_id):
    items = OrderItem.objects.filter(
        order_id=order_id,
        supplier_id=supplier_id,
        purchase_order__isnull=True,
        item_status="processed",
    )

    data = {
        "available_items": [
            {
                "id": item.id,
                "description": item.description,
                "quantity": item.order_qty,
                "cost_price": str(item.cost_price),
            }
            for item in items
        ]
    }

    return JsonResponse(data)


@login_required
def preview_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    return render(request, "orders/po_preview.html", {"po": po})


@login_required
def download_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    if po.pdf_file:
        response = HttpResponse(po.pdf_file, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{po.po_number}.pdf"'
        return response
    messages.error(request, "PDF file not found")
    return redirect("orders:order_detail", pk=po.order.id)


@login_required
def email_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)

    # Just redirect to the preview page with a message
    messages.info(request, "Email functionality is currently disabled.")
    return redirect("orders:preview_po", po_id=po.id)


@login_required
def preview_purchase_order(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    context = {"po": po, "title": f"Preview PO - {po.po_number}"}
    return render(request, "orders/po_preview.html", context)


@login_required
def email_purchase_order(request, po_id):
    try:
        po = get_object_or_404(PurchaseOrder, id=po_id)

        if not po.pdf_file:
            messages.error(request, "PDF file not found")
            return redirect("orders:preview_po", po_id=po.id)

        # Get supplier email
        supplier_email = getattr(po.supplier, "email", None)
        if not supplier_email:
            messages.error(request, "Supplier email not found")
            return redirect("orders:preview_po", po_id=po.id)

        # Prepare email
        subject = f"Purchase Order - {po.po_number}"
        message = render_to_string(
            "orders/email/po_email.html",
            {
                "po": po,
                "supplier": po.supplier,
            },
        )

        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[supplier_email],
        )

        # Attach PO PDF
        email.attach(f"{po.po_number}.pdf", po.pdf_file.read(), "application/pdf")

        email.send()

        messages.success(
            request, f"Purchase Order {po.po_number} sent to {supplier_email}"
        )
        return redirect("orders:preview_po", po_id=po.id)

    except Exception as e:
        messages.error(request, f"Error sending email: {str(e)}")
        return redirect("orders:preview_po", po_id=po.id)


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
            bottomMargin=36,
        )
        elements = []
        styles = getSampleStyleSheet()

        # Add custom styles
        styles.add(
            ParagraphStyle(
                name="CompanyName",
                parent=styles["Heading1"],
                fontSize=14,
                alignment=0,
                spaceBefore=12,
                spaceAfter=12,
            )
        )

        # Choose company details based on letterhead selection
        if quote.company_letterhead == "CNL":
            company_details = [
                [
                    Paragraph(
                        "<b>CNL Mining Supplies (Pty) Ltd</b>", styles["CompanyName"]
                    )
                ],
                [Paragraph("47 Station Street", styles["Normal"])],
                [Paragraph("Carletonville, Gauteng 2499", styles["Normal"])],
                [Paragraph("+27 18 786 2897", styles["Normal"])],
                [Paragraph("laura@wfsales.co.za", styles["Normal"])],
                [Paragraph("VAT No: 4840229449", styles["Normal"])],
                [Paragraph("Business ID No: 2014/004024/07", styles["Normal"])],
            ]
            logo_path = os.path.join(
                settings.STATIC_ROOT, "assets", "images", "cnl_logo.png"
            )
            banking_details = [
                "Banking Details:",
                "Standard Bank - Carletonville",
                "Current Account",
                "Branch Code: 016141",
                "Account Number: 022196552",
            ]
        else:  # ISHERWOOD
            company_details = [
                [
                    Paragraph(
                        "<b>ISHERWOOD ENGINEERING (PTY) LTD</b>", styles["CompanyName"]
                    )
                ],
                [Paragraph("Registration No: 2014/004024/07", styles["Normal"])],
                [Paragraph("VAT No: 4840229449", styles["Normal"])],
                [Paragraph("Physical Address: 47 Station Street", styles["Normal"])],
                [Paragraph("Carletonville, Gauteng 2499", styles["Normal"])],
                [Paragraph("Contact: +27 18 786 2897", styles["Normal"])],
                [Paragraph("Email: laura@wfsales.co.za", styles["Normal"])],
            ]
            logo_path = os.path.join(
                settings.STATIC_ROOT, "assets", "images", "isherwood_logo.png"
            )
            banking_details = [
                "Banking Details:",
                "Standard Bank",
                "Current Account",
                "Branch Code: XXXXX",
                "Account Number: XXXXXXXXX",
            ]

        # Create header with logo
        header_data = [
            [
                Table(company_details, colWidths=[4 * inch]),
                Image(logo_path, width=2 * inch, height=1.25 * inch),
            ]
        ]

        # ... rest of your PDF generation code ...

        # Add banking details at the end
        elements.append(Spacer(1, 20))
        for detail in banking_details:
            elements.append(Paragraph(detail, styles["Normal"]))

        # Build PDF
        doc.build(elements)

        # Save and return PDF
        buffer.seek(0)
        quote.pdf_file.save(
            f"Quote-{quote.quote_number}.pdf", ContentFile(buffer.getvalue())
        )

        return HttpResponse(
            buffer.getvalue(),
            content_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="Quote-{quote.quote_number}.pdf"'
            },
        )

    except Exception as e:
        messages.error(request, f"Error generating quote: {str(e)}")
        return redirect("quotes:quote_detail", pk=quote_id)


def create_order(request):
    if request.method == "POST":
        form = OrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            # Set other fields...
            order.save()

            # Get item data from POST
            descriptions = request.POST.getlist("description[]")
            quantities = request.POST.getlist("quantity[]")
            selling_prices = request.POST.getlist("selling_price[]")
            notes = request.POST.getlist("notes[]")

            # CRITICAL FIX: If standard approach isn't working for selling prices,
            # use the backup individual fields
            if "use_item_fields" in request.POST and not all(selling_prices):
                print("Using backup item fields for selling prices")
                new_selling_prices = []
                for i in range(len(descriptions)):
                    price_key = f"item_selling_price_{i}"
                    if price_key in request.POST:
                        new_selling_prices.append(request.POST[price_key])
                    else:
                        new_selling_prices.append("0.00")

                if len(new_selling_prices) == len(descriptions):
                    selling_prices = new_selling_prices
                    print(
                        f"Fixed! Using {len(selling_prices)} selling prices from backup fields"
                    )

            # Debug log for server-side troubleshooting
            print(
                f"Processing {len(descriptions)} descriptions, {len(quantities)} quantities, {len(selling_prices)} prices"
            )

            # Create order items
            for i in range(len(descriptions)):
                if descriptions[i]:
                    # Make sure we have a valid price
                    try:
                        price = (
                            Decimal(selling_prices[i])
                            if i < len(selling_prices)
                            else Decimal("0.00")
                        )
                    except (ValueError, InvalidOperation, TypeError):
                        price = Decimal("0.00")

                    # Create the order item
                    OrderItem.objects.create(
                        order=order,
                        description=descriptions[i],
                        quantity=(
                            int(quantities[i])
                            if i < len(quantities) and quantities[i].isdigit()
                            else 1
                        ),
                        selling_price=price,
                        notes=notes[i] if i < len(notes) else "",
                    )

            return JsonResponse(
                {
                    "success": True,
                    "order_id": order.id,
                    "order_number": order.order_number,
                }
            )
        else:
            return JsonResponse({"success": False, "errors": form.errors})
    # [...]


def handle_mailto_error(request, path=None):
    """Handle erroneous mailto URL requests"""
    messages.error(
        request,
        "Email functionality is disabled. This error occurred due to an email link.",
    )
    return redirect("orders:order_list")


@login_required
def check_po_items(request, order_id):
    """API endpoint to check if an order has items ready for PO generation"""
    try:
        order = get_object_or_404(Order, id=order_id)

        # Get all suppliers with their items
        suppliers_with_items = get_suppliers_with_items(order)

        return JsonResponse(
            {
                "success": True,
                "has_po_items": len(suppliers_with_items) > 0,
                "suppliers_items": [
                    {
                        "supplier": {
                            "id": supplier_data["supplier"].id,
                            "suppliername": supplier_data["supplier"].suppliername,
                        },
                        "items": [
                            {
                                "id": item.id,
                                "description": item.description,
                                "order_qty": (
                                    item.order_qty if item.order_qty else item.quantity
                                ),
                            }
                            for item in supplier_data["items"]
                        ],
                    }
                    for supplier_data in suppliers_with_items
                ],
            }
        )

    except Exception as e:
        import traceback

        print(traceback.format_exc())
        return JsonResponse({"success": False, "has_po_items": False, "error": str(e)})


@login_required
def check_order_number(request):
    """API to check if an order number already exists"""
    order_number = request.GET.get("order_number")

    if not order_number:
        return JsonResponse({"exists": False})

    exists = Order.objects.filter(order_number=order_number).exists()

    return JsonResponse({"exists": exists})


@login_required
def find_matching_quotes(request, pk):
    """View to find and suggest matching quotes for an order"""
    order = get_object_or_404(Order, pk=pk)
    print(f"Finding matches for order {order.id}: {order.order_number}")

    # If already linked, redirect back
    if order.quote:
        messages.info(
            request,
            f"This order is already linked to Quote #{order.quote.quote_number}",
        )
        return redirect("orders:order_detail", pk=pk)

    # If user wants to force a new search
    force_search = request.GET.get("force", "") == "1"

    # Try to find matches
    from .utils import attempt_quote_matching

    if force_search:
        # Reset matching status to allow a new search
        order.quote_matching_attempted = False
        order.save(update_fields=["quote_matching_attempted"])

    # Get cached match information BEFORE using matched_items
    import json
    from django.core.cache import cache

    cache_key = f"order_{order.id}_matched_items"
    matched_items = []
    cached_items = cache.get(cache_key)
    if cached_items:
        try:
            matched_items = json.loads(cached_items)
        except json.JSONDecodeError:
            matched_items = []

    was_matched, suggested_quote, confidence = attempt_quote_matching(order)

    # After running matching
    print(f"Match result: was_matched={was_matched}, confidence={confidence}")
    print(f"Matched items: {len(matched_items)}")

    if suggested_quote:
        print(f"Suggested quote: {suggested_quote.quote_number}")

    if was_matched:
        messages.success(
            request,
            f"Order automatically linked to Quote #{suggested_quote.quote_number} with {confidence}% confidence.",
        )
        return redirect("orders:order_detail", pk=pk)

    # Find potential quotes for this company (most recent first)
    potential_quotes = QuoteRequest.objects.filter(
        Q(status="processed") | Q(status="complete"), customer__company=order.company
    ).order_by("-created_at")[:30]

    return render(
        request,
        "orders/find_matching_quotes.html",
        {
            "order": order,
            "suggested_quote": suggested_quote,
            "suggested_confidence": confidence,
            "potential_quotes": potential_quotes,
            "matched_items": matched_items,
        },
    )


@login_required
@require_http_methods(["POST"])
def link_quote(request, order_id, quote_id):
    """Link an order to a quote manually"""
    order = get_object_or_404(Order, pk=order_id)
    quote = get_object_or_404(QuoteRequest, pk=quote_id)

    # Link order to quote
    order.quote = quote
    order.quote_matching_attempted = True
    order.quote_match_confidence = 100  # Manual linking = 100% confidence
    order.save(
        update_fields=["quote", "quote_matching_attempted", "quote_match_confidence"]
    )

    messages.success(
        request,
        f"Order #{order.order_number} has been linked to Quote #{quote.quote_number}",
    )
    return redirect("orders:order_detail", pk=order_id)


@login_required
@require_http_methods(["POST"])
def unlink_quote(request, order_id):
    """Unlink a quote from an order"""
    order = get_object_or_404(Order, pk=order_id)

    if order.quote:
        quote_number = order.quote.quote_number
        order.quote = None
        order.quote_match_confidence = None
        order.save(update_fields=["quote", "quote_match_confidence"])
        messages.success(
            request, f"Quote #{quote_number} has been unlinked from this order"
        )

    return redirect("orders:order_detail", pk=order_id)


@login_required
def get_item_status(request, item_id):
    """API to get current status of an item with detailed information"""
    item = get_object_or_404(OrderItem, id=item_id)

    # Get related collection info (if any)
    collection = (
        Collection.objects.filter(order_item=item).order_by("-created_at").first()
    )
    collection_data = None
    if collection:
        collection_data = {
            "id": collection.id,
            "status": collection.status,
            "driver": collection.driver.get_full_name() if collection.driver else None,
            "planned_date": (
                collection.planned_date.strftime("%Y-%m-%d")
                if collection.planned_date
                else None
            ),
            "actual_date": (
                collection.actual_date.strftime("%Y-%m-%d")
                if collection.actual_date
                else None
            ),
            "received_qty": (
                float(collection.received_qty) if collection.received_qty else None
            ),
        }

    # Get related stock item info (if any)
    stock = StockItem.objects.filter(order_item=item).order_by("-created_at").first()
    stock_data = None
    if stock:
        stock_data = {
            "id": stock.id,
            "status": stock.status,
            "verified_by": (
                stock.verified_by.get_full_name() if stock.verified_by else None
            ),
            "received_qty": float(stock.received_qty) if stock.received_qty else None,
            "picked": stock.picked,
            "picked_by": stock.picked_by.get_full_name() if stock.picked_by else None,
            "picked_date": (
                stock.picked_date.strftime("%Y-%m-%d") if stock.picked_date else None
            ),
        }

    # Map the item status to display which steps have been completed
    status_progression = [status[0] for status in OrderItem.ITEM_STATUS_CHOICES]
    current_status_index = status_progression.index(item.item_status)

    # Create a dictionary of completed steps
    completed_steps = {}
    for i, status_code in enumerate(status_progression):
        completed_steps[status_code] = i <= current_status_index

    return JsonResponse(
        {
            "id": item.id,
            "description": item.description,
            "status": item.item_status,
            "status_display": item.get_item_status_display(),
            "collection": collection_data,
            "stock": stock_data,
            "completed_steps": completed_steps,
        }
    )


@login_required
def order_admin_dashboard(request):
    """Admin dashboard for orders overview"""
    # Check if user is admin
    if (
        not request.user.is_superuser
        and not request.user.groups.filter(name="ADMIN").exists()
    ):
        messages.error(request, "You don't have permission to access this page.")
        return redirect("dashboard:rep_dashboard")

    # Get order statistics
    total_orders = Order.objects.count()
    new_orders = Order.objects.filter(status="new").count()
    processing_orders = Order.objects.filter(status="processing").count()
    completed_orders = Order.objects.filter(status="completed").count()

    # Get recent orders
    recent_orders = Order.objects.all().order_by("-created_at")[:10]

    context = {
        "title": "Order Administration Dashboard",
        "segment": "order_admin",
        "total_orders": total_orders,
        "new_orders": new_orders,
        "processing_orders": processing_orders,
        "completed_orders": completed_orders,
        "recent_orders": recent_orders,
    }

    return render(request, "orders/admin/dashboard.html", context)


@login_required
def bulk_update_orders(request):
    """Bulk update orders and order items"""
    # Check if user is admin
    if (
        not request.user.is_superuser
        and not request.user.groups.filter(name="ADMIN").exists()
    ):
        messages.error(request, "You don't have permission to access this page.")
        return redirect("dashboard:rep_dashboard")

    if request.method == "POST":
        # Handle form submission
        order_ids = request.POST.getlist("order_ids")
        new_status = request.POST.get("new_status")

        if order_ids and new_status:
            # Update orders
            updated = Order.objects.filter(id__in=order_ids).update(status=new_status)
            messages.success(request, f"Updated status for {updated} orders.")
            return redirect("orders:bulk_update_orders")

    # Get orders for display
    orders = Order.objects.all().order_by("-created_at")[:100]

    context = {
        "title": "Bulk Update Orders",
        "segment": "order_admin",
        "orders": orders,
    }

    return render(request, "orders/admin/bulk_update.html", context)


@login_required
def order_analytics(request):
    """Order analytics and reporting"""
    # Check if user is admin
    if (
        not request.user.is_superuser
        and not request.user.groups.filter(name="ADMIN").exists()
    ):
        messages.error(request, "You don't have permission to access this page.")
        return redirect("dashboard:rep_dashboard")

    # Get analytics data
    # ... analytics code here ...

    context = {
        "title": "Order Analytics",
        "segment": "order_admin",
    }

    return render(request, "orders/admin/analytics.html", context)


@login_required
def order_issues(request):
    """View and manage orders with issues"""
    # Check if user is admin
    if (
        not request.user.is_superuser
        and not request.user.groups.filter(name="ADMIN").exists()
    ):
        messages.error(request, "You don't have permission to access this page.")
        return redirect("dashboard:rep_dashboard")

    # Find orders with issues
    # ... code to identify problematic orders ...

    context = {
        "title": "Order Issues",
        "segment": "order_admin",
    }

    return render(request, "orders/admin/issues.html", context)


# In your Django shell or add a temporary view:
from orders.models import Order

order = Order.objects.get(id=297)  # Your problematic order
order.quote_matching_attempted = False
order.save()


@login_required
def test_match(request, order_id, quote_id):
    """Test the similarity between a specific order and quote"""
    order = get_object_or_404(Order, id=order_id)
    quote = get_object_or_404(QuoteRequest, id=quote_id)

    results = []
    matched_count = 0

    for order_item in order.items.all():
        order_desc = order_item.description.lower().strip()

        best_match = None
        best_ratio = 0
        best_desc = None

        for quote_item in quote.items.all():
            quote_desc = quote_item.description.lower().strip()

            # Try different cleaning methods
            clean_order = re.sub(r"\([^)]*\)", "", order_desc).strip()
            clean_quote = re.sub(r"\([^)]*\)", "", quote_desc).strip()

            # Try splitting on hyphen
            if " - " in quote_desc:
                parts = quote_desc.split(" - ", 1)
                quote_desc_parts = [parts[0].strip(), parts[1].strip()]
            else:
                quote_desc_parts = []

            # Compare all variations
            for desc_var in [quote_desc, clean_quote] + quote_desc_parts:
                ratio = difflib.SequenceMatcher(None, order_desc, desc_var).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = quote_item
                    best_desc = desc_var

        result = {
            "order_item": order_item,
            "best_match": best_match,
            "similarity": round(best_ratio * 100, 1),
            "matched_on": best_desc,
            "qty_match": best_match and order_item.quantity == best_match.quantity,
        }

        if best_ratio > 0.4:  # Lower threshold for testing
            matched_count += 1

        results.append(result)

    return render(
        request,
        "orders/test_match.html",
        {
            "order": order,
            "quote": quote,
            "results": results,
            "matched_count": matched_count,
            "total_items": order.items.count(),
            "match_percent": (
                round(matched_count / order.items.count() * 100)
                if order.items.count() > 0
                else 0
            ),
        },
    )


@login_required
def batch_match_quotes(request):
    """Process all unmatched orders and attempt to find quote matches"""
    # Only allow staff/admin to run this
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "You don't have permission to run batch matching")
        return redirect("orders:order_list")

    # Get number of unmatched orders
    unmatched_count = Order.objects.filter(
        quote__isnull=True, quote_matching_attempted=False
    ).count()

    # If this is a POST request, actually do the matching
    if request.method == "POST" and "confirm" in request.POST:
        from .utils import attempt_quote_matching
        import time

        # Get the orders to process
        orders = Order.objects.filter(
            quote__isnull=True, quote_matching_attempted=False
        ).order_by("-created_at")[
            :500
        ]  # Limit to 500 most recent

        # Process them
        results = {
            "total": len(orders),
            "matched": 0,
            "potential": 0,
            "no_match": 0,
            "matched_orders": [],
        }

        start_time = time.time()

        for order in orders:
            was_matched, quote, confidence = attempt_quote_matching(order)

            if was_matched:
                results["matched"] += 1
                results["matched_orders"].append(
                    {"order": order, "quote": quote, "confidence": confidence}
                )
            elif quote:
                results["potential"] += 1
            else:
                results["no_match"] += 1

        processing_time = time.time() - start_time

        return render(
            request,
            "orders/batch_match_results.html",
            {"results": results, "processing_time": round(processing_time, 2)},
        )

    # Otherwise, show the confirmation form
    return render(
        request, "orders/batch_match_confirm.html", {"unmatched_count": unmatched_count}
    )


@login_required
def reset_matching(request):
    """Reset all quote matching attempts to allow re-running the matching process"""
    from django.db import connection

    if request.method == "POST":
        try:
            # Use a raw SQL query for efficiency when handling many records
            with connection.cursor() as cursor:
                # This is the exact SQL you provided
                cursor.execute(
                    """
                    UPDATE orders_order
                    SET
                        quote_match_confidence = NULL,
                        quote_matching_attempted = FALSE,
                        potential_quote_id = NULL,
                        potential_quote_confidence = 0
                """
                )

            # Get count of affected rows (for display purposes)
            count = Order.objects.count()
            messages.success(
                request, f"Successfully reset matching data for {count} orders."
            )
            return redirect("orders:batch_match_quotes")

        except Exception as e:
            messages.error(request, f"Error resetting matching data: {str(e)}")
            return redirect("orders:batch_match_quotes")

    # Count orders to show in confirmation screen
    count = Order.objects.count()
    return render(request, "orders/reset_matching_confirm.html", {"count": count})


@login_required
@require_POST
def reset_selected_matching(request):
    """Reset matching for selected orders"""
    # Only allow staff/admin to reset
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "You don't have permission to reset matching")
        return redirect("orders:order_list")

    order_numbers = request.POST.get("order_numbers", "")
    if not order_numbers.strip():
        messages.error(request, "No order numbers provided")
        return redirect("orders:batch_match_quotes")

    # Parse order numbers
    order_numbers = [num.strip() for num in order_numbers.split(",")]

    try:
        # Reset specified orders
        from django.db import transaction

        with transaction.atomic():
            count = Order.objects.filter(order_number__in=order_numbers).update(
                quote_matching_attempted=False,
                potential_quote=None,
                potential_quote_confidence=None,
            )

        messages.success(request, f"Successfully reset matching for {count} orders")
    except Exception as e:
        messages.error(request, f"Error resetting: {str(e)}")

    return redirect("orders:batch_match_quotes")


@login_required
@require_http_methods(["POST"])
def check_duplicates(request):
    """Check for potential duplicate orders before creating a new one"""
    # Extract data from request
    try:
        company_id = request.POST.get("company")

        # Handle both array-style and regular form data
        if "description[]" in request.POST:
            descriptions = request.POST.getlist("description[]")
        else:
            descriptions = [
                v for k, v in request.POST.items() if k.startswith("description")
            ]

        if "quantity[]" in request.POST:
            quantities = request.POST.getlist("quantity[]")
        else:
            quantities = [
                v for k, v in request.POST.items() if k.startswith("quantity")
            ]

        order_number = request.POST.get("order_number")

        # Prepare data for duplicate checking
        order_data = {
            "company": company_id,
            "description": descriptions,
            "quantity": quantities,
            "order_number": order_number,
        }

        # Check for basic validity
        if not company_id or not descriptions:
            return JsonResponse({"duplicates": []})

        # Import find_potential_duplicate_orders from utils.py
        try:
            from .utils import find_potential_duplicate_orders

            potential_duplicates = find_potential_duplicate_orders(order_data)
        except ImportError:
            # Provide a minimal implementation if the function doesn't exist
            potential_duplicates = []

        # Structure the response
        duplicates_data = []
        for dup in potential_duplicates:
            duplicates_data.append(
                {
                    "order": {
                        "id": dup["order"].id,
                        "order_number": dup["order"].order_number or "Unknown",
                        "created_at": dup["order"].created_at.strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                    },
                    "score": dup["score"],
                    "match_percentage": dup["match_percentage"],
                    "days_ago": dup["days_ago"],
                    "matching_items": dup["matching_items"],
                }
            )

        return JsonResponse({"duplicates": duplicates_data})
    except Exception as e:
        import traceback

        traceback.print_exc()
        return JsonResponse({"error": str(e), "duplicates": []}, status=500)


# Add this to views.py
@login_required
def reset_order_matching(request, pk):
    """Reset matching for a specific order"""
    order = get_object_or_404(Order, pk=pk)

    order.quote = None
    order.quote_match_confidence = None
    order.quote_matching_attempted = False
    order.potential_quote_id = None
    order.potential_quote_confidence = 0
    order.save()

    messages.success(
        request, f"Successfully reset matching data for order #{order.order_number}"
    )
    return redirect("orders:find_matching_quotes", pk=order.pk)


@login_required
def order_item_list(request):
    """View to display order items grouped by status"""
    # Get query parameters
    search_query = request.GET.get("search", "")

    # Base queryset with related objects to avoid N+1 queries
    items = OrderItem.objects.select_related(
        "order", "order__company", "supplier"
    ).all()

    # Apply search filter if provided
    if search_query:
        items = items.filter(
            Q(description__icontains=search_query)
            | Q(order__order_number__icontains=search_query)
            | Q(order__company__company__icontains=search_query)
            | Q(supplier__suppliername__icontains=search_query)
        )

    # Define status display information
    status_info = {
        "pending": {"name": "Pending", "color": "warning"},
        "processed": {"name": "Processed", "color": "info"},
        "po_generated": {"name": "PO Generated", "color": "primary"},
        "driver_pool": {"name": "Driver Pool", "color": "secondary"},
        "assigned": {"name": "Assigned", "color": "dark"},
        "collected": {"name": "Collected", "color": "light text-dark"},
        "stock_verified": {"name": "To Invoice", "color": "info"},
        "picking": {"name": "Picking", "color": "warning"},
        "ready_delivery": {"name": "Ready for Delivery", "color": "primary"},
        "delivered": {"name": "Delivered", "color": "success"},
        "awaiting_po": {"name": "Awaiting PO", "color": "info"},
        "supplier_assigned": {"name": "Supplier Assigned", "color": "warning"},
        "ready_collection": {"name": "Ready for Collection", "color": "success"},
    }

    # Group items by status
    status_groups = {}
    for status, info in status_info.items():
        status_groups[status] = {
            "name": info["name"],
            "color": info["color"],
            "orders": {},
            "count": 0,
        }

    # Group items by status and then by order
    for item in items:
        status = item.item_status
        if status not in status_groups:
            continue  # Skip if not in our defined statuses

        order_id = item.order.id

        # Initialize order group if it doesn't exist
        if order_id not in status_groups[status]["orders"]:
            status_groups[status]["orders"][order_id] = {
                "order": item.order,
                "items": [],
                "count": 0,
            }

        # Add item to its order group
        status_groups[status]["orders"][order_id]["items"].append(item)
        status_groups[status]["orders"][order_id]["count"] += 1
        status_groups[status]["count"] += 1

    # Convert order dictionaries to lists for easier template iteration
    for status in status_groups:
        status_groups[status]["orders"] = list(status_groups[status]["orders"].values())
        # Sort orders by order number
        status_groups[status]["orders"].sort(key=lambda x: x["order"].order_number)

    context = {
        "status_groups": status_groups,
        "search_query": search_query,
    }

    return render(request, "orders/order_item_list.html", context)
