from django.contrib import admin
from .models import StockItem

@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = (
        'order_item',
        'status',
        'received_qty',
        'invoice_number',
        'invoice_date',
        'picked',
        'picked_by'
    )
    list_filter = (
        'status',
        'picked',
        'invoice_date',
        'created_at'
    )
    search_fields = (
        'invoice_number',
        'order_item__description',
        'order_item__order__order_number'
    )
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('order_item', 'collection', 'status', 'notes')
        }),
        ('Stock Details', {
            'fields': ('received_qty', 'verified_quantity', 'verified_by')
        }),
        ('Invoice Information', {
            'fields': (
                'invoice_number',
                'invoice_date',
                'external_invoice_number',
                'external_invoice_date'
            )
        }),
        ('Picking Information', {
            'fields': ('picked', 'picked_by', 'picked_date')
        }),
        ('Loading Information', {
            'fields': ('loaded_by', 'loaded_date')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

    def has_delete_permission(self, request, obj=None):
        # Only allow deletion if user is superuser
        return request.user.is_superuser
