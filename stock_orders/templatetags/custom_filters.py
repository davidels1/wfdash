from django import template
from decimal import Decimal

register = template.Library()

@register.filter
def split(value, key):
    """Split a string into a list using the specified delimiter"""
    return value.split(key)

@register.filter
def strip(value):
    """Strip whitespace from a string"""
    return value.strip()

@register.filter
def multiply(value, arg):
    try:
        return Decimal(str(value)) * Decimal(str(arg))
    except:
        return 0