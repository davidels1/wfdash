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
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('picked', 'Picked'),  # After ready_to_pick
        ('loading', 'Loading'),  # New status for delivery pick list
        ('ready_for_delivery', 'Ready for Delivery'),
        ('delivered', 'Delivered')
    ]

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE)
    received_date = models.DateField(auto_now_add=True)
    received_qty = models.DecimalField(max_digits=10, decimal_places=2)
    invoice_number = models.CharField(max_length=50, blank=True, null=True)
    invoice_date = models.DateField(null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    delivery_note = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='in_stock'
    )
    notes = models.TextField(blank=True, null=True)
    verified_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='verified_stock'
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
        related_name='picked_items'
    )
    picked_date = models.DateTimeField(null=True, blank=True)
    loaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loaded_items'
    )
    loaded_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.order_item.description} - {self.received_qty}"

    def save(self, *args, **kwargs):
        if self.status == 'delivered':
            # Update order item status
            self.order_item.item_status = 'delivered'
            self.order_item.save()
            
            # Check if all items in order are delivered
            order = self.order_item.order
            all_delivered = all(
                item.item_status == 'delivered' 
                for item in order.items.all()
            )
            if all_delivered:
                order.status = 'completed'
                order.save()
                
        super().save(*args, **kwargs)