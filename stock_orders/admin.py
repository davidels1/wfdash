from django.contrib import admin
from .models import StockOrder, StockOrderItem, Supplier


class StockOrderItemInline(admin.TabularInline):
    model = StockOrderItem
    extra = 0


@admin.register(StockOrder)
class StockOrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "supplier", "status", "created_at", "driver")
    list_filter = ("status", "created_at", "supplier")
    search_fields = ("order_number", "supplier__name", "items__description")
    inlines = [StockOrderItemInline]
    readonly_fields = ("created_at", "updated_at", "assigned_at", "collected_at")

    # Explicitly enable actions including delete
    actions = ["delete_selected", "custom_delete_with_confirmation"]

    def has_delete_permission(self, request, obj=None):
        return True

    # Custom deletion action with confirmation
    def custom_delete_with_confirmation(self, request, queryset):
        """Delete stock orders with additional confirmation"""
        for order in queryset:
            order.delete()
        self.message_user(
            request, f"{queryset.count()} stock orders were successfully deleted."
        )

    custom_delete_with_confirmation.short_description = (
        "Delete selected stock orders (with confirmation)"
    )


@admin.register(StockOrderItem)
class StockOrderItemAdmin(admin.ModelAdmin):

    list_display = ("description", "quantity", "stock_order")
    search_fields = ("description",)
    list_filter = ("stock_order__status",)

    def has_delete_permission(self, request, obj=None):
        return True


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    # Update these field names to match your actual Supplier model fields
    list_display = ("name", "email", "phone")
    search_fields = ("name", "email", "phone")

    def has_delete_permission(self, request, obj=None):
        return True
