from django.contrib import admin
from .models import Collection

@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ['order_item', 'supplier', 'driver', 'status', 'created_at']
    list_filter = ['status', 'supplier', 'driver']
    search_fields = ['order_item__description', 'supplier__suppliername']
    raw_id_fields = ['order_item']
    autocomplete_fields = ['driver']
    readonly_fields = ['created_at', 'updated_at']