from django.db import models
from django.conf import settings
from wfdash.models import Customers, Suppliers, Company
from quotes.models import QuoteRequest, QuoteItem
from django.utils import timezone
import uuid
from django.core.files.base import ContentFile
from decimal import Decimal
from django.core.validators import MinValueValidator
from django.db.models.signals import post_save
from django.dispatch import receiver


class Order(models.Model):
    STATUS_CHOICES = [
        ("new", "New"),
        ("processing", "Processing"),
        ("order_ready", "Order Ready"),
        ("po_generated", "PO Generated"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    order_number = models.CharField(max_length=50)  # Customer's order number
    company = models.ForeignKey(
        "wfdash.Company", on_delete=models.CASCADE
    )  # Changed from customer
    rep = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    quote = models.ForeignKey(
        QuoteRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="related_orders",
        verbose_name="Related Quote",
    )
    quote_matching_attempted = models.BooleanField(default=False)
    quote_match_confidence = models.IntegerField(null=True, blank=True)
    potential_quote = models.ForeignKey(
        "quotes.QuoteRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="potential_orders",
    )
    potential_quote_confidence = models.IntegerField(default=0)  # For 30-69% matches

    class Meta:
        unique_together = [
            "order_number",
            "company",
        ]  # Updated from customer to company
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["rep"]),
            models.Index(fields=["company"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"Order #{self.order_number}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def update_order_status(self):
        """
        Updates order status based on its items' statuses
        """
        items = self.items.all()

        # If no items exist, keep the order as "new"
        if not items.exists():
            new_status = "new"
        # If all items are delivered, mark as completed
        elif all(item.item_status == "delivered" for item in items):
            new_status = "completed"
        # If some items are not pending (but not all delivered), mark as processing
        elif any(item.item_status != "pending" for item in items):
            new_status = "processing"
        # If all items are pending, keep as new
        elif all(item.item_status == "pending" for item in items):
            new_status = "new"
        # Default fallback (shouldn't reach here but just in case)
        else:
            new_status = "new"

        # Only update if status has changed
        if self.status != new_status:
            self.status = new_status
            self.save(update_fields=["status"])

    def get_total_value(self):
        """Calculate total order value"""
        return sum(item.quantity * item.selling_price for item in self.items.all())

    def get_total_cost(self):
        """Calculate total order cost"""
        return sum(
            item.quantity * (item.cost_price or Decimal("0"))
            for item in self.items.all()
        )


class PurchaseOrder(models.Model):
    po_number = models.CharField(max_length=50, unique=True)
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="purchase_orders"
    )
    supplier = models.ForeignKey("wfdash.Suppliers", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default="draft")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    pdf_file = models.FileField(upload_to="purchase_orders/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.po_number

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.po_number:
            # Get company abbreviation
            company = CompanyDetails.objects.first()
            company_prefix = (
                "".join(word[0] for word in company.name.split()[:3]).upper()
                if company
                else "PO"
            )

            # Get today's date for the PO number
            today = timezone.now().strftime("%y%m")

            # Find last PO number for this prefix and month
            last_po = (
                PurchaseOrder.objects.filter(
                    po_number__startswith=f"{company_prefix}-{today}"
                )
                .order_by("-po_number")
                .first()
            )

            if last_po:
                last_number = int(last_po.po_number.split("-")[-1])
                next_number = str(last_number + 1).zfill(4)
            else:
                next_number = "0001"

            self.po_number = f"{company_prefix}-{today}-{next_number}"
        super().save(*args, **kwargs)


class OrderItem(models.Model):
    ITEM_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processed", "Processed"),
        ("po_generated", "PO Generated"),
        ("driver_pool", "In Driver Pool"),
        ("assigned", "Assigned to Driver"),
        ("collected", "Collected"),
        ("stock_verified", "Stock Verified"),
        ("picking", "Picking"),
        ("ready_delivery", "Ready for Delivery"),
        ("delivered", "Delivered"),
    ]

    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    description = models.CharField(max_length=255)
    po_description = models.TextField(
        blank=True, help_text="Description to use on the purchase order"
    )
    quantity = models.IntegerField(default=1)  # Original quantity from order
    order_qty = models.IntegerField(null=True, blank=True)  # New field for PO quantity
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    supplier = models.ForeignKey(
        Suppliers, on_delete=models.SET_NULL, null=True, blank=True
    )
    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=False,
        default=0.00,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    markup = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    purchase_order = models.ForeignKey(
        "PurchaseOrder", on_delete=models.SET_NULL, null=True, blank=True
    )
    item_status = models.CharField(
        max_length=20, choices=ITEM_STATUS_CHOICES, default="pending"
    )
    notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        # Import needed constants at the beginning of the method
        from decimal import Decimal, ROUND_HALF_UP

        # Auto-populate po_description with description if it's empty
        if not self.po_description:
            self.po_description = self.description

        # Set order_qty to quantity if not set
        if self.order_qty is None:
            self.order_qty = self.quantity

        # Convert float to Decimal if necessary
        if self.cost_price is not None:
            if isinstance(self.cost_price, float):
                # Convert through string to avoid floating point precision issues
                self.cost_price = Decimal(str(self.cost_price))
        else:
            # Default value for None
            self.cost_price = Decimal("0.00")

        # Other existing save logic
        if self.cost_price and self.selling_price:
            try:
                # Calculate markup percentage safely
                self.markup = (
                    (self.selling_price - self.cost_price) / self.cost_price
                ) * 100
            except Exception:
                # In case of division errors
                self.markup = Decimal("0")

        # Update status only if cost_price and supplier are newly set
        if self.cost_price and self.supplier:
            if self.item_status == "pending":
                self.item_status = "processed"

        # Add extra safety before save
        try:
            # Make sure cost_price is in range
            if self.cost_price is not None:
                max_digits = 10
                decimal_places = 2

                # Calculate maximum allowed value
                max_int_digits = max_digits - decimal_places
                max_allowed = 10**max_int_digits - Decimal("0.01")

                # If cost_price exceeds maximum, cap it
                if self.cost_price > max_allowed:
                    self.cost_price = max_allowed

                # Now it's safe to quantize
                self.cost_price = self.cost_price.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            super().save(*args, **kwargs)
        except Exception as e:
            # Log the error and raise a more helpful exception
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error saving OrderItem: {str(e)}")
            raise ValueError(
                f"Unable to save with cost_price={self.cost_price}. Please use a simpler number."
            )

    def update_order_status(self):
        """
        Updates the parent order's status based on the status of this and other items
        """
        order = self.order
        items = order.items.all()

        # Start with existing status checks
        if not items.exists():
            new_status = "new"
        # If all items are delivered, mark as completed
        elif all(item.item_status == "delivered" for item in items):
            new_status = "completed"
        # If any item is not pending, mark as processing
        elif any(item.item_status != "pending" for item in items):
            new_status = "processing"
        # If all items are pending, keep as new
        elif all(item.item_status == "pending" for item in items):
            new_status = "new"
        # Default fallback (shouldn't reach here but just in case)
        else:
            new_status = "new"

        # Only update if status has changed
        if order.status != new_status:
            order.status = new_status
            order.save(update_fields=["status"])


class CompanyDetails(models.Model):
    name = models.CharField(max_length=255)
    address = models.TextField()
    phone = models.CharField(max_length=50)
    vat_number = models.CharField(max_length=50)
    logo = models.ImageField(upload_to="company_logos/", null=True, blank=True)

    class Meta:
        verbose_name_plural = "Company Details"

    def __str__(self):
        return self.name


@receiver(post_save, sender=OrderItem)
def update_order_on_item_change(sender, instance, created, **kwargs):
    """
    Signal to update order status when an item's status changes
    """
    if instance.order:
        # Use the Order model's update_order_status method
        instance.order.update_order_status()
