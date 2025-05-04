from django.contrib import admin
from .models import InternalStockItem, SupplierPriceList, PriceListItem


@admin.register(InternalStockItem)
class InternalStockItemAdmin(admin.ModelAdmin):
    list_display = (
        "part_number",
        "brand",
        "description",
        "supplier",
        "cost_price",
        "markup",
        "selling_price",
        "updated_at",
    )
    search_fields = ("part_number", "brand", "description")
    list_filter = ("supplier", "brand", "updated_at")
    fieldsets = (
        (None, {"fields": ("part_number", "brand", "description", "supplier")}),
        ("Pricing", {"fields": ("cost_price", "markup", "selling_price")}),
    )
    readonly_fields = ("created_at", "updated_at")


class PriceListItemInline(admin.TabularInline):
    model = PriceListItem
    extra = 0
    fields = [
        "part_number",
        "description",
        "brand",
        "cost_price",
        "markup",
        "selling_price",
    ]


@admin.register(SupplierPriceList)
class SupplierPriceListAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "supplier",
        "year",
        "valid_from",
        "valid_until",
        "default_markup",
    ]
    list_filter = ["supplier", "year"]
    search_fields = ["name", "supplier__suppliername"]
    inlines = [PriceListItemInline]


@admin.register(PriceListItem)
class PriceListItemAdmin(admin.ModelAdmin):
    list_display = [
        "description",
        "price_list",
        "cost_price",
        "markup",
        "selling_price",
    ]
    list_filter = ["price_list", "price_list__supplier"]
    search_fields = ["description", "part_number", "brand"]
