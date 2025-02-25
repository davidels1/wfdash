from django import template
from django.contrib.auth.models import Group

register = template.Library()

@register.filter(name='has_group')
def has_group(user, group_name):
    """Check if user belongs to a specific group"""
    try:
        return user.groups.filter(name=group_name).exists()
    except:
        return False

@register.simple_tag
def is_admin_user(user):
    """Check if user is superuser or in ADMIN group"""
    return user.is_superuser or user.groups.filter(name='ADMIN').exists()