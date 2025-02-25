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

    order_item = models.ForeignKey('orders.OrderItem', on_delete=models.CASCADE)
    supplier = models.ForeignKey('wfdash.Suppliers', on_delete=models.CASCADE)
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)  # Add this line
    planned_date = models.DateField(null=True, blank=True)
    actual_date = models.DateField(null=True, blank=True)
    received_qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['supplier', 'planned_date']
        verbose_name = 'Collection'
        verbose_name_plural = 'Collections'

    def __str__(self):
        return f"{self.order_item} - {self.supplier}"

    def assign_driver(self, driver, planned_date):
        self.driver = driver
        self.planned_date = planned_date
        self.status = 'assigned'
        self.save()

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
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE)
    purchase_order = models.ForeignKey('orders.PurchaseOrder', on_delete=models.CASCADE)
    item = models.ForeignKey('orders.OrderItem', on_delete=models.CASCADE)
    supplier = models.ForeignKey('wfdash.Suppliers', on_delete=models.CASCADE)
    quantity = models.IntegerField()  # This will store the order_qty
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Driver List Pool'
        verbose_name_plural = 'Driver List Pool'

    def __str__(self):
        return f"{self.order.order_number} - {self.item.description}"
