from django import template
from django.utils.safestring import mark_safe
from django.template.defaultfilters import floatformat

register = template.Library()


@register.filter
def calculate_total_deliveries(status_deliveries):
    """Calculate total delivery notes across all companies in a status"""
    total = 0
    for company, deliveries in status_deliveries.items():
        total += len(deliveries)
    return total


@register.filter
def calculate_total_value(status_deliveries):
    """Calculate total selling value of all items across all deliveries in a status"""
    total_value = 0
    for company, deliveries in status_deliveries.items():
        for delivery in deliveries:
            for item in delivery.items.all():
                if item.price is not None and item.quantity:
                    total_value += float(item.price) * item.quantity
    return total_value


@register.filter
def format_as_currency(value):
    """Format value as currency (R1,234.56)"""
    if value is None or value == 0:
        return "R0.00"
    formatted = floatformat(value, 2)
    parts = str(formatted).split(".")
    parts[0] = "{:,}".format(int(parts[0]))
    return f"R{parts[0]}.{parts[1] if len(parts) > 1 else '00'}"


@register.filter
def format_delivery_badge(status_deliveries):
    """Format badge with count and total value"""
    count = calculate_total_deliveries(status_deliveries)
    total = calculate_total_value(status_deliveries)

    return mark_safe(f"""
        <div class="d-flex flex-column align-items-center">
            <div>{count}</div>
            <div class="small">{format_as_currency(total)}</div>
        </div>
    """)
