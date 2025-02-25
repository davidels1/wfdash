from django.db import models
from django.conf import settings
from wfdash.models import Customers, Suppliers
from decimal import Decimal, InvalidOperation

class QuoteRequest(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ]
    
    COMPANY_CHOICES = [
        ('CNL', 'CNL'),
        ('ISHERWOOD', 'Isherwood')
    ]

    quote_number = models.CharField(max_length=50, unique=True)
    quote_reference = models.CharField(max_length=50, blank=True)
    external_number = models.CharField(max_length=50, blank=True)
    markup = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    customer = models.ForeignKey('wfdash.Customers', on_delete=models.CASCADE)
    rep = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_quotes'
    )
    description = models.TextField()  # Add this field
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    email_sender = models.EmailField(blank=True, null=True)
    email_subject = models.CharField(max_length=255, blank=True, null=True)
    email_body = models.TextField(blank=True, null=True)
    has_attachments = models.BooleanField(default=False)
    company_letterhead = models.CharField(
        max_length=20, 
        choices=COMPANY_CHOICES,
        default='CNL'
    )
    pdf_file = models.FileField(
        upload_to='generated_quotes/%Y/%m/', 
        null=True, 
        blank=True
    )
    pdf_generated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Quote {self.quote_number} - {self.customer}"

    def can_complete(self):
        return all(item.is_processed and 
                  item.supplier and 
                  item.cost_price and 
                  item.selling_price 
                  for item in self.items.all())

    def all_items_complete(self):
        items = self.items.all()
        if not items:
            return False
        return all(
            bool(item.quote_number) and 
            bool(item.quote_reference) and 
            bool(item.markup) and 
            bool(item.supplier) and 
            bool(item.cost_price) and 
            bool(item.selling_price)
            for item in items
        )

    @property
    def is_complete(self):
        return self.status == 'completed'

    @property
    def has_pdf(self):
        return bool(self.pdf_file)

class QuoteItem(models.Model):
    quote = models.ForeignKey(QuoteRequest, related_name='items', on_delete=models.CASCADE)
    description = models.TextField()
    quote_number = models.CharField(max_length=100, blank=True)
    quote_reference = models.CharField(max_length=100, blank=True)
    quantity = models.IntegerField(default=1)
    supplier = models.ForeignKey(Suppliers, null=True, blank=True, on_delete=models.SET_NULL)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_processed = models.BooleanField(default=False)  # Add this field
    markup = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def save(self, *args, **kwargs):
        # Auto-calculate markup if not provided
        if self.cost_price and self.selling_price and not self.markup:
            self.markup = ((self.selling_price - self.cost_price) / self.cost_price) * 100
        super().save(*args, **kwargs)

    @property
    def is_complete(self):
        return bool(
            self.quote_number and 
            self.quote_reference and 
            self.supplier and 
            self.cost_price and 
            self.selling_price
        )

    def __str__(self):
        return f"{self.quote.quote_number} - {self.description[:50]}"

class QuoteAttachment(models.Model):
    quote = models.ForeignKey(QuoteRequest, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='quote_attachments/%Y/%m/')
    filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quote.quote_number} - {self.filename}"

    class Meta:
        ordering = ['-uploaded_at']