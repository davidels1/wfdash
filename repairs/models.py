from django.db import models
from django.conf import settings
from wfdash.models import Suppliers, Customers

class Repair(models.Model):
    STATUS_CHOICES = (
        ('received', 'Received'),
        ('sent_for_quote', 'Sent for Strip & Quote'),
        ('quote_received', 'Quote Received'),
        ('quote_sent', 'Quote Sent to Customer'),
        ('quote_approved', 'Quote Approved'),
        ('repair_ordered', 'Repair Ordered'),
        ('repair_in_progress', 'Repair in Progress'),
        ('repaired', 'Repaired'),
        ('returned', 'Returned to Customer'),
        ('cancelled', 'Cancelled'),
    )
    
    repair_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(Customers, on_delete=models.CASCADE)
    supplier = models.ForeignKey(Suppliers, on_delete=models.CASCADE, blank=True, null=True)
    item_description = models.TextField()
    serial_number = models.CharField(max_length=100, blank=True, null=True)
    problem_description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received')
    received_date = models.DateField(auto_now_add=True)
    sent_for_quote_date = models.DateField(blank=True, null=True)
    quote_received_date = models.DateField(blank=True, null=True)
    quote_sent_date = models.DateField(blank=True, null=True)
    quote_approved_date = models.DateField(blank=True, null=True)
    repair_ordered_date = models.DateField(blank=True, null=True)
    expected_completion_date = models.DateField(blank=True, null=True)
    completed_date = models.DateField(blank=True, null=True)
    returned_date = models.DateField(blank=True, null=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_repairs')
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Repair #{self.repair_number} - {self.customer}"
    
    class Meta:
        ordering = ['-received_date']


class RepairPhoto(models.Model):
    repair = models.ForeignKey(Repair, on_delete=models.CASCADE, related_name='photos')
    photo = models.ImageField(upload_to='repair_photos/%Y/%m/')
    description = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Photo for {self.repair.repair_number}"


class RepairQuote(models.Model):
    repair = models.ForeignKey(Repair, on_delete=models.CASCADE, related_name='quotes')
    quote_number = models.CharField(max_length=50)
    quote_date = models.DateField()
    supplier_quote_amount = models.DecimalField(max_digits=10, decimal_places=2)
    customer_quote_amount = models.DecimalField(max_digits=10, decimal_places=2)
    markup_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=20.00)
    approved = models.BooleanField(default=False)
    approved_date = models.DateField(blank=True, null=True)
    pdf_file = models.FileField(upload_to='repair_quotes/%Y/%m/', blank=True, null=True)
    
    def __str__(self):
        return f"Quote #{self.quote_number} for {self.repair.repair_number}"


class RepairOrder(models.Model):
    STATUS_CHOICES = (
        ('ordered', 'Ordered'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    )
    
    repair = models.ForeignKey(Repair, on_delete=models.CASCADE, related_name='orders')
    order_number = models.CharField(max_length=50)
    order_date = models.DateField(auto_now_add=True)
    supplier = models.ForeignKey(Suppliers, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ordered')
    expected_completion_date = models.DateField(blank=True, null=True)
    actual_completion_date = models.DateField(blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)
    
    def __str__(self):
        return f"Order #{self.order_number} for {self.repair.repair_number}"
