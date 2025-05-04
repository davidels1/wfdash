from django import template

register = template.Library()

@register.filter
def filter_by_status(orders, status):
    """Filter a list of orders by status"""
    return [order for order in orders if order.status == status]