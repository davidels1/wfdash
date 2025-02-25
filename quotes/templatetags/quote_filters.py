from django import template

register = template.Library()

@register.filter(name='multiply')
def multiply(value, arg):
    try:
        return float(value or 0) * float(arg or 0)
    except (ValueError, TypeError):
        return 0