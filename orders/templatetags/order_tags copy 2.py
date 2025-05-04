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
    delivered = len([item for item in items if item.item_status == 'delivered'])
    return int((delivered / total) * 100)

# Add these new template tags
@register.simple_tag
def count_pending_items(order):
    """Count items with pending status in an order"""
    return order.items.filter(item_status='pending').count()

@register.simple_tag
def count_delivered_items(order):
    """Count items with delivered status in an order"""
    return order.items.filter(item_status='delivered').count()

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
    return dictionary.get(key, '')

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

@register.filter
def get_all_items(orders):
    """Gets all order items from a list of orders"""
    all_items = []
    for order in orders:
        all_items.extend(order.items.all())
    return all_items

@register.filter
def count_items_with_status(items, status):
    """Counts items with a specific status"""
    return len([item for item in items if item.item_status == status])