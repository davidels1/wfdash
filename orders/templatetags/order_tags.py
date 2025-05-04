from django import template
from decimal import Decimal

register = template.Library()


@register.simple_tag
def count_items_by_status(items, status):
    return len([item for item in items if item.item_status == status])


@register.simple_tag
def calculate_progress(items):
    total = len(items)
    if total == 0:
        return 0
    delivered = len([item for item in items if item.item_status == "delivered"])
    return int((delivered / total) * 100)


# Add these new template tags
@register.simple_tag
def count_pending_items(order):
    """Count items with pending status in an order"""
    return order.items.filter(item_status="pending").count()


@register.simple_tag
def count_delivered_items(order):
    """Count items with delivered status in an order"""
    return order.items.filter(item_status="delivered").count()


@register.simple_tag
def count_total_items(order):
    """Count total items in an order"""
    return order.items.count()


@register.simple_tag
def calculate_percentage(part, whole):
    """Calculate percentage safely"""
    if whole == 0:
        return 0
    return int((part / whole) * 100)


# Keep your existing filters
@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary safely, handling non-dictionary inputs"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""


@register.filter
def intdiv(value, arg):
    """Integer division filter"""
    try:
        return int(int(value) / int(arg))
    except (ValueError, ZeroDivisionError):
        return 0


@register.filter
def divide_by(value, arg):
    """Divides the value by the argument"""
    try:
        return int(float(value) / float(arg))
    except (ValueError, ZeroDivisionError):
        return value


@register.filter
def subtract(value, arg):
    return value - arg


@register.filter
def multiply(value, arg):
    return value * arg


@register.simple_tag
def get_all_items_from_orders(orders):
    """Gets all order items from a list of orders"""
    all_items = []
    for order in orders:
        all_items.extend(list(order.items.all()))
    return all_items


@register.simple_tag
def count_items_with_status(items, status):
    """Counts items with a specific status"""
    return sum(1 for item in items if item.item_status == status)


@register.filter
def slugify(value):
    """Convert value to slug format (lowercase, hyphens)"""
    return value.lower().replace(" ", "-").replace("_", "-")


@register.filter
def is_breakdown_order(order):
    """Check if an order is a breakdown order"""
    if not order:
        return False
    if hasattr(order, "order_number"):
        return order.order_number and "breakdown" in order.order_number.lower()
    return False


@register.simple_tag
def breakdown_badge():
    """Return HTML for breakdown badge"""
    return '<span class="breakdown-badge"><i class="fas fa-tools"></i> BREAKDOWN</span>'


# Add this filter
@register.filter
def percentage(value, total):
    """Calculate what percentage value is of total"""
    try:
        if total == 0:
            return 0
        return int((value / total) * 100)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0


@register.simple_tag
def get_order_status_display(order):
    """Get display status for an order with priority for pending items"""
    # Check for pending items first
    if order.items.filter(item_status="pending").exists():
        return "Pending Items"

    # Then check standard status logic
    return order.get_status_display()


@register.simple_tag
def get_order_status_color(order):
    """Get status color class with priority for pending items"""
    # If any pending items exist, use warning color
    if order.items.filter(item_status="pending").exists():
        return "warning"

    # Otherwise use standard color mapping
    status_colors = {
        "new": "primary",
        "processing": "info",
        "order_ready": "secondary",
        "po_generated": "purple",
        "completed": "success",
        "cancelled": "danger",
    }
    return status_colors.get(order.status, "secondary")


@register.filter
def item_status_color(status):
    """Return a specific color class for each item status"""
    status_colors = {
        "pending": "warning",  # Yellow
        "delivered": "success",  # Green
        "collected": "info",  # Light blue
        "processed": "primary",  # Blue
        "po_generated": "purple",  # Purple
        "assigned": "dark",  # Dark gray
    }
    return status_colors.get(status, "secondary")  # Default to secondary
