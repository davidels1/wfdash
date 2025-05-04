from django.db import models
from wfdash.models import Suppliers  # Assuming your Suppliers model is here
from decimal import Decimal
from django.utils import timezone
import datetime


class InternalStockItem(models.Model):
    part_number = models.CharField(
        max_length=100, unique=True, help_text="Your unique internal part number"
    )
    brand = models.CharField(max_length=100, blank=True, help_text="Brand of the item")
    description = models.TextField(help_text="Detailed description for the quote")
    supplier = models.ForeignKey(
        Suppliers,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Default supplier (e.g., 'Internal Stock')",
    )
    cost_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    markup = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Default markup percentage",
    )
    selling_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Calculated or fixed selling price",
    )
    # Add the notes field
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about this item (e.g., kit components, where to find items)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Auto-calculate selling_price from cost and markup if selling_price is not set
        if self.cost_price and self.markup and not self.selling_price:
            self.selling_price = self.cost_price * (1 + (self.markup / Decimal(100)))
        # Auto-calculate markup from cost and selling if markup is not set
        elif (
            self.cost_price
            and self.selling_price
            and not self.markup
            and self.cost_price > 0
        ):
            self.markup = (
                (self.selling_price - self.cost_price) / self.cost_price
            ) * Decimal(100)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.part_number} - {self.description[:50]}"

    class Meta:
        ordering = ["part_number"]
        verbose_name = "Internal Stock Item"
        verbose_name_plural = "Internal Stock Items"


class SupplierPriceList(models.Model):
    """Model to store supplier price list metadata"""

    supplier = models.ForeignKey(
        Suppliers, on_delete=models.CASCADE, related_name="price_lists"
    )
    name = models.CharField(
        max_length=200, help_text="Price list name (e.g., 'B&R 2025 Price List')"
    )
    year = models.PositiveIntegerField(help_text="Year of price list")
    valid_from = models.DateField(default=timezone.now)
    valid_until = models.DateField(null=True, blank=True)
    default_markup = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=30.00,
        help_text="Default markup percentage for items in this price list",
    )
    notes = models.TextField(
        blank=True, help_text="General notes about this price list"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.supplier.suppliername} - {self.name}"

    @property
    def is_valid(self):
        today = timezone.now().date()
        return (self.valid_from <= today) and (
            not self.valid_until or self.valid_until >= today
        )

    @property
    def duration(self):
        if not self.valid_until:
            return "Ongoing"
        days = (self.valid_until - self.valid_from).days
        if days < 30:
            return f"{days} days"
        elif days < 365:
            months = round(days / 30)
            return f"{months} months"
        else:
            years = round(days / 365, 1)
            return f"{years} years"

    class Meta:
        ordering = ["-year", "supplier"]
        verbose_name = "Supplier Price List"
        verbose_name_plural = "Supplier Price Lists"


class PriceListItem(models.Model):
    """Model for individual items in a supplier price list"""

    price_list = models.ForeignKey(
        SupplierPriceList, on_delete=models.CASCADE, related_name="items"
    )
    part_number = models.CharField(
        max_length=100, blank=True, help_text="Supplier's part number"
    )
    description = models.TextField(help_text="Item description")
    brand = models.CharField(max_length=100, blank=True)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    markup = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Markup percentage (leave blank to use price list default)",
    )
    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        # Use default markup from price list if not specified
        if not self.markup and self.price_list:
            self.markup = self.price_list.default_markup

        # Auto-calculate selling price from cost and markup if selling_price is not set
        if self.cost_price and self.markup and not self.selling_price:
            self.selling_price = self.cost_price * (1 + (self.markup / Decimal(100)))
        # Auto-calculate markup from cost and selling if markup is not set
        elif (
            self.cost_price
            and self.selling_price
            and not self.markup
            and self.cost_price > 0
        ):
            self.markup = (
                (self.selling_price - self.cost_price) / self.cost_price
            ) * Decimal(100)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.description} ({self.price_list.supplier.suppliername})"

    class Meta:
        ordering = ["description"]
        verbose_name = "Price List Item"
        verbose_name_plural = "Price List Items"
