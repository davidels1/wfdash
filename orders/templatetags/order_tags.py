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