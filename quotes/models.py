from django.db import models
from django.conf import settings
from wfdash.models import Customers, Suppliers
from decimal import Decimal, InvalidOperation
from django.contrib.auth.models import User  # Import the User model
from django.core.files.base import ContentFile
import base64
import uuid


class QuoteRequest(models.Model):
    """
    Represents a quote request.
    """

    STATUS_CHOICES = [
        ("new", "New"),
        ("claimed", "Claimed"),
        ("processed", "Processed"),
        ("emailed", "Emailed"),
        ("approval_pending", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("problem", "Problem Reported"),  # Add this new status
        ("complete", "Complete"),
        ("cancelled", "Cancelled"),
    ]

    COMPANY_CHOICES = [("CNL", "CNL"), ("ISHERWOOD", "Isherwood")]

    quote_number = models.CharField(max_length=50, unique=True)
    quote_reference = models.CharField(max_length=50, blank=True)
    external_number = models.CharField(max_length=50, blank=True)
    markup = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    customer = models.ForeignKey("wfdash.Customers", on_delete=models.CASCADE)
    rep = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_quotes",
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="quotes", null=True, blank=True
    )
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    email_sender = models.EmailField(blank=True, null=True)
    email_subject = models.CharField(max_length=255, blank=True, null=True)
    email_body = models.TextField(blank=True, null=True)
    has_attachments = models.BooleanField(default=False)
    company_letterhead = models.CharField(
        max_length=20, choices=COMPANY_CHOICES, default="CNL"
    )
    pdf_file = models.FileField(
        upload_to="generated_quotes/%Y/%m/", null=True, blank=True
    )
    pdf_generated_at = models.DateTimeField(null=True, blank=True)
    photo = models.ImageField(upload_to="quote_photos/%Y/%m/", blank=True, null=True)
    email_delivered = models.BooleanField(default=False)
    email_delivered_at = models.DateTimeField(null=True, blank=True)
    email_opened = models.BooleanField(default=False)
    email_opened_at = models.DateTimeField(null=True, blank=True)
    email_tracking_id = models.CharField(max_length=64, null=True, blank=True)

    def __str__(self):
        return f"{self.quote_number} - {self.customer.company}"

    def can_complete(self):
        return all(
            item.is_processed
            and item.supplier
            and item.cost_price
            and item.selling_price
            for item in self.items.all()
        )

    def all_items_complete(self):
        items = self.items.all()
        if not items:
            return False
        return all(
            bool(item.quote_number)
            and bool(item.quote_reference)
            and bool(item.markup)
            and bool(item.supplier)
            and bool(item.cost_price)
            and bool(item.selling_price)
            for item in items
        )

    @property
    def is_complete(self):
        return self.status == "completed"

    @property
    def has_pdf(self):
        return bool(self.pdf_file)

    def get_total(self):
        """Calculate total value of all items in the quote."""
        total = 0
        for item in self.items.all():
            if hasattr(item, "price") and item.price:
                quantity = item.quantity or 1
                total += item.price * quantity
        return total


class QuoteItem(models.Model):
    quote = models.ForeignKey(
        QuoteRequest, related_name="items", on_delete=models.CASCADE
    )
    description = models.TextField()
    quote_number = models.CharField(max_length=100, blank=True)
    quote_reference = models.CharField(max_length=100, blank=True)
    quantity = models.IntegerField(default=1)
    supplier = models.ForeignKey(
        Suppliers, null=True, blank=True, on_delete=models.SET_NULL
    )
    cost_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    selling_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_processed = models.BooleanField(default=False)  # Add this field
    markup = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    included_in_quote = models.BooleanField(default=False)
    quote_pdf_id = models.CharField(
        max_length=50, blank=True, null=True
    )  # To track which PDF this item was included in

    def save(self, *args, **kwargs):
        # Auto-calculate markup if not provided
        if self.cost_price and self.selling_price and not self.markup:
            self.markup = (
                (self.selling_price - self.cost_price) / self.cost_price
            ) * 100
        super().save(*args, **kwargs)

    @property
    def is_complete(self):
        return bool(
            self.quote_number
            and self.quote_reference
            and self.supplier
            and self.cost_price
            and self.selling_price
        )

    def __str__(self):
        return f"{self.quote.quote_number} - {self.description[:50]}"


class QuoteAttachment(models.Model):
    quote = models.ForeignKey(
        QuoteRequest, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to="quote_attachments/%Y/%m/%d/")
    filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.filename

    class Meta:
        ordering = ["-uploaded_at"]


class VoiceNote(models.Model):
    quote_request = models.ForeignKey(
        QuoteRequest, on_delete=models.CASCADE, related_name="voice_notes"
    )
    audio_file = models.FileField(upload_to="voice_notes/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Voice note for {self.quote_request.quote_number}"

    def save_audio(self, base64_data):
        """Save base64 audio data as a file"""
        if not base64_data:
            return

        try:
            # Split the base64 string at the comma
            format_info, base64_str = base64_data.split(";base64,")

            # Get the file extension from the MIME type
            extension = "webm"  # Default to webm
            if "ogg" in format_info:
                extension = "ogg"
            elif "mp3" in format_info or "mpeg" in format_info:
                extension = "mp3"
            elif "wav" in format_info:
                extension = "wav"

            # Create a unique filename
            import uuid
            from django.core.files.base import ContentFile
            import base64

            filename = f"voice_note_{uuid.uuid4()}.{extension}"

            # Decode base64 and save as file
            binary_data = base64.b64decode(base64_str)
            self.audio_file.save(filename, ContentFile(binary_data), save=False)

        except Exception as e:
            print(f"Error in save_audio: {e}")
            import traceback

            print(traceback.format_exc())


# Add a model to track email link clicks


class EmailClickTracker(models.Model):
    quote = models.ForeignKey(
        QuoteRequest, on_delete=models.CASCADE, related_name="email_clicks"
    )
    clicked_url = models.URLField()
    clicked_at = models.DateTimeField(auto_now_add=True)
    user_agent = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)

    class Meta:
        ordering = ["-clicked_at"]
