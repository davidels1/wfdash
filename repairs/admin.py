from django.contrib import admin
from .models import Repair, RepairPhoto, RepairQuote, RepairOrder

class RepairPhotoInline(admin.TabularInline):
    model = RepairPhoto
    extra = 1

class RepairQuoteInline(admin.TabularInline):
    model = RepairQuote
    extra = 1

class RepairOrderInline(admin.TabularInline):
    model = RepairOrder
    extra = 1

@admin.register(Repair)
class RepairAdmin(admin.ModelAdmin):
    list_display = ('repair_number', 'customer', 'item_description', 'status', 'received_date')
    list_filter = ('status', 'received_date', 'customer')
    search_fields = ('repair_number', 'item_description', 'customer__company')
    inlines = [RepairPhotoInline, RepairQuoteInline, RepairOrderInline]

@admin.register(RepairPhoto)
class RepairPhotoAdmin(admin.ModelAdmin):
    list_display = ('repair', 'description', 'uploaded_at')
    list_filter = ('uploaded_at',)

@admin.register(RepairQuote)
class RepairQuoteAdmin(admin.ModelAdmin):
    list_display = ('quote_number', 'repair', 'quote_date', 'supplier_quote_amount', 
                    'customer_quote_amount', 'approved')
    list_filter = ('approved', 'quote_date')
    search_fields = ('quote_number', 'repair__repair_number')

@admin.register(RepairOrder)
class RepairOrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'repair', 'supplier', 'status', 'order_date', 'expected_completion_date')
    list_filter = ('status', 'order_date')
    search_fields = ('order_number', 'repair__repair_number')
