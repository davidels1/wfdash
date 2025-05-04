from django.db import models
from django.conf import settings
from orders.models import OrderItem, PurchaseOrder
from wfdash.models import Suppliers
from django.core.validators import MinValueValidator
from django.utils import timezone

class Collection(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('assigned', 'Assigned'),  # Make sure this matches the status in assign_driver
        ('collected', 'Collected'),
        ('problem', 'Problem')
    ]

    order_item = models.ForeignKey('orders.OrderItem', on_delete=models.CASCADE, null=True, blank=True)  # Make optional
    supplier = models.ForeignKey('wfdash.Suppliers', on_delete=models.CASCADE)
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    planned_date = models.DateField(null=True, blank=True)
    actual_date = models.DateField(null=True, blank=True)
    received_qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # New fields for manual collections
    is_manual = models.BooleanField(default=False)
    description = models.CharField(max_length=255, blank=True, null=True)
    unit = models.CharField(max_length=20, blank=True, null=True, default='units')

    # Add new fields for stock orders
    stock_order = models.ForeignKey('stock_orders.StockOrder', null=True, blank=True, 
                                   on_delete=models.CASCADE, related_name='collections')
    stock_item = models.ForeignKey('stock_orders.StockOrderItem', null=True, blank=True,
                                   on_delete=models.CASCADE, related_name='collections')

    class Meta:
        ordering = ['supplier', 'planned_date']
        verbose_name = 'Collection'
        verbose_name_plural = 'Collections'

    def __str__(self):
        if self.order_item:
            return f"{self.order_item} - {self.supplier}"
        elif self.stock_item:
            return f"{self.stock_item.description} - {self.supplier}"
        else:
            return f"{self.description or 'Manual entry'} - {self.supplier}"

    def assign_driver(self, driver, planned_date):
        self.driver = driver
        self.planned_date = planned_date
        self.status = 'assigned'
        self.save()

    def save(self, *args, **kwargs):
        # Store previous status if this is an existing collection
        old_status = None
        if self.pk:
            old_status = Collection.objects.get(pk=self.pk).status
        
        # Call the original save method
        super().save(*args, **kwargs)
        
        # Update OrderItem status if there's a change and we have an order_item
        if self.order_item and (old_status != self.status or not old_status):
            # Map collection status to OrderItem status
            status_mapping = {
                'pending': 'driver_pool',
                'assigned': 'assigned',
                'collected': 'collected',
                'problem': 'driver_pool'  # Or another appropriate status
            }
            
            # Only update if the new status represents forward progress
            if self.status in status_mapping:
                new_status = status_mapping[self.status]
                
                # Don't downgrade status if already further along
                further_statuses = ['stock_verified', 'picking', 'ready_delivery', 'delivered']
                if self.order_item.item_status not in further_statuses:
                    self.order_item.item_status = new_status
                    self.order_item.save(update_fields=['item_status'])

class CollectionProblem(models.Model):
    PROBLEM_TYPES = [
        ('out_of_stock', 'Out of Stock'),
        ('partial_stock', 'Partial Stock'),
        ('quality_issue', 'Quality Issue'),
        ('wrong_item', 'Wrong Item'),
        ('other', 'Other')
    ]

    collection = models.ForeignKey(Collection, on_delete=models.CASCADE)
    problem_type = models.CharField(max_length=20, choices=PROBLEM_TYPES)
    description = models.TextField()
    photo = models.ImageField(upload_to='collection_problems/', null=True, blank=True)
    reported_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Problem Report - Collection {self.collection.id}"

class DriverListPool(models.Model):
    order = models.ForeignKey('orders.Order', null=True, blank=True, on_delete=models.CASCADE, related_name='driver_list_entries')
    purchase_order = models.ForeignKey('orders.PurchaseOrder', null=True, blank=True, on_delete=models.CASCADE, related_name='driver_list_entries')
    item = models.ForeignKey('orders.OrderItem', null=True, blank=True, on_delete=models.CASCADE, related_name='driver_list_entries')
    supplier = models.ForeignKey('wfdash.Suppliers', on_delete=models.CASCADE)
    quantity = models.IntegerField()  # This will store the order_qty
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    # Add these fields for stock orders
    stock_order = models.ForeignKey('stock_orders.StockOrder', null=True, blank=True, on_delete=models.CASCADE, related_name='driver_list_entries')
    stock_item = models.ForeignKey('stock_orders.StockOrderItem', null=True, blank=True, on_delete=models.CASCADE, related_name='driver_list_entries')

    class Meta:
        verbose_name = 'Driver List Pool'
        verbose_name_plural = 'Driver List Pool'

    def __str__(self):
        if self.order and self.item:
            return f"{self.order.order_number} - {self.item.description}"
        elif self.stock_order and self.stock_item:
            return f"{self.stock_order.order_number} - {self.stock_item.description}"
        else:
            return f"Item for {self.supplier.suppliername}"

class Supplier(models.Model):
    suppliername = models.CharField(max_length=255)
    address = models.TextField(blank=True, null=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    # Other fields...
