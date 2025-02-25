from django.db import models
from django.conf import settings
from wfdash.models import Customers, Suppliers, Company
from quotes.models import QuoteRequest, QuoteItem
from django.utils import timezone
import uuid
from django.core.files.base import ContentFile
from decimal import Decimal
from django.core.validators import MinValueValidator

class Order(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('processing', 'Processing'),
        ('order_ready', 'Order Ready'),
        ('po_generated', 'PO Generated'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ]
    
    order_number = models.CharField(max_length=50)  # Customer's order number
    company = models.ForeignKey('wfdash.Company', on_delete=models.CASCADE)  # Changed from customer
    rep = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['order_number', 'company']  # Updated from customer to company

    def __str__(self):
        return f"Order #{self.order_number}"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def update_order_status(self):
        """
        Updates order status based on its items' statuses
        """
        items = self.items.all()
        
        if any(item.item_status == 'pending' for item in items):
            new_status = 'processing'
        elif all(item.item_status == 'processed' for item in items):
            new_status = 'order_ready'
        elif all(item.item_status == 'po_generated' for item in items):
            new_status = 'po_generated'
        else:
            new_status = 'new'
        
        if self.status != new_status:
            self.status = new_status
            self.save()

    def get_total_value(self):
        """Calculate total order value"""
        return sum(
            item.quantity * item.selling_price 
            for item in self.items.all()
        )

    def get_total_cost(self):
        """Calculate total order cost"""
        return sum(
            item.quantity * (item.cost_price or Decimal('0'))
            for item in self.items.all()
        )

class PurchaseOrder(models.Model):
    po_number = models.CharField(max_length=50, unique=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='purchase_orders')
    supplier = models.ForeignKey('wfdash.Suppliers', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default='draft')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    pdf_file = models.FileField(upload_to='purchase_orders/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.po_number

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.po_number:
            # Get company abbreviation
            company = CompanyDetails.objects.first()
            company_prefix = ''.join(word[0] for word in company.name.split()[:3]).upper() if company else 'PO'
            
            # Get today's date for the PO number
            today = timezone.now().strftime('%y%m')
            
            # Find last PO number for this prefix and month
            last_po = PurchaseOrder.objects.filter(
                po_number__startswith=f'{company_prefix}-{today}'
            ).order_by('-po_number').first()
            
            if last_po:
                last_number = int(last_po.po_number.split('-')[-1])
                next_number = str(last_number + 1).zfill(4)
            else:
                next_number = '0001'
            
            self.po_number = f'{company_prefix}-{today}-{next_number}'
        super().save(*args, **kwargs)

class OrderItem(models.Model):
    ITEM_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('po_generated', 'PO Generated'),
        ('driver_pool', 'In Driver Pool'),
        ('assigned', 'Assigned to Driver'),
        ('collected', 'Collected'),
        ('stock_verified', 'Stock Verified'),
        ('picking', 'Picking'),
        ('ready_delivery', 'Ready for Delivery'),
        ('delivered', 'Delivered')
    ]
    
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    description = models.CharField(max_length=255)
    quantity = models.IntegerField(default=1)  # Original quantity from order
    order_qty = models.IntegerField(null=True, blank=True)  # New field for PO quantity
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    supplier = models.ForeignKey(Suppliers, on_delete=models.SET_NULL, null=True, blank=True)
    cost_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    markup = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    purchase_order = models.ForeignKey('PurchaseOrder', on_delete=models.SET_NULL, null=True, blank=True)
    item_status = models.CharField(
        max_length=20,
        choices=ITEM_STATUS_CHOICES,
        default='pending'
    )
    notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        # Set order_qty to quantity if not set
        if self.order_qty is None:
            self.order_qty = self.quantity

        if self.cost_price and self.selling_price:
            # Calculate markup percentage
            self.markup = ((self.selling_price - self.cost_price) / self.cost_price) * 100
        
        # Update status only if cost_price and supplier are newly set
        if self.cost_price and self.supplier:
            if self.item_status == 'pending':
                self.item_status = 'processed'
        
        super().save(*args, **kwargs)
        self.update_order_status()

    def update_order_status(self):
        order = self.order
        items = order.items.all()
        
        if any(item.item_status == 'pending' for item in items):
            new_status = 'processing'
        elif all(item.item_status == 'processed' for item in items):
            new_status = 'order_ready'
        elif all(item.item_status == 'po_generated' for item in items):
            new_status = 'po_generated'
        else:
            new_status = 'new'
        
        if order.status != new_status:
            order.status = new_status
            order.save()

class CompanyDetails(models.Model):
    name = models.CharField(max_length=255)
    address = models.TextField()
    phone = models.CharField(max_length=50)
    vat_number = models.CharField(max_length=50)
    logo = models.ImageField(upload_to='company_logos/', null=True, blank=True)

    class Meta:
        verbose_name_plural = "Company Details"

    def __str__(self):
        return self.name