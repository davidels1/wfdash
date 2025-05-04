from django.contrib import admin
from .models import DeliveryNote, DeliveryItem


class DeliveryItemInline(admin.TabularInline):
    model = DeliveryItem
    extra = 0
    fields = ["description", "quantity", "price", "notes"]


@admin.register(DeliveryNote)
class DeliveryNoteAdmin(admin.ModelAdmin):
    list_display = [
        "delivery_number",
        "company",
        "delivery_date",
        "status",
        "created_by",
        "created_at",
        "item_count",
    ]
    list_filter = ["status", "delivery_date", "created_at", "company"]
    search_fields = ["delivery_number", "company__company", "contact_person", "notes"]
    date_hierarchy = "created_at"
    readonly_fields = ["created_at", "updated_at", "converted_at"]
    inlines = [DeliveryItemInline]

    fieldsets = (
        (
            "Basic Information",
            {"fields": ("delivery_number", "company", "status", "delivery_date")},
        ),
        (
            "Contact Information",
            {
                "fields": (
                    "contact_person",
                    "contact_email",
                    "contact_phone",
                    "customer_order_number",
                )
            },
        ),
        (
            "Signature and Documentation",
            {
                "fields": (
                    "digital_signature",
                    "signed_by",
                    "signature_date",
                    "signed_document",
                )
            },
        ),
        ("Notes", {"fields": ("notes",)}),
        ("Generated Files", {"fields": ("pdf_file",)}),
        (
            "System Fields",
            {
                "classes": ("collapse",),
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                    "converted_to_quote",
                    "converted_at",
                ),
            },
        ),
    )

    def item_count(self, obj):
        return obj.items.count()

    item_count.short_description = "Items"


@admin.register(DeliveryItem)
class DeliveryItemAdmin(admin.ModelAdmin):
    list_display = ["delivery_note", "description", "quantity", "price", "item_total"]
    list_filter = ["delivery_note__status"]
    search_fields = ["description", "notes", "delivery_note__delivery_number"]

    def item_total(self, obj):
        if obj.price:
            return f"R{(obj.price * obj.quantity):.2f}"
        return "-"

    item_total.short_description = "Total"
