from django import template
from decimal import Decimal

register = template.Library()

@register.filter
def sub(value, arg):
    """Subtract the arg from the value."""
    try:
        return value - arg
    except (ValueError, TypeError):
        try:
            return Decimal(value) - Decimal(arg)
        except:
            return 0

@register.filter
def multiply(value, arg):
    """Multiply the value by the arg."""
    try:
        return value * arg
    except (ValueError, TypeError):
        try:
            return Decimal(value) * Decimal(arg)
        except:
            return 0
            
@register.filter
def percent_diff(value, arg):
    """Calculate percentage difference between value and arg."""
    try:
        if arg == 0:
            return 0
        return ((value - arg) / arg) * 100
    except (ValueError, TypeError, ZeroDivisionError):
        return 0
        
@register.simple_tag
def qty_status_class(received, ordered):
    """Return appropriate CSS class based on quantity difference."""
    try:
        if received > ordered:
            return "excess-qty"
        elif received < ordered:
            return "short-qty"
        else:
            return "match-qty"
    except (ValueError, TypeError):
        return ""

@register.simple_tag
def get_unique_order_numbers(items):
    """Return unique order numbers from a list of stock items."""
    order_numbers = set()
    for item in items:
        if hasattr(item, 'order_item') and hasattr(item.order_item, 'order'):
            order_numbers.add(item.order_item.order.order_number)
    return order_numbers