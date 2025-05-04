from django.db import models
from django.conf import settings
from django.utils import timezone
from wfdash.models import Company, Customers
import uuid
import os
from django.urls import reverse
from django.utils.crypto import get_random_string


def get_delivery_note_number():
    """Generate a unique delivery note number"""
    prefix = "DN"
    date_part = timezone.now().strftime("%y%m%d")
    random_suffix = get_random_string(length=4, allowed_chars="0123456789")
    return f"{prefix}-{date_part}-{random_suffix}"


class DeliveryNote(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("need_signature", "Need Signature"),
        ("need_pricing", "Need Pricing"),
        ("need_both", "Need Signature & Pricing"),
        ("ready_to_invoice", "Ready to Invoice"),
        ("completed", "Completed"),
        ("delivered", "Delivered"),
        ("signed", "Signed"),
        ("converted", "Converted to Quote"),
        ("ordered", "Ordered"),
    ]

    delivery_number = models.CharField(
        max_length=50, unique=True, default=get_delivery_note_number
    )
    company = models.ForeignKey("wfdash.Company", on_delete=models.CASCADE)
    contact_person = models.CharField(max_length=100, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_delivery_notes",
    )
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="delivered_notes",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    delivery_date = models.DateField(default=timezone.now)
    signature_date = models.DateTimeField(null=True, blank=True)
    signed_by = models.CharField(max_length=100, blank=True)
    signature_file = models.FileField(
        upload_to="delivery_signatures/", null=True, blank=True
    )
    digital_signature = models.TextField(
        blank=True
    )  # For storing digital signature data
    signed_document = models.FileField(
        upload_to="delivery_notes/signed_documents/",
        blank=True,
        null=True,
        help_text="Uploaded scanned copy of signed delivery note",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    pdf_file = models.FileField(upload_to="delivery_notes/", null=True, blank=True)
    customer_order_number = models.CharField(max_length=50, blank=True, null=True)
    invoice_number = models.CharField(max_length=100, blank=True, null=True)

    # Fields for tracking conversions
    converted_to_quote = models.ForeignKey(
        "quotes.QuoteRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="from_delivery_note",
    )
    converted_at = models.DateTimeField(null=True, blank=True)

    # Fields for tracking order requests
    order_requests_count = models.IntegerField(
        default=0, help_text="Number of times an order has been requested"
    )
    last_order_requested_date = models.DateTimeField(null=True, blank=True)
    last_order_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="last_requested_order_deliveries",
    )

    # For backward compatibility
    @property
    def order_requested(self):
        return self.order_requests_count > 0

    @order_requested.setter
    def order_requested(self, value):
        if value and not self.order_requests_count:
            self.order_requests_count = 1

    def __str__(self):
        return f"{self.delivery_number} - {self.company.company}"

    def get_absolute_url(self):
        return reverse("delivery_notes:detail", kwargs={"pk": self.pk})

    def get_pdf_url(self):
        if self.pdf_file:
            return self.pdf_file.url
        return None

    def is_signed(self):
        """Check if delivery note is signed"""
        return bool(
            self.signature_date
            and (
                hasattr(self, "digital_signature")
                and self.digital_signature
                or hasattr(self, "signed_document")
                and self.signed_document
            )
        )

    def has_all_items_priced(self):
        """
        Check if all related items have complete pricing information
        (cost price, markup, and selling price).
        """
        if not self.items.exists():
            return False  # Cannot be priced if there are no items

        # Check if *any* item is missing complete pricing
        for item in self.items.all():
            if not item.has_complete_pricing():
                return False  # Found an item without complete pricing

        return True  # All items have complete pricing

    @property
    def can_generate_quote(self):
        """Check if the delivery note is ready to be converted to a quote."""
        return (
            self.is_signed()
            and self.has_all_items_priced()
            and not self.converted_to_quote
        )

    def get_status_category(self):
        """Return the status category for grouping in list view"""
        signed = self.is_signed()
        priced = self.has_all_items_priced()
        converted = bool(self.converted_to_quote)
        invoiced = bool(self.invoice_number)

        if invoiced:
            return "completed"
        elif signed and priced and converted:
            return "ready_to_invoice"
        elif signed and priced and not converted:
            return "generate_quote"
        elif signed and not priced:
            return "need_pricing"
        elif not signed and not priced:
            return "need_both"
        elif not signed and priced:
            return "need_signature"
        else:
            return "unknown"

    def total_items(self):
        return self.items.count()


class DeliveryItem(models.Model):
    delivery_note = models.ForeignKey(
        DeliveryNote, on_delete=models.CASCADE, related_name="items"
    )
    stock_item = models.ForeignKey(
        "stock_management.StockItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_items",
    )
    description = models.TextField()
    quantity = models.IntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cost_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    markup = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    def has_complete_pricing(self):
        """
        Checks if the item has valid cost price, markup, and selling price.
        Assumes price > 0 is the primary requirement, but also checks cost and markup.
        """
        has_valid_price = self.price is not None and self.price > 0
        has_valid_cost = (
            self.cost_price is not None and self.cost_price >= 0
        )  # Cost can be 0
        has_valid_markup = (
            self.markup is not None and self.markup >= 0
        )  # Markup can be 0

        # Require all three for complete pricing
        return has_valid_price and has_valid_cost and has_valid_markup

    def __str__(self):
        return f"{self.quantity}x {self.description[:30]}"

    def item_total(self):
        if self.price is not None:
            return self.price * self.quantity
        return None

    def calculate_markup(self):
        """Calculate the markup percentage if cost and selling price are set"""
        if self.cost_price and self.price and self.cost_price > 0:
            return ((self.price - self.cost_price) / self.cost_price) * 100
        return None

    def calculate_selling_price(self):
        """Calculate selling price based on cost price and markup"""
        if self.cost_price and self.markup:
            return self.cost_price * (1 + (self.markup / 100))
        return None
