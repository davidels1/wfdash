from django.db import models


class RepSubmission(models.Model):
    """Track rep submissions to associate with customer later if needed"""

    SUBMISSION_TYPES = (("quote", "Quote Request"), ("order", "Order"))

    submission_type = models.CharField(max_length=10, choices=SUBMISSION_TYPES)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    reference_number = models.CharField(max_length=50, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # References to the actual quote or order (one will be null)
    # Changed related_name to avoid conflicts
    quote = models.ForeignKey(
        "quotes.QuoteRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rep_submission",  # Changed from customer_submission
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rep_submission",  # Changed from customer_submission
    )

    def __str__(self):
        return f"{self.get_submission_type_display()} - {self.reference_number}"
