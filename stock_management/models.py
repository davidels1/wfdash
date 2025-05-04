from django.db import models

# Create your models here.
from django.db import models
from django.contrib.auth import get_user_model
from driver_list.models import Collection
from orders.models import Order, OrderItem
from decimal import Decimal

User = get_user_model()


class StockItem(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("verified", "Verified"),
        ("picked", "Picked"),  # After ready_to_pick
        ("loading", "Loading"),  # New status for delivery pick list
        ("ready_for_delivery", "Ready for Delivery"),
        ("delivered", "Delivered"),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="verified")
    delivered_in = models.ForeignKey(
        "delivery_notes.DeliveryNote",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_items",
    )

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.CASCADE,
        null=True,  # Allow null values
        blank=True,  # Allow blank in forms
    )
    received_date = models.DateField(auto_now_add=True)
    received_qty = models.DecimalField(max_digits=10, decimal_places=2)
    invoice_number = models.CharField(max_length=50, blank=True, null=True)
    invoice_date = models.DateField(null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    delivery_note = models.CharField(max_length=50, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="verified_stock"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    external_invoice_number = models.CharField(max_length=50)
    external_invoice_date = models.DateField()
    verified_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    picked = models.BooleanField(default=False)
    picked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="picked_items",
    )
    picked_date = models.DateTimeField(null=True, blank=True)
    loaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="loaded_items",
    )
    loaded_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.order_item.description} - {self.received_qty}"

    def save(self, *args, **kwargs):
        # Store old status if this is an existing object
        old_status = None
        if self.pk:
            old_status = StockItem.objects.get(pk=self.pk).status

        # Call the original save method
        super().save(*args, **kwargs)

        # Map StockItem status to OrderItem status
        status_mapping = {
            "pending": "stock_verified",  # Freshly added to stock
            "verified": "stock_verified",
            "picked": "picking",
            "loading": "ready_delivery",
            "ready_for_delivery": "ready_delivery",
            "delivered": "delivered",
        }

        # Only update if status has changed and there's a mapping
        if self.status in status_mapping and (
            not old_status or old_status != self.status
        ):
            new_status = status_mapping[self.status]

            # Only update if it represents forward progress
            current_status_index = next(
                (
                    i
                    for i, (code, _) in enumerate(self.order_item.ITEM_STATUS_CHOICES)
                    if code == self.order_item.item_status
                ),
                0,
            )
            new_status_index = next(
                (
                    i
                    for i, (code, _) in enumerate(self.order_item.ITEM_STATUS_CHOICES)
                    if code == new_status
                ),
                0,
            )

            # Update if new status represents progress in the workflow
            if new_status_index > current_status_index:
                self.order_item.item_status = new_status
                self.order_item.save(update_fields=["item_status"])

        if self.status == "delivered":
            # Update order item status
            self.order_item.item_status = "delivered"
            self.order_item.save()

            # Check if all items in order are delivered
            order = self.order_item.order
            all_delivered = all(
                item.item_status == "delivered" for item in order.items.all()
            )
            if all_delivered:
                order.status = "completed"
                order.save()
