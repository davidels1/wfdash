def menu_permissions(request):
    """Adds menu visibility flags to template context"""
    user = request.user
    is_rep = user.groups.filter(name='REP').exists()  # Changed 'Rep' to 'REP'

    return {
        'menu_perms': {
            'is_rep': is_rep,
            'can_view_quotes': user.has_perm('quotes.view_quoterequest'),
            'can_view_orders': user.has_perm('orders.view_order'),
            'can_view_collections': user.has_perm('driver_list.view_collection'),
            'can_view_stock': user.has_perm('stock_management.view_stockitem'),
        }
    }