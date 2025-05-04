from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q, F, DecimalField
from django.db.models.functions import Coalesce, TruncMonth, TruncYear
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from quotes.models import QuoteRequest
from orders.models import Order, OrderItem
from wfdash.models import Customers, Suppliers, Company
from driver_list.models import Collection
from django.http import JsonResponse
import json
from django.views.decorators.csrf import csrf_exempt
import requests
from django.conf import settings
from collections import defaultdict
from django.contrib.auth.models import User
from delivery_notes.models import DeliveryNote  # Import DeliveryNote


@login_required
def index(request):
    """Main dashboard router that redirects to appropriate dashboard based on user group"""
    user = request.user

    # Check user groups and redirect accordingly
    if user.is_superuser or user.groups.filter(name="ADMIN").exists():
        # Admin users see the main dashboard
        # Get today's date
        today = timezone.now().date()
        month_start = today.replace(day=1)

        # Get counts
        total_drivers = Collection.objects.count()
        active_drivers = Collection.objects.filter(status="active").count()

        # Calculate percentage (avoid division by zero)
        driver_percentage = (
            (active_drivers / total_drivers * 100) if total_drivers > 0 else 0
        )

        context = {
            "page_title": "Admin Dashboard",
            "total_quotes": QuoteRequest.objects.count(),
            "total_orders": Order.objects.count(),
            "total_collections": Collection.objects.count(),
            "total_customers": Customers.objects.count(),
            # Driver statistics
            "total_drivers": total_drivers,
            "active_drivers": active_drivers,
            "driver_percentage": driver_percentage,
            # Collection statistics
            "pending_collections": Collection.objects.filter(status="pending").count(),
            "assigned_collections": Collection.objects.filter(
                status="assigned"
            ).count(),
            "completed_collections": Collection.objects.filter(
                status="completed"
            ).count(),
            # Recent items
            "recent_quotes": QuoteRequest.objects.order_by("-created_at")[:5],
            "recent_orders": Order.objects.order_by("-created_at")[:5],
            "recent_collections": Collection.objects.order_by("-created_at")[:5],
            "segment": "dashboard",
        }

        return render(request, "dashboard/index.html", context)

    elif user.groups.filter(name="QUOTERS").exists():
        # Redirect Quoters (or show a specific dashboard if needed)
        # For now, let's redirect them to the quotes list
        return redirect(
            "quotes:quote_list"
        )  # Adjust if you have a specific quoter dashboard

    elif user.groups.filter(name="REP").exists():
        # Redirect REP users to their specific detailed dashboard
        return redirect("dashboard:rep_dashboard_detail")  # Renamed target

    elif user.groups.filter(name="BUYER").exists():
        # Redirect Buyers (or show a specific dashboard)
        # For now, redirect to orders list
        return redirect("orders:order_list")  # Adjust if needed

    elif user.groups.filter(name="INVOICE").exists():
        # Redirect Invoice users (or show a specific dashboard)
        # Placeholder - adjust as needed
        return redirect("orders:order_list")  # Adjust if needed

    else:
        # Default fallback for users with no specific group/role
        # Maybe redirect to profile or a generic page
        # For now, let's show a simple message or redirect to login
        return redirect("login")  # Or wherever appropriate


@login_required
def rep_dashboard(request):
    """Dashboard view for sales representatives showing key performance metrics."""
    # Get the current user
    user = request.user

    # Time periods for filtering
    today = timezone.now().date()
    last_30_days = today - timedelta(days=30)
    first_day_of_month = today.replace(day=1)
    last_day_of_month = (
        (
            first_day_of_month.replace(
                month=first_day_of_month.month % 12 + 1,
                year=first_day_of_month.year + first_day_of_month.month // 12,
            )
            - timedelta(days=1)
        )
        if first_day_of_month.month < 12
        else first_day_of_month.replace(day=31, month=12)
    )

    # Check user roles
    is_admin = user.is_superuser or user.groups.filter(name="ADMIN").exists()
    is_quoter = user.groups.filter(name="QUOTERS").exists()
    is_buyer = user.groups.filter(name="BUYER").exists()
    is_invoice = user.groups.filter(name="INVOICING").exists()

    # Determine if user can view all data
    can_view_all = is_admin or is_quoter or is_buyer

    # QUOTES METRICS
    if can_view_all:
        # Admin, quoters, buyers see all quotes
        quotes = QuoteRequest.objects.all()
    else:
        # Regular reps only see their quotes
        quotes = QuoteRequest.objects.filter(rep=user)

    # Calculate quote metrics
    total_quotes = quotes.count()
    quotes_last_30_days = quotes.filter(created_at__gte=last_30_days).count()
    quotes_today = quotes.filter(created_at__date=today).count()

    # Quote status breakdown
    quote_status_counts = quotes.values("status").annotate(count=Count("id"))

    # CUSTOMERS METRICS
    if can_view_all:
        customers = Customers.objects.all()
    else:
        # For regular reps, show customers they've worked with
        customer_ids = quotes.values_list("customer", flat=True).distinct()
        customers = Customers.objects.filter(id__in=customer_ids)

    total_customers = customers.count()
    new_customers_30_days = customers.filter(dateadded__gte=last_30_days).count()

    # ORDERS METRICS
    if is_admin or is_invoice or is_buyer:
        orders = Order.objects.all()
    else:
        # For regular reps, show only their orders
        orders = Order.objects.filter(rep=user)

    # General order metrics
    total_orders = orders.count()
    orders_last_30_days = orders.filter(created_at__gte=last_30_days).count()
    orders_by_status = orders.values("status").annotate(count=Count("id"))
    recent_orders = orders.order_by("-created_at")[:5]

    # Filter orders to current month for value calculation
    current_month_orders = orders.filter(
        created_at__gte=first_day_of_month, created_at__lte=last_day_of_month
    )

    # Add current month to context
    current_month_name = first_day_of_month.strftime("%B %Y")

    # Get recent quotes
    recent_quotes = quotes.order_by("-created_at")[:5]

    # Import OrderItem model directly
    order_items = OrderItem.objects.filter(order__in=orders)

    # Print the number of items found for debugging
    print(f"Total orders for {'all users' if is_admin else 'rep'}: {orders.count()}")
    print(f"Found {order_items.count()} total order items")

    # Enhanced debugging for order value calculation
    print("\n===== DETAILED ORDER VALUE CALCULATION =====")
    print(f"User: {user.username}, Is Admin: {is_admin}")

    # Track values by order
    order_values = {}
    item_count = 0

    # Group by orders for easier verification
    for order in orders:
        order_total = 0
        order_items = OrderItem.objects.filter(order=order)

        print(f"\nOrder #{order.order_number} (ID: {order.id}):")
        print(f"  - Date: {order.created_at}")
        print(f"  - Status: {order.status}")
        print(f"  - Customer: {order.company}")

        # Calculate items for this order
        for item in order_items:
            try:
                selling_price = float(item.selling_price or 0)
                quantity = int(item.quantity or 0)
                item_total = selling_price * quantity

                print(
                    f"  - Item #{item.id}: '{item.description[:30]}...' - {quantity} × ${selling_price:.2f} = ${item_total:.2f}"
                )

                order_total += item_total
                item_count += 1
            except (ValueError, TypeError) as e:
                print(f"  - ERROR with item {item.id}: {e}")

        # Store order total
        order_values[order.id] = order_total
        print(f"  Order total: ${order_total:.2f}")

    # Calculate overall totals
    total_order_value = sum(order_values.values())

    # Print summary
    print("\n===== ORDER VALUE SUMMARY =====")
    print(f"Total orders processed: {len(order_values)}")
    print(f"Total items processed: {item_count}")
    print(f"Total value: ${total_order_value:.2f}")

    # If current month calculation is needed, do the same for current month orders
    current_month_value = 0
    current_month_item_count = 0

    print("\n===== CURRENT MONTH ORDER VALUE CALCULATION =====")
    print(f"Month: {current_month_name}")

    for order in current_month_orders:
        order_total = 0
        order_items = OrderItem.objects.filter(order=order)

        print(f"\nMonth Order #{order.order_number} (ID: {order.id}):")

        # Calculate items for this order
        for item in order_items:
            try:
                selling_price = float(item.selling_price or 0)
                quantity = int(item.quantity or 0)
                item_total = selling_price * quantity

                print(
                    f"  - Item #{item.id}: {quantity} × ${selling_price:.2f} = ${item_total:.2f}"
                )

                order_total += item_total
                current_month_item_count += 1
            except (ValueError, TypeError) as e:
                print(f"  - ERROR with item {item.id}: {e}")

        current_month_value += order_total
        print(f"  Order total: ${order_total:.2f}")

    print(f"\nCurrent month total ({current_month_name}): ${current_month_value:.2f}")
    print(f"Current month items: {current_month_item_count}")

    # Query quotes pending approval
    if is_admin or is_quoter or is_buyer:
        # Admin, quoters, and buyers see all pending quotes
        pending_approval_quotes = QuoteRequest.objects.filter(
            status="approval_pending", pdf_file__isnull=False
        ).order_by("-pdf_generated_at")[
            :5
        ]  # Get the 5 most recent
    else:
        # Regular reps only see their own quotes pending approval
        pending_approval_quotes = QuoteRequest.objects.filter(
            rep=request.user, status="approval_pending", pdf_file__isnull=False
        ).order_by("-pdf_generated_at")[
            :5
        ]  # Get the 5 most recent

    # Create the context dictionary
    context = {
        "total_quotes": total_quotes,
        "quotes_last_30_days": quotes_last_30_days,
        "quotes_today": quotes_today,
        "quote_status_counts": quote_status_counts,
        "total_customers": total_customers,
        "new_customers_30_days": new_customers_30_days,
        "total_orders": total_orders,
        "orders_last_30_days": orders_last_30_days,
        "orders_by_status": orders_by_status,
        "recent_quotes": recent_quotes,
        "recent_orders": recent_orders,
        "segment": "dashboard",
        "title": "Sales Dashboard",
        "is_admin": is_admin,
        "is_rep": not can_view_all,
        "total_order_value": total_order_value,
        "current_month_value": current_month_value,
        "current_month": current_month_name,
        "pending_approval_quotes": pending_approval_quotes,  # Add the pending approval quotes here
    }

    return render(request, "dashboard/rep_dashboard.html", context)


@login_required
def rep_dashboard_detail(request, user_id=None):
    """Displays a detailed dashboard for a Sales Representative."""
    target_user = None
    if user_id:
        if (
            not request.user.is_superuser
            and not request.user.groups.filter(name="ADMIN").exists()
        ):
            return redirect("dashboard:rep_dashboard_detail")
        target_user = get_object_or_404(User, pk=user_id, groups__name="REP")
    else:
        target_user = request.user
        if not target_user.groups.filter(name="REP").exists():
            return redirect("dashboard:index")

    rep_user = target_user

    # --- Base Querysets ---
    # Quotes directly linked to the rep
    rep_quotes = QuoteRequest.objects.filter(rep=rep_user).select_related("customer")

    # Orders directly linked to the rep
    rep_orders = Order.objects.filter(rep=rep_user).select_related(
        "quote", "company"
    )  # Filter directly on Order.rep

    # --- UPDATE: Filter items based on orders directly linked to the rep ---
    rep_order_items = OrderItem.objects.filter(order__rep=rep_user).select_related(
        "order", "supplier"
    )
    # --- END UPDATE ---

    # --- Quote Stats (Should be correct as it uses rep_quotes) ---
    total_quotes_count = rep_quotes.count()
    monthly_quotes_raw = (
        rep_quotes.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    )

    quotes_by_customer_raw = (
        rep_quotes.values("customer__company")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # --- Order & Financial Stats (Now uses the updated rep_order_items) ---
    total_orders_count = rep_orders.count()  # Count orders directly linked to rep

    # Aggregate financials from order items linked via order__rep
    financial_aggregates = rep_order_items.aggregate(
        total_value=Coalesce(
            Sum(F("selling_price") * F("quantity")),
            Decimal("0.0"),
            output_field=DecimalField(),
        ),
        total_cost=Coalesce(
            Sum(F("cost_price") * F("quantity")),
            Decimal("0.0"),
            output_field=DecimalField(),
        ),
    )
    total_value = financial_aggregates["total_value"]
    total_cost = financial_aggregates["total_cost"]

    overall_markup_value = total_value - total_cost
    overall_markup_percentage = (
        (overall_markup_value / total_cost * 100) if total_cost else Decimal("0.0")
    )

    # --- Monthly & Yearly Profitability (Uses updated rep_order_items) ---
    profitability_base_qs = rep_order_items.filter(order__created_at__isnull=False)

    monthly_profitability_raw = (
        profitability_base_qs.annotate(month=TruncMonth("order__created_at"))
        .values("month")
        .annotate(
            monthly_value=Coalesce(
                Sum(F("selling_price") * F("quantity")), Decimal("0.0")
            ),
            monthly_cost=Coalesce(Sum(F("cost_price") * F("quantity")), Decimal("0.0")),
        )
        .order_by("month")
    )

    yearly_profitability_raw = (
        profitability_base_qs.annotate(year=TruncYear("order__created_at"))
        .values("year")
        .annotate(
            yearly_value=Coalesce(
                Sum(F("selling_price") * F("quantity")), Decimal("0.0")
            ),
            yearly_cost=Coalesce(Sum(F("cost_price") * F("quantity")), Decimal("0.0")),
        )
        .order_by("year")
    )

    # --- Process Data for Charts/Template ---
    monthly_quotes_chart_labels = [
        m["month"].strftime("%Y-%m") for m in monthly_quotes_raw if m["month"]
    ]
    monthly_quotes_chart_data = [m["count"] for m in monthly_quotes_raw if m["month"]]

    quotes_by_customer_chart_labels = [
        (c["customer__company"] or "Unknown Customer")
        for c in quotes_by_customer_raw[:10]
    ]
    quotes_by_customer_chart_data = [c["count"] for c in quotes_by_customer_raw[:10]]

    monthly_profit_chart_labels = []
    monthly_profit_chart_value = []
    monthly_profit_chart_cost = []
    monthly_profitability_table = []
    for m in monthly_profitability_raw:
        if not m["month"]:
            continue
        month_str = m["month"].strftime("%Y-%m")
        value = m["monthly_value"]
        cost = m["monthly_cost"]
        markup_val = value - cost
        markup_pct = (markup_val / cost * 100) if cost else Decimal("0.0")

        monthly_profit_chart_labels.append(month_str)
        monthly_profit_chart_value.append(
            float(value)
        )  # Keep float conversion for Chart.js
        monthly_profit_chart_cost.append(float(cost))  # Keep float conversion
        monthly_profitability_table.append(
            {
                "month": month_str,
                "value": value,
                "cost": cost,
                "markup_value": markup_val,
                "markup_percentage": markup_pct,
            }
        )

    yearly_profitability_table = []
    for y in yearly_profitability_raw:
        if not y["year"]:
            continue
        year_str = y["year"].strftime("%Y")
        value = y["yearly_value"]
        cost = y["yearly_cost"]
        markup_val = value - cost
        markup_pct = (markup_val / cost * 100) if cost else Decimal("0.0")
        yearly_profitability_table.append(
            {
                "year": year_str,
                "value": value,
                "cost": cost,
                "markup_value": markup_val,
                "markup_percentage": markup_pct,
            }
        )

    context = {
        "rep_user": rep_user,
        "page_title": f"Dashboard Detail for {rep_user.first_name or rep_user.username}",
        "segment": "rep_dashboard_detail",
        # Overall Stats
        "total_quotes_count": total_quotes_count,
        "total_orders_count": total_orders_count,
        "total_value": total_value,
        "total_cost": total_cost,
        "overall_markup_value": overall_markup_value,
        "overall_markup_percentage": overall_markup_percentage,
        # Data for Tables
        "monthly_profitability_table": monthly_profitability_table,
        "yearly_profitability_table": yearly_profitability_table,
        "quotes_by_customer_list": quotes_by_customer_raw,
        # Data for Charts
        "monthly_quotes_chart_labels": monthly_quotes_chart_labels,
        "monthly_quotes_chart_data": monthly_quotes_chart_data,
        "quotes_by_customer_chart_labels": quotes_by_customer_chart_labels,
        "quotes_by_customer_chart_data": quotes_by_customer_chart_data,
        "monthly_profit_chart_labels": monthly_profit_chart_labels,
        "monthly_profit_chart_value": monthly_profit_chart_value,
        "monthly_profit_chart_cost": monthly_profit_chart_cost,
    }
    return render(request, "dashboard/rep_dashboard_detail.html", context)


@login_required
def customer_dashboard(request, customer_id):
    """Displays a dashboard with details, stats, quotes, orders, and items for a specific customer."""
    customer = get_object_or_404(Customers, pk=customer_id)

    # --- Data Fetching ---
    # Get all quotes for this customer
    quotes = QuoteRequest.objects.filter(customer=customer).order_by("-created_at")

    # Get all orders linked to this customer's quotes
    orders = (
        Order.objects.filter(quote__customer=customer)
        .select_related("quote", "company")
        .order_by("-created_at")
    )

    # Get all order items related to those orders
    order_items = (
        OrderItem.objects.filter(order__in=orders)
        .select_related("order", "order__quote")
        .order_by("order__created_at", "id")
    )

    # --- Stats Calculation ---
    total_quotes = quotes.count()
    quote_status_counts = (
        quotes.values("status").annotate(count=Count("id")).order_by("status")
    )

    total_orders = orders.count()
    order_status_counts = (
        orders.values("status").annotate(count=Count("id")).order_by("status")
    )

    total_order_items = order_items.count()

    # Calculate total value of order items (handle potential None values)
    # Assumes selling_price and quantity can be converted to numbers
    total_order_value = order_items.aggregate(
        total_value=Coalesce(
            Sum(
                F("selling_price") * F("quantity"),
                output_field=DecimalField(),  # Specify output field type
            ),
            0.0,  # Default value if sum is None
            output_field=DecimalField(),
        )
    )["total_value"]

    context = {
        "customer": customer,
        "page_title": f"Dashboard for {customer.customer}",
        "segment": "customer_dashboard",  # For navigation highlighting
        # Stats
        "total_quotes": total_quotes,
        "quote_status_counts": {
            item["status"]: item["count"] for item in quote_status_counts
        },  # Convert to dict for easier template access
        "total_orders": total_orders,
        "order_status_counts": {
            item["status"]: item["count"] for item in order_status_counts
        },  # Convert to dict
        "total_order_items": total_order_items,
        "total_order_value": total_order_value,
        # Data Lists
        "quotes_list": quotes,
        "orders_list": orders,
        "order_items_list": order_items,
    }
    return render(request, "dashboard/customer_dashboard.html", context)


@login_required
def supplier_dashboard(request, supplier_id):
    """Displays a dashboard with details, stats, and related items for a specific supplier."""
    supplier = get_object_or_404(Suppliers, pk=supplier_id)

    # --- Data Fetching ---
    # Get all order items from this supplier
    supplier_items = OrderItem.objects.filter(supplier=supplier).select_related(
        "order", "order__quote", "order__company"
    )

    # Items on completed orders for purchase value calculation
    completed_items = supplier_items.filter(order__status="completed")

    # Outstanding items (not yet delivered)
    outstanding_items = supplier_items.exclude(item_status="delivered").order_by(
        "order__created_at", "id"
    )

    # Related quotes (via orders linked to items from this supplier)
    related_quotes = (
        QuoteRequest.objects.filter(related_orders__items__supplier=supplier)
        .select_related("customer")
        .distinct()
        .order_by("-created_at")
    )

    # --- Stats Calculation ---
    # Total Purchased Value (from completed orders)
    total_purchased_value = completed_items.aggregate(
        total_value=Coalesce(
            Sum(F("cost_price") * F("quantity"), output_field=DecimalField()),
            Decimal("0.0"),  # Use Decimal for default
            output_field=DecimalField(),
        )
    )["total_value"]

    # Outstanding Items Count
    outstanding_items_count = outstanding_items.count()

    # --- Monthly/Yearly Totals (Based on Order creation date of completed items) ---
    monthly_totals_raw = (
        completed_items.annotate(month=TruncMonth("order__created_at"))
        .values("month")
        .annotate(total=Sum(F("cost_price") * F("quantity")))
        .order_by("month")
    )

    yearly_totals_raw = (
        completed_items.annotate(year=TruncYear("order__created_at"))
        .values("year")
        .annotate(total=Sum(F("cost_price") * F("quantity")))
        .order_by("year")
    )

    # Process totals for easier template display (optional, can be done in template)
    monthly_totals = {
        item["month"].strftime("%Y-%m"): item["total"]
        for item in monthly_totals_raw
        if item["month"] and item["total"] is not None  # Added check for None
    }
    yearly_totals = {
        item["year"].strftime("%Y"): item["total"]
        for item in yearly_totals_raw
        if item["year"] and item["total"] is not None  # Added check for None
    }

    context = {
        "supplier": supplier,
        "page_title": f"Dashboard for {supplier.suppliername}",
        "segment": "supplier_dashboard",  # For navigation highlighting
        # Stats
        "total_purchased_value": total_purchased_value,
        "outstanding_items_count": outstanding_items_count,
        "monthly_totals": monthly_totals,
        "yearly_totals": yearly_totals,
        # Data Lists
        "outstanding_items_list": outstanding_items,
        "related_quotes_list": related_quotes,
    }
    return render(request, "dashboard/supplier_dashboard.html", context)


@login_required
def company_dashboard(request, company_id):
    """Displays a dashboard with details and activity for a specific Company."""
    company = get_object_or_404(Company, pk=company_id)

    # --- Base Querysets ---
    company_orders = (
        Order.objects.filter(company=company)
        .select_related("rep", "quote", "quote__customer")
        .prefetch_related("items")  # Use the correct related_name 'items'
        .order_by("-created_at")
    )
    company_order_items = (
        OrderItem.objects.filter(order__company=company)
        .select_related("order", "order__rep", "supplier")  # Added order__rep
        .order_by("-order__created_at")  # Order by parent order date
    )
    company_customers = Customers.objects.filter(company=company)
    company_quotes = (
        QuoteRequest.objects.filter(customer__company=company)
        .select_related("customer", "rep")
        .prefetch_related("items")  # Use the correct related_name (e.g., 'items')
        .order_by("-created_at")
    )
    company_delivery_notes = (
        DeliveryNote.objects.filter(company=company)
        .select_related("created_by", "delivered_by")  # Select users
        .prefetch_related("items")  # Needed for has_all_items_priced check efficiently
        .order_by("-delivery_date", "-created_at")  # Order by date
    )

    # --- Stats Calculation ---
    total_orders = company_orders.count()
    total_quotes = company_quotes.count()
    total_customers = company_customers.count()
    total_order_items = company_order_items.count()
    total_delivery_notes = company_delivery_notes.count()

    # Total Order Value
    total_order_value = company_order_items.aggregate(
        total=Coalesce(
            Sum(F("selling_price") * F("quantity")),
            Decimal("0.0"),
            output_field=DecimalField(),
        )
    )["total"]

    # Order Status Distribution
    order_status_counts_raw = (
        company_orders.values("status").annotate(count=Count("id")).order_by("-count")
    )
    order_status_counts = {
        item["status"]: item["count"] for item in order_status_counts_raw
    }

    # Quote Status Distribution
    quote_status_counts_raw = (
        company_quotes.values("status").annotate(count=Count("id")).order_by("-count")
    )
    quote_status_counts = {
        item["status"]: item["count"] for item in quote_status_counts_raw
    }

    # --- Monthly Order Value (for Chart) ---
    monthly_value_raw = (
        company_order_items.filter(order__created_at__isnull=False)
        .annotate(month=TruncMonth("order__created_at"))
        .values("month")
        .annotate(
            total_value=Coalesce(
                Sum(F("selling_price") * F("quantity")), Decimal("0.0")
            )
        )
        .order_by("month")
    )

    monthly_value_labels = [
        m["month"].strftime("%Y-%m") for m in monthly_value_raw if m["month"]
    ]
    monthly_value_data = [
        float(m["total_value"]) for m in monthly_value_raw if m["month"]
    ]  # Use float for Chart.js

    # --- Data for Tables (Limit for display) ---
    recent_orders = company_orders[:10]
    recent_quotes = company_quotes[:10]
    recent_delivery_notes = company_delivery_notes[:10]
    recent_order_items = company_order_items[:15]  # Show a few more items

    context = {
        "company": company,
        "page_title": f"Dashboard for {company.company}",  # Use company.company
        "segment": "company_dashboard",
        # Stats
        "total_orders": total_orders,
        "total_quotes": total_quotes,
        "total_customers": total_customers,
        "total_order_items": total_order_items,
        "total_order_value": total_order_value,
        "order_status_counts": order_status_counts,
        "quote_status_counts": quote_status_counts,
        "total_delivery_notes": total_delivery_notes,
        # Data Lists for Tables
        "recent_orders_list": recent_orders,
        "recent_quotes_list": recent_quotes,
        "customers_list": company_customers,
        "recent_delivery_notes_list": recent_delivery_notes,
        "recent_order_items_list": recent_order_items,
        # Chart Data (using json_script method)
        "monthly_value_labels": monthly_value_labels,
        "monthly_value_data": monthly_value_data,
        "order_status_labels": list(order_status_counts.keys()),
        "order_status_data": list(order_status_counts.values()),
    }
    return render(request, "dashboard/company_dashboard.html", context)


def test_notifications_view(request):
    """View for testing PWA notifications"""
    return render(request, "test_notifications.html")


@csrf_exempt  # Only for testing - use proper CSRF in production
def send_test_notification(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            title = data.get("title")
            body = data.get("body")
            url = data.get("url")

            # In a real implementation, you would fetch subscription info from your database
            # This is a simplified example assuming you have a push service set up

            # Example using web-push library (you'd need to install this)
            # Replace with your actual push service implementation
            push_service_url = "https://fcm.googleapis.com/fcm/send"  # Example URL

            # Get the user's subscription from your database
            # subscription = UserSubscription.objects.get(user=request.user).subscription_data

            # For testing, we'll just log that we would send a notification
            print(f"Would send notification: {title} - {body}")

            # Simulate successful push
            return JsonResponse(
                {"success": True, "message": "Push notification sent (simulated)"}
            )

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Only POST method is supported"})
