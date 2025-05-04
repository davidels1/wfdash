def is_mobile(request):
    """Check if request is from mobile device"""
    return any(
        x in request.META.get("HTTP_USER_AGENT", "").lower()
        for x in ["mobile", "android", "iphone", "ipad"]
    )


from django.db import IntegrityError
import qrcode
import io
import base64
from django.urls import reverse
from django.contrib.sites.models import Site


def generate_unique_quote_number():
    """
    Generate a unique quote number in the format Q000001
    Used for both manual quotes and email quotes for consistency
    """
    from quotes.models import QuoteRequest
    import re

    # Use Q prefix for all quotes
    prefix = "Q"

    # Find the last numeric quote with standard format
    # This specifically looks for quotes that match our format Q followed by digits
    standard_quotes = QuoteRequest.objects.filter(
        quote_number__regex=r"^Q\d{6}$"  # Match Q followed by exactly 6 digits
    ).order_by("-quote_number")

    if standard_quotes.exists():
        last_quote = standard_quotes.first()
        try:
            # Extract numeric part
            numeric_part = last_quote.quote_number[1:]  # Skip "Q" prefix
            new_number = int(numeric_part) + 1
        except (ValueError, TypeError):
            # Fallback to counting if extraction fails
            new_number = 100001  # Start with 100001
    else:
        # No standard quotes found, start with 100001
        new_number = 100001

    # Format with leading zeros (6 digits)
    return f"{prefix}{new_number:06d}"


def generate_quote_qr_code(request, quote_id):
    """Generate a QR code for a quote detail page"""
    # Get the current site domain
    current_site = Site.objects.get_current()
    domain = request.scheme + "://" + current_site.domain

    # Create the full URL to the quote detail page
    quote_url = domain + reverse("quotes:quote_detail", kwargs={"pk": quote_id})

    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(quote_url)
    qr.make(fit=True)

    # Create an image from the QR code
    img = qr.make_image(fill_color="black", back_color="white")

    # Convert the image to a base64 string to embed in HTML
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    image_data = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return f"data:image/png;base64,{image_data}"
