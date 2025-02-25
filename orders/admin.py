from django.contrib import admin
from .models import Order, OrderItem, PurchaseOrder, CompanyDetails

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'company', 'rep', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('order_number', 'company__company')
    date_hierarchy = 'created_at'

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'description', 'quantity', 'selling_price')
    list_filter = ('order__status',)
    search_fields = ('description', 'order__order_number')

@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('po_number', 'order', 'supplier', 'status', 'total_amount')
    list_filter = ('status', 'created_at')
    search_fields = ('po_number', 'order__order_number')
    date_hierarchy = 'created_at'

@admin.register(CompanyDetails)
class CompanyDetailsAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'vat_number')
