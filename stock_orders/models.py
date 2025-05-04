from django.db import models
from django.conf import settings
from django.utils import timezone
from wfdash.models import Suppliers  # Import your existing Suppliers model


class Supplier(models.Model):
    name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class StockOrder(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("pending", "Pending"),
        ("processed", "Processed"),
        ("assigned", "Assigned to Driver"),
        ("collected", "Collected"),
        ("in_stock", "In Stock"),
        ("canceled", "Canceled"),
    )

    order_number = models.CharField(max_length=50, unique=True)
    # Use your existing Suppliers model instead of a new one
    supplier = models.ForeignKey(
        Suppliers,  # Changed from Supplier to Suppliers
        on_delete=models.CASCADE,
        related_name="stock_orders",
    )

    # User who created the order
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_stock_orders",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    notes = models.TextField(blank=True, null=True)

    # Purchase order details
    po_number = models.CharField(max_length=100, blank=True, null=True)
    po_date = models.DateTimeField(blank=True, null=True)
    po_sent = models.BooleanField(default=False)
    email_sent_to = models.EmailField(blank=True, null=True)
    pdf_file = models.FileField(
        upload_to="stock_orders/po_files/", null=True, blank=True
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Driver assignment - Use AUTH_USER_MODEL instead of 'driver_list.Driver'
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL,  # Updated to use User model instead of Driver model
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_stock_orders",
    )

    assigned_at = models.DateTimeField(blank=True, null=True)
    collected_at = models.DateTimeField(blank=True, null=True)

    expected_delivery_date = models.DateField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Stock Order #{self.order_number}"

    def assign_to_driver(self, driver):
        """Assign this stock order to a driver"""
        self.driver = driver
        self.status = "assigned"
        self.assigned_at = timezone.now()
        self.save()

    def mark_as_collected(self):
        """Mark this stock order as collected by the driver"""
        self.status = "collected"
        self.collected_at = timezone.now()
        self.save()

    def move_to_stock(self):
        """Move this stock order to in-stock status"""
        from stock_management.models import StockItem
        from django.utils import timezone
        import logging
        from django.db import transaction

        logger = logging.getLogger(__name__)

        self.status = "in_stock"
        self.save()

        item_count = 0

        # Use transaction to ensure all operations are atomic
        with transaction.atomic():
            # Get all collections for this stock order
            for item in self.items.all():
                collections = item.collections.all()

                if collections.exists():
                    for collection in collections:
                        # Create a StockItem entry directly with office_stock status
                        # Skip the order_item association for stock orders
                        stock_item = StockItem.objects.create(
                            collection=collection,
                            order_item=None,  # This will fail unless order_item allows NULL
                            received_date=timezone.now().date(),
                            received_qty=item.quantity,
                            verified_quantity=item.quantity,  # Auto-verify
                            status="office_stock",  # Skip verification, go directly to office stock
                            external_invoice_number=self.po_number
                            or f"SO-{self.order_number}",
                            external_invoice_date=timezone.now().date(),
                            notes=f"Automatically added to office stock from Stock Order #{self.order_number}",
                        )
                        item_count += 1

                        # Mark the collection as collected
                        collection.status = "collected"
                        collection.actual_date = timezone.now().date()
                        collection.received_qty = item.quantity
                        collection.save()

        logger.info(
            f"Stock Order #{self.order_number} moved to office stock with {item_count} items"
        )


class StockOrderItem(models.Model):
    stock_order = models.ForeignKey(
        StockOrder, on_delete=models.CASCADE, related_name="items"
    )

    description = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.quantity} x {self.description} ({self.stock_order.order_number})"
