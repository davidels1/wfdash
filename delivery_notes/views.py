import os
import base64
import logging
import tempfile
from django.db.models import Q
from io import BytesIO
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.conf import settings
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy, reverse
from django.template.loader import get_template
from django.utils import timezone
from django.db import transaction
from django.contrib import messages
from django.core.files.storage import default_storage
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.mail import EmailMessage
import json
import traceback
from PIL import Image as PILImage
import qrcode
import mimetypes
from quotes.views import generate_quote_pdf

# Local imports
from .models import DeliveryNote, DeliveryItem
from .forms import (
    DeliveryNoteForm,
    DeliveryItemFormSet,
    SignatureForm,
    UploadSignatureForm,
)
from stock_management.models import StockItem
from quotes.models import QuoteRequest, QuoteItem
from wfdash.models import Customers
from .utils import check_delivery_ready_status

# PDF generation imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm, inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
)
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

# Debug counts
from orders.models import OrderItem
from stock_management.models import StockItem


# Define a style for the reference


# When adding the reference to the PDF element


print(f"OrderItem count: {OrderItem.objects.count()}")
print(f"StockItem count: {StockItem.objects.count()}")

# =====================================================================
# Helper Functions
# =====================================================================


def is_mobile(request):
    """Check if the request is coming from a mobile device"""
    user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
    mobile_agents = ["mobile", "android", "iphone", "ipad", "ipod"]
    return any(agent in user_agent for agent in mobile_agents)


def generate_delivery_number():
    """Generate a unique delivery number"""
    prefix = "DN"
    date_str = timezone.now().strftime("%y%m%d")
    pattern = f"{prefix}{date_str}"

    latest_delivery = (
        DeliveryNote.objects.filter(delivery_number__startswith=pattern)
        .order_by("-delivery_number")
        .first()
    )

    if latest_delivery:
        try:
            last_num = int(latest_delivery.delivery_number[len(pattern) :])
            new_num = last_num + 1
        except ValueError:
            new_num = 1
    else:
        new_num = 1

    return f"{prefix}{date_str}{new_num:03d}"


def safe_load_image(image_path, max_side=2000):
    """
    Load an image with robust safety measures against decompression bombs
    and corrupt files. Returns a PIL Image and the path to the temporary file.
    """
    from PIL import Image, ImageFile
    import os
    import tempfile
    import subprocess

    # Safety precautions
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    Image.MAX_IMAGE_PIXELS = None

    # Check file size first
    file_size = os.path.getsize(image_path)
    if file_size > 50 * 1024 * 1024:  # 50MB limit
        raise ValueError(f"File too large: {file_size / (1024 * 1024):.1f}MB")

    try:
        # Create a temp directory to work in
        temp_dir = tempfile.mkdtemp()
        temp_output = os.path.join(temp_dir, "resized.jpg")

        # Try multiple approaches, starting with most reliable
        try:
            # Try ImageMagick first
            subprocess.run(
                [
                    "convert",
                    image_path,
                    "-resize",
                    f"{max_side}x{max_side}>",
                    temp_output,
                ],
                check=True,
                timeout=30,
            )
            img = Image.open(temp_output)
            return img, temp_output
        except (subprocess.SubprocessError, FileNotFoundError):
            # ImageMagick not available, try PIL
            with open(image_path, "rb") as f:
                file_bytes = f.read()

            # Create a new blank image with safe dimensions
            safe_img = Image.new("RGB", (max_side, max_side), color="white")

            try:
                # Try to decode the image with strict size limits
                from io import BytesIO

                temp_img = Image.open(BytesIO(file_bytes))

                # Get original dimensions safely
                width, height = temp_img.size

                # Check if dimensions are reasonable
                if width > 10000 or height > 10000 or (width * height) > 100000000:
                    width, height = 1000, 1000
                    temp_img = Image.new("RGB", (width, height), color=(245, 245, 245))

                # Calculate new size while preserving aspect ratio
                if width > height:
                    new_width = min(width, max_side)
                    new_height = int(height * (new_width / width))
                else:
                    new_height = min(height, max_side)
                    new_width = int(width * (new_height / height))

                # Resize to safe dimensions
                temp_img = temp_img.resize((new_width, new_height), Image.LANCZOS)
                temp_img.save(temp_output, format="JPEG", quality=85)

                return Image.open(temp_output), temp_output

            except Exception as decode_error:
                # If all decoding fails, create a placeholder image
                placeholder = Image.new("RGB", (500, 300), color=(240, 240, 240))
                placeholder.save(temp_output)
                return placeholder, temp_output

    except Exception as e:
        # Clean up any temp files
        try:
            import shutil

            if "temp_dir" in locals():
                shutil.rmtree(temp_dir)
        except:
            pass

        # Re-raise with more context
        raise ValueError(f"Cannot safely process image: {str(e)}")


def generate_unique_quote_number():
    """Generate a unique quote number that matches the standard format used elsewhere"""
    # Get the latest quote with standard format (Q followed by 6 digits)
    latest_quote = (
        QuoteRequest.objects.filter(
            quote_number__regex=r"^Q\d{6}$"  # Only match standard format
        )
        .order_by("-quote_number")
        .first()
    )

    if latest_quote:
        try:
            # Extract the numeric part (skip the 'Q')
            current_number = int(latest_quote.quote_number[1:])
            # Increment by 1
            new_number = current_number + 1
        except (ValueError, IndexError):
            # Fallback if parsing fails
            new_number = 1
    else:
        # Start with 1 if no quotes exist
        new_number = 1

    # Format with leading zeros to 6 digits
    return f"Q{new_number:06d}"


def generate_qr_code(url, size=2.0):
    """Generate QR code for delivery note actions"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # Changed from ERROR_CORRECTION_H
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return buffer


def check_delivery_ready_status(delivery):
    """Check if delivery note is ready to be processed based on signature and prices"""
    # Must have a signature
    has_signature = bool(delivery.digital_signature)

    if not has_signature:
        return False

    # All items must have prices
    all_items_have_prices = True
    items = delivery.items.all()

    if not items:
        return False

    for item in items:
        if item.price is None or item.price <= 0:
            all_items_have_prices = False
            break

    # If conditions are met and status is not already beyond 'signed'
    if (
        has_signature
        and all_items_have_prices
        and delivery.status in ["draft", "delivered"]
    ):
        delivery.status = "signed"
        delivery.save(update_fields=["status", "updated_at"])
        return True

    return False


# =====================================================================
# Email Functions
# =====================================================================


def send_delivery_email(delivery, email_type="signed", recipient=None, request=None):
    """
    Centralized email function for delivery notes with different email types:
    - 'signed': For digitally signed delivery notes
    - 'paper_signed': For paper-signed delivery notes
    - 'confirmation': General delivery confirmation

    Returns True if email sent successfully, False otherwise
    """
    try:
        subject_prefix = {
            "signed": "Delivery Note Signed",
            "paper_signed": "Delivery Note - Paper Signature Recorded",
            "confirmation": "Delivery Confirmation",
        }.get(email_type, "Delivery Note")

        subject = f"{subject_prefix}: {delivery.delivery_number}"

        # Determine recipients
        to_emails = []
        cc_emails = []

        # Add customer email if available
        if delivery.contact_email and (
            email_type == "signed" or email_type == "confirmation"
        ):
            to_emails.append(delivery.contact_email)

        # Add requestor if available
        if request and request.user.email:
            cc_emails.append(request.user.email)

        # Add recipient if specified
        if recipient:
            if (
                not to_emails
            ):  # Only add as primary recipient if no other primary recipient
                to_emails.append(recipient)
            else:
                cc_emails.append(recipient)

        # Add creator if available and not already included
        if delivery.created_by and delivery.created_by.email:
            if (
                delivery.created_by.email not in cc_emails
                and delivery.created_by.email not in to_emails
            ):
                cc_emails.append(delivery.created_by.email)

        # If no recipients, return False
        if not to_emails and not cc_emails:
            logger.warning(
                f"No recipients for delivery email {delivery.delivery_number}"
            )
            return False

        # Construct appropriate message based on email type
        if email_type == "signed":
            message = f"""Dear {delivery.contact_person or "Customer"},

Thank you for signing our delivery note.

Your delivery note number is: {delivery.delivery_number}
Date: {delivery.delivery_date.strftime("%d %B %Y")}

A copy of the signed delivery note is attached for your records.

If you have any questions about this delivery, please contact us.

Thank you for your business,
{delivery.created_by.get_full_name() if delivery.created_by else "WF Sales Team"}
WF Group of Companies
"""
        elif email_type == "paper_signed":
            message = f"""Dear Team,

A paper-signed delivery note has been uploaded to the system.

Delivery Note: {delivery.delivery_number}
Date: {delivery.delivery_date.strftime("%d %B %Y")}
Customer: {delivery.company.company}
Signed By: {delivery.signed_by or "Unknown"}
Order Number: {delivery.customer_order_number or "Not provided"}

Both the original delivery note and the scanned signed copy are attached.

Uploaded by: {request.user.get_full_name() if request and request.user else "Unknown"}
"""
        else:  # confirmation or default
            message = f"""Dear {delivery.contact_person or "Customer"},

Thank you for receiving our delivery.

Delivery Number: {delivery.delivery_number}
Date: {delivery.delivery_date.strftime("%d %B %Y")}
{f"Signed By: {delivery.signed_by}" if delivery.signed_by else ""}

A copy of the delivery note is attached for your records.

Thank you for your business,
WF Group of Companies
"""

        # Create email
        email = EmailMessage(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=to_emails,
            cc=cc_emails,
        )

        # Attach the delivery note PDF
        if delivery.pdf_file:
            email.attach_file(delivery.pdf_file.path)

        # For paper-signed, also attach the uploaded document
        if email_type == "paper_signed" and delivery.signed_document:
            email.attach_file(delivery.signed_document.path)

        # Send the email
        email.send()
        return True

    except Exception as e:
        logger.error(f"Error sending delivery email: {str(e)}")
        return False


# =====================================================================
# PDF Generation Functions
# =====================================================================


@login_required
def generate_delivery_pdf(request, pk, as_response=True):
    """Generate a PDF for a delivery note"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    # Create a file-like buffer to receive PDF data
    buffer = BytesIO()

    # Create the PDF object, using the buffer as its "file"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    # Container for the 'Flowable' objects
    elements = []
    styles = getSampleStyleSheet()

    # Get company details
    company_name = "WF - GROUP OF COMPANIES"
    company_address = "47 Station Street, Carletonville, Gauteng 2499"
    company_phone = "+27 18 786 2897"
    company_email = "info@wfsales.co.za"

    # Find logo
    try:
        possible_logo_paths = [
            os.path.join(
                settings.BASE_DIR, "static", "assets", "images", "wf_logo.png"
            ),
            os.path.join(settings.BASE_DIR, "static", "images", "wf_logo.png"),
            os.path.join(
                settings.BASE_DIR, "wfdash", "static", "assets", "images", "wf_logo.png"
            ),
            # Fallbacks
            os.path.join(
                settings.BASE_DIR, "static", "assets", "images", "cnl_logo.png"
            ),
            os.path.join(settings.BASE_DIR, "static", "images", "cnl_logo.png"),
            os.path.join(
                settings.BASE_DIR,
                "wfdash",
                "static",
                "assets",
                "images",
                "cnl_logo.png",
            ),
        ]

        logo_path = None
        for path in possible_logo_paths:
            if path and os.path.exists(path):
                logo_path = path
                break

        if not logo_path:
            # Create a blank image as fallback
            temp_logo = os.path.join(settings.BASE_DIR, "temp_logo.png")
            img = PILImage.new("RGB", (200, 100), color=(255, 255, 255))
            img.save(temp_logo)
            logo_path = temp_logo

    except Exception as e:
        # Create a blank image as fallback
        temp_logo = os.path.join(settings.BASE_DIR, "temp_logo.png")
        img = PILImage.new("RGB", (300, 200), color=(255, 255, 255))
        img.save(temp_logo)
        logo_path = temp_logo

    # Generate QR code URL with the delivery ID
    base_url = settings.BASE_URL
    qr_url = f"{base_url}/delivery/{delivery.id}/mobile-actions/"

    # Create smaller QR code
    qr_buffer = generate_qr_code(qr_url)
    qr_img = Image(qr_buffer, width=1.0 * inch, height=1.0 * inch)
    qr_img.hAlign = "CENTER"  # Center the QR code

    # Create a table with logo on top and QR code below
    logo_qr_table = Table(
        [
            [Image(logo_path, width=3.0 * inch, height=0.60 * inch)],  # First row: logo
            [qr_img],  # Second row: QR code
        ],
        colWidths=[3.0 * inch],  # Single column width
    )
    logo_qr_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, 1), "CENTER"),  # Center both logo and QR code
                ("VALIGN", (0, 0), (0, 1), "MIDDLE"),  # Middle vertical alignment
                (
                    "TOPPADDING",
                    (0, 1),
                    (0, 1),
                    7,
                ),  # Add padding between logo and QR code
            ]
        )
    )

    # Header with company info and logo+QR combo
    header_data = [
        [
            Table(
                [
                    [Paragraph(f"<b>{company_name}</b>", styles["Heading1"])],
                    [Paragraph(company_address, styles["Normal"])],
                    [Paragraph(company_phone, styles["Normal"])],
                    [Paragraph(company_email, styles["Normal"])],
                ],
                colWidths=[4 * inch],
            ),
            logo_qr_table,  # Use the combined logo+QR table instead
        ]
    ]

    header_table = Table(header_data, colWidths=[4 * inch, 4 * inch])
    header_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),  # Reduced from 20 to 5
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 5))  # Reduced from 15 to 5

    # Add delivery information
    elements.append(Paragraph("<b>DELIVERY NOTE</b>", styles["Heading1"]))
    elements.append(
        Paragraph(f"Delivery Number: {delivery.delivery_number}", styles["Normal"])
    )
    elements.append(
        Paragraph(
            f"Date: {delivery.delivery_date.strftime('%d %B %Y')}", styles["Normal"]
        )
    )
    elements.append(Spacer(1, 20))

    # Delivery details
    details_data = [
        [
            Table(
                [
                    [Paragraph("<b>DELIVER TO:</b>", styles["Normal"])],
                    [Paragraph(f"{delivery.company.company}", styles["Normal"])],
                    [
                        Paragraph(
                            f"Contact: {delivery.contact_person or ''}",
                            styles["Normal"],
                        )
                    ],
                    [
                        Paragraph(
                            f"Phone: {delivery.contact_phone or ''}",
                            styles["Normal"],
                        )
                    ],
                    [
                        Paragraph(
                            f"Email: {delivery.contact_email or ''}",
                            styles["Normal"],
                        )
                    ],
                ],
                colWidths=[3 * inch],
            ),
            Table(
                [
                    [Paragraph("<b>DELIVERY DETAILS:</b>", styles["Normal"])],
                    [
                        # Make sure we correctly display the creator's name
                        Paragraph(
                            f"Created By: {delivery.created_by.get_full_name() or delivery.created_by.username}",
                            styles["Normal"],
                        )
                    ],
                    [
                        Paragraph(
                            f"Created On: {delivery.created_at.strftime('%d %B %Y')}",
                            styles["Normal"],
                        )
                    ],
                    [
                        Paragraph(
                            f"Status: {delivery.get_status_display()}",
                            styles["Normal"],
                        )
                    ],
                    [
                        Paragraph(
                            f"Order #: {delivery.customer_order_number or 'N/A'}",
                            styles["Normal"],
                        )
                    ],
                ],
                colWidths=[3 * inch],
            ),
        ]
    ]

    details_table = Table(details_data, colWidths=[4 * inch, 4 * inch])
    details_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.white),
                ("LINEBELOW", (0, 0), (-1, 0), 1, colors.black),
            ]
        )
    )
    elements.append(details_table)
    elements.append(Spacer(1, 20))

    # Items table with styling to match PO
    # Always use simplified columns without pricing
    table_data = [["Description", "Quantity", "Notes"]]

    for item in delivery.items.all():
        description_text = item.description
        description_paragraph = Paragraph(description_text, styles["Normal"])

        table_data.append(
            [
                description_paragraph,
                str(item.quantity),
                Paragraph(item.notes or "", styles["Normal"]),
            ]
        )

    # Create table with column widths
    items_table = Table(table_data, colWidths=[5 * inch, 1 * inch, 2 * inch])

    # Apply styling to match PO
    items_table.setStyle(
        TableStyle(
            [
                # Header row styling - orange background with white text
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e76240")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                # Data rows
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),  # Right-align numeric columns
                ("ALIGN", (0, 1), (0, -1), "LEFT"),  # Left-align description
                ("ALIGN", (-1, 1), (-1, -1), "LEFT"),  # Left-align notes
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                # Gridlines
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                # Padding for all cells
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    elements.append(items_table)
    elements.append(Spacer(1, 20))

    # Notes section
    if delivery.notes:
        elements.append(Paragraph("<b>NOTES:</b>", styles["Heading3"]))
        elements.append(Paragraph(delivery.notes, styles["Normal"]))
        elements.append(Spacer(1, 20))

    # Signature section - improved styling
    elements.append(Paragraph("<b>AUTHORIZATION</b>", styles["Heading3"]))
    elements.append(Spacer(1, 10))

    # Signature table
    signature_data = [
        ["Delivered By", "Received By"],
        [
            f"{delivery.created_by.get_full_name() if delivery.created_by else ''}",
            f"{delivery.signed_by or '______________________'}",
        ],
        [
            f"Date: {delivery.created_at.strftime('%d %B %Y') if delivery.created_at else ''}",
            f"Date: {delivery.signature_date.strftime('%d %B %Y') if delivery.signature_date else '______________________'}",
        ],
    ]

    signature_table = Table(signature_data, colWidths=[4 * inch, 4 * inch])
    signature_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (1, 0), "CENTER"),
                ("BACKGROUND", (0, 0), (1, 0), colors.HexColor("#e76240")),
                ("TEXTCOLOR", (0, 0), (1, 0), colors.white),
                ("FONTNAME", (0, 0), (1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (1, 0), 8),
                ("TOPPADDING", (0, 0), (1, 0), 8),
                ("LINEBELOW", (0, 1), (1, 1), 1, colors.black),
                ("TOPPADDING", (0, 1), (1, 1), 30),  # Space for signature
                ("ALIGN", (0, 1), (1, 2), "CENTER"),
            ]
        )
    )

    elements.append(signature_table)

    # Add signature image if available and requested
    if delivery.is_signed() and delivery.digital_signature:
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("<b>SIGNATURE</b>", styles["Heading3"]))

        try:
            # Extract base64 data directly without saving to temp file
            if "," in delivery.digital_signature:
                base64_data = delivery.digital_signature.split(",", 1)[1]
            else:
                base64_data = delivery.digital_signature

            # Decode to binary
            signature_binary = base64.b64decode(base64_data)

            # Create BytesIO object instead of a temp file
            signature_io = BytesIO(signature_binary)

            # Add to PDF using BytesIO object
            signature_img = Image(signature_io, width=3 * inch, height=1.2 * inch)
            signature_img.hAlign = "CENTER"
            elements.append(signature_img)

        except Exception as e:
            # Just add the error message to the PDF
            elements.append(
                Paragraph(f"Error displaying signature: {str(e)}", styles["Normal"])
            )

    # Footer with disclaimer
    elements.append(Spacer(1, 30))
    elements.append(
        Paragraph(
            f"This document was generated on {timezone.now().strftime('%d %B %Y at %H:%M')}.",
            ParagraphStyle("Footer", parent=styles["Normal"], alignment=1, fontSize=8),
        )
    )

    # Build the PDF
    doc.build(elements)

    # Get the value from the buffer
    pdf_value = buffer.getvalue()
    buffer.close()

    # Save PDF to delivery model
    pdf_filename = f"delivery_note_{delivery.delivery_number}.pdf"
    content_file = ContentFile(pdf_value)

    # Delete old file if exists
    if delivery.pdf_file:
        try:
            old_path = delivery.pdf_file.path
            if os.path.exists(old_path):
                delivery.pdf_file.delete(save=False)
        except Exception as delete_error:
            logger.error(f"Error deleting old PDF: {str(delete_error)}")

    delivery.pdf_file.save(pdf_filename, content_file, save=True)

    # At the end, check if we want to return content or response
    if not as_response:
        # Return the PDF content as bytes
        return pdf_value

    # Return the normal HttpResponse with the PDF
    response = HttpResponse(pdf_value, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{pdf_filename}"'
    return response


# =====================================================================
# Class-Based Views
# =====================================================================


class DeliveryNoteListView(LoginRequiredMixin, ListView):
    """View all delivery notes"""

    model = DeliveryNote
    paginate_by = 20
    context_object_name = "delivery_notes"

    def get_template_names(self):
        if is_mobile(self.request):
            return ["delivery_notes/mobile/delivery_list.html"]
        return ["delivery_notes/delivery_list.html"]

    def get_queryset(self):
        queryset = DeliveryNote.objects.all().order_by("-created_at")

        # Add search functionality
        search_query = self.request.GET.get("q")
        if search_query:
            queryset = queryset.filter(
                Q(delivery_number__icontains=search_query)
                | Q(company__company__icontains=search_query)
                | Q(contact_person__icontains=search_query)
            )

        # Status filter
        status_filter = self.request.GET.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Date range filter
        date_from = self.request.GET.get("date_from")
        date_to = self.request.GET.get("date_to")
        if date_from:
            date_from = timezone.datetime.strptime(date_from, "%Y-%m-%d")
            queryset = queryset.filter(delivery_date__gte=date_from)
        if date_to:
            date_to = timezone.datetime.strptime(date_to, "%Y-%m-%d")
            queryset = queryset.filter(delivery_date__lte=date_to)

        # Add a total_items property to each delivery note
        for delivery in queryset:
            delivery.total_items = delivery.items.count()

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = DeliveryNote.STATUS_CHOICES

        # Add counts for status filter badges
        status_counts = {}
        for status_code, status_name in DeliveryNote.STATUS_CHOICES:
            status_counts[status_code] = DeliveryNote.objects.filter(
                status=status_code
            ).count()
        context["status_counts"] = status_counts

        return context


class DeliveryNoteDetailView(LoginRequiredMixin, DetailView):
    """View a delivery note"""

    model = DeliveryNote
    context_object_name = "delivery"

    def get_template_names(self):
        # Choose template based on device type
        if is_mobile(self.request):
            return ["delivery_notes/mobile/delivery_detail.html"]
        return ["delivery_notes/delivery_detail.html"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add signature mode flag
        context["signature_mode"] = self.request.GET.get("signature_mode", "0") == "1"
        delivery = self.get_object()

        # Initialize signature form
        context["signature_form"] = SignatureForm()
        context["upload_form"] = UploadSignatureForm()

        # Calculate whether any items have prices and the total
        items_with_prices = delivery.items.exclude(price__isnull=True).exclude(price=0)
        context["has_prices"] = items_with_prices.exists()

        # Calculate total price if applicable
        if context["has_prices"]:
            total = sum(item.price * item.quantity for item in items_with_prices)
            context["total_price"] = total

        return context


# =====================================================================
# Function-Based Views
# =====================================================================


@login_required
def delivery_list(request):
    """View all delivery notes"""
    # Start with base queryset
    queryset = (
        DeliveryNote.objects.all()
        .prefetch_related("items")
        .select_related("company", "created_by", "converted_to_quote")
    )

    # Handle search functionality
    search_query = request.GET.get("search", "")
    if search_query:
        # Search across delivery number, company name, and item descriptions
        queryset = queryset.filter(
            Q(delivery_number__icontains=search_query)
            | Q(company__company__icontains=search_query)
            | Q(items__description__icontains=search_query)
        ).distinct()

    # Group by category instead of direct status
    delivery_notes_by_category = {}

    # Define display names and order for categories
    categories = {
        "need_both": "Need Signature & Pricing",
        "need_signature": "Need Signature",
        "need_pricing": "Need Pricing",
        "generate_quote": "Generate Quote",
        "ready_to_invoice": "Ready to Invoice",
        "awaiting_order": "Awaiting Order Number",
        "completed": "Completed",
    }

    # Group by company within each category
    for delivery in queryset:
        category = delivery.get_status_category()

        if category not in delivery_notes_by_category:
            delivery_notes_by_category[category] = {}

        company_name = delivery.company.company
        if company_name not in delivery_notes_by_category[category]:
            delivery_notes_by_category[category][company_name] = []

        delivery_notes_by_category[category][company_name].append(delivery)

    # Sort by company within each category
    for category in delivery_notes_by_category:
        delivery_notes_by_category[category] = dict(
            sorted(delivery_notes_by_category[category].items())
        )

    # Order categories by priority
    ordered_delivery_notes = {}
    for category in categories:
        if category in delivery_notes_by_category:
            ordered_delivery_notes[categories[category]] = delivery_notes_by_category[
                category
            ]

    return render(
        request,
        "delivery_notes/delivery_list.html",
        {
            "delivery_notes_by_status": ordered_delivery_notes,
            "all_deliveries": queryset,
            "search_query": search_query,  # Add search query to context
            "total_results": queryset.count(),  # Add total results count
        },
    )


@login_required
def delivery_detail(request, pk):
    """Function-based view for delivery note detail (fallback)"""
    view = DeliveryNoteDetailView.as_view()
    return view(request, pk=pk)


@login_required
def create_delivery_note(request):
    """Create a new delivery note"""
    if request.method == "POST":
        form = DeliveryNoteForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                delivery = form.save(commit=False)
                delivery.created_by = request.user
                # Ensure delivery number is generated if not provided by form
                if not delivery.delivery_number:
                    delivery.delivery_number = generate_delivery_number()
                delivery.save()

                formset = DeliveryItemFormSet(request.POST, instance=delivery)
                if formset.is_valid():
                    formset.save()

                    # Generate PDF (consider doing this asynchronously if it takes time)
                    try:
                        generate_delivery_pdf(request, delivery.pk, as_response=False)
                    except Exception as pdf_error:
                        logger.error(
                            f"Error generating PDF for new delivery {delivery.pk}: {pdf_error}"
                        )
                        messages.warning(
                            request,
                            f"Delivery note {delivery.delivery_number} created, but PDF generation failed.",
                        )
                        # Decide if you still want to redirect or show an error

                    messages.success(
                        request,
                        f"Delivery note {delivery.delivery_number} created successfully.",
                    )
                    return redirect(
                        "delivery_notes:list"
                    )  # Changed from detail to list
                else:
                    # Handle formset errors
                    for form_errors in formset.errors:
                        for field, error_list in form_errors.items():
                            for error in error_list:
                                messages.error(
                                    request, f"Item Error - {field}: {error}"
                                )
                    # Rollback transaction if formset is invalid
                    transaction.set_rollback(True)
        else:
            # Handle main form errors
            for field, error_list in form.errors.items():
                for error in error_list:
                    messages.error(request, f"Error in {field}: {error}")

    # If GET or form/formset invalid, render the create page again
    else:
        form = DeliveryNoteForm()
        formset = DeliveryItemFormSet()

    return render(
        request,
        "delivery_notes/delivery_create.html",
        {
            "form": form,
            "formset": formset,
        },
    )


@login_required
def edit_delivery_note(request, pk):
    """Edit an existing delivery note"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    # Only allow editing draft delivery notes
    if delivery.status != "draft" and not request.user.is_staff:
        messages.warning(request, "Only draft delivery notes can be edited.")
        return redirect("delivery_notes:detail", pk=delivery.pk)

    if request.method == "POST":
        form = DeliveryNoteForm(request.POST, instance=delivery)
        if form.is_valid():
            with transaction.atomic():
                delivery = form.save()

                formset = DeliveryItemFormSet(request.POST, instance=delivery)
                if formset.is_valid():
                    formset.save()

                    # Regenerate PDF
                    generate_delivery_pdf(request, delivery.pk)

                    messages.success(
                        request,
                        f"Delivery note {delivery.delivery_number} updated successfully.",
                    )
                    return redirect("delivery_notes:detail", pk=delivery.pk)
                else:
                    for form_errors in formset.errors:
                        for field, error in formset.errors.items():
                            messages.error(request, f"{field}: {error[0]}")
        else:
            for field, error in form.errors.items():
                messages.error(request, f"{field}: {error[0]}")
    else:
        form = DeliveryNoteForm(instance=delivery)
        formset = DeliveryItemFormSet(instance=delivery)

    return render(
        request,
        "delivery_notes/delivery_edit.html",
        {"form": form, "formset": formset, "delivery": delivery},
    )


@login_required
def delete_delivery_note(request, pk):
    """Delete a delivery note"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    # Allow admin users to delete any delivery note
    if not request.user.is_staff and delivery.status != "draft":
        messages.warning(
            request, "Only draft delivery notes can be deleted by regular users."
        )
        return redirect("delivery_notes:detail", pk=delivery.pk)

    if request.method == "POST":
        # Store the delivery number for the success message
        delivery_number = delivery.delivery_number

        # Delete the delivery note
        delivery.delete()

        messages.success(
            request, f"Delivery note {delivery_number} deleted successfully."
        )
        return redirect("delivery_notes:list")

    # GET request shows confirmation page
    return render(
        request, "delivery_notes/delivery_delete_confirm.html", {"delivery": delivery}
    )


@login_required
def save_signature(request, pk):
    """Save a digital signature to a delivery note"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    if request.method == "POST":
        form = SignatureForm(request.POST)

        if form.is_valid():
            # Update delivery note with signature data
            delivery.digital_signature = request.POST.get("digital_signature")
            delivery.signed_by = form.cleaned_data["signed_by"]
            delivery.customer_order_number = form.cleaned_data.get(
                "customer_order_number", ""
            )
            delivery.signature_date = timezone.now()
            delivery.status = "signed"
            delivery.save()

            # Add success message before generating PDF
            messages.success(
                request,
                f"Signature saved successfully for delivery note {delivery.delivery_number}",
            )

            # Use the "skip response" pattern for PDF generation
            request._skip_response = True

            # Generate the PDF without redirecting to it
            try:
                generate_delivery_pdf(request, pk, as_response=False)
                # Send email with signature
                if delivery.contact_email:
                    if send_delivery_email(delivery, "signed", request=request):
                        messages.success(request, "Signature confirmation email sent.")
                    else:
                        messages.warning(
                            request, "Signature saved but email could not be sent."
                        )
            except Exception as e:
                logger.error(f"Error generating PDF after saving signature: {str(e)}")
                messages.warning(
                    request,
                    "Signature saved, but there was an error generating the PDF.",
                )

            # Check if delivery is now ready to process
            check_delivery_ready_status(delivery)

            return redirect("delivery_notes:detail", pk=pk)
        else:
            messages.error(request, "Error saving signature: Form validation failed")
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    return redirect("delivery_notes:detail", pk=pk)


@login_required
def upload_signed_document(request, pk):
    """Upload a scanned signed document instead of digital signature"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    if request.method == "POST":
        form = UploadSignatureForm(request.POST, request.FILES, instance=delivery)
        if form.is_valid():
            try:
                # Save the form which updates the delivery instance
                form.save()

                # Update signature date and status
                delivery.signature_date = timezone.now()
                delivery.status = "signed"
                delivery.save(update_fields=["signature_date", "status", "updated_at"])

                # Regenerate PDF to include signature details if needed (optional)
                generate_delivery_pdf(request, pk, as_response=False)

                messages.success(
                    request,
                    f"Signed document uploaded successfully for {delivery.delivery_number}",
                )
                return redirect("delivery_notes:detail", pk=pk)

            except Exception as e:
                logger.error(f"Error processing uploaded document: {str(e)}")
                messages.error(request, f"Error processing uploaded document: {str(e)}")

        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Error in {field}: {error}")

    # For GET request, show the upload form
    context = {"form": UploadSignatureForm(instance=delivery), "delivery": delivery}
    return render(request, "delivery_notes/upload_signature.html", context)


@login_required
def upload_signed(request, delivery_id):
    """Upload a signed document via AJAX"""
    delivery = get_object_or_404(DeliveryNote, id=delivery_id)

    if request.method == "POST":
        try:
            form = UploadSignatureForm(request.POST, request.FILES, instance=delivery)
            if form.is_valid():
                # Save the form which updates the delivery instance
                form.save()

                # Update signature date and status
                delivery.signature_date = timezone.now()
                delivery.status = "signed"
                delivery.save(update_fields=["signature_date", "status", "updated_at"])

                # Regenerate PDF (optional, consider if needed for AJAX)
                generate_delivery_pdf(request, delivery.pk, as_response=False)

                # Return JSON response for AJAX
                return JsonResponse(
                    {
                        "success": True,
                        "message": "Document uploaded successfully",
                        "delivery_id": delivery.id,
                    }
                )
            else:
                # Handle form errors for AJAX
                error_list = []
                for field, errors in form.errors.items():
                    error_list.append(f"{field}: {', '.join(errors)}")
                return JsonResponse(
                    {"success": False, "error": "; ".join(error_list)}, status=400
                )

        except Exception as e:
            logger.error(f"Error in AJAX upload_signed: {str(e)}")
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    # GET request - show the form (shouldn't happen for AJAX, but handle gracefully)
    return JsonResponse(
        {"success": False, "error": "GET method not supported for AJAX upload"},
        status=405,
    )


@login_required
def extract_signature_from_document(request, pk):
    """Extract signature from uploaded document"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    if not delivery.signed_document:
        messages.error(request, "No signed document uploaded")
        return redirect("delivery_notes:detail", pk=pk)

    if request.method == "POST":
        try:
            # Get coordinates
            x1 = int(request.POST.get("x1", 0))
            y1 = int(request.POST.get("y1", 0))
            x2 = int(request.POST.get("x2", 0))
            y2 = int(request.POST.get("y2", 0))

            # Validate coordinates
            if x1 >= x2 or y1 >= y2 or x1 < 0 or y1 < 0:
                messages.error(request, "Invalid selection coordinates")
                return redirect("delivery_notes:extract_signature", pk=pk)

            # Load and process image safely
            safe_img, temp_path = safe_load_image(
                delivery.signed_document.path, max_side=2000
            )

            # Ensure coordinates are within image bounds
            img_width, img_height = safe_img.size
            x1 = max(0, min(x1, img_width - 1))
            y1 = max(0, min(y1, img_height - 1))
            x2 = max(x1 + 1, min(x2, img_width))
            y2 = max(y1 + 1, min(y2, img_height))

            # Extract signature region
            signature_region = safe_img.crop((x1, y1, x2, y2))

            # Generate PNG data
            import io, base64

            buffer = io.BytesIO()
            signature_region.save(buffer, format="PNG")
            buffer.seek(0)
            base64_data = base64.b64encode(buffer.getvalue()).decode("utf-8")
            data_url = f"data:image/png;base64,{base64_data}"

            # Save to delivery note
            delivery.digital_signature = data_url
            if not delivery.signed_by:
                delivery.signed_by = "Document Signature"
            if not delivery.signature_date:
                delivery.signature_date = timezone.now()

            delivery.status = "signed"
            delivery.save()

            # Clean up temp files
            try:
                import os, shutil
                from pathlib import Path

                # Remove the temp file
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

                # Also try to remove parent temp directory
                parent_dir = Path(temp_path).parent
                if os.path.exists(parent_dir) and parent_dir.name.startswith("tmp"):
                    shutil.rmtree(parent_dir, ignore_errors=True)
            except Exception as cleanup_error:
                # Just log the error but don't fail the operation
                logger.warning(f"Cleanup error: {cleanup_error}")

            # Regenerate PDF
            generate_delivery_pdf(request, pk)

            messages.success(request, "Signature extracted and saved successfully")
            return redirect("delivery_notes:detail", pk=pk)

        except Exception as e:
            messages.error(request, f"Error extracting signature: {str(e)}")
            return redirect("delivery_notes:extract_signature", pk=pk)

    # GET request - show extraction form
    return render(
        request, "delivery_notes/extract_signature.html", {"delivery": delivery}
    )


@login_required
def convert_to_quote(request, pk):
    """Convert a delivery note to a quote request"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    if delivery.status == "converted":
        messages.warning(
            request, "This delivery note has already been converted to a quote."
        )
        return redirect("delivery_notes:detail", pk=delivery.pk)

    try:
        # Find customer based on company name rather than using a reverse relationship
        customer = Customers.objects.filter(company=delivery.company.company).first()
        if not customer:
            # Create a default customer for this company
            customer = Customers.objects.create(
                company=delivery.company.company,
                customer=delivery.contact_person,
                email=delivery.contact_email,
                number=delivery.contact_phone,
                dateadded=timezone.now(),
            )

        # Generate a unique quote number
        quote_number = generate_unique_quote_number()

        # Create new quote with the signed-in user as rep
        quote = QuoteRequest(
            quote_number=quote_number,
            customer=customer,
            rep=request.user,
            user=request.user,
            assigned_to=request.user,
            description=f"DELIVERY NOTE: {delivery.delivery_number} | {delivery.company.company if delivery.company else ''}",
            status="processed",
            notes=delivery.notes,
            quote_reference=f"Delivery Note: {delivery.delivery_number}",
        )
        quote.save()

        # IMPORTANT: Force the reference field to update
        quote.refresh_from_db()  # Get the latest from DB
        quote.quote_reference = f"Delivery Note: {delivery.delivery_number}"
        quote.save(
            update_fields=["quote_reference"]
        )  # Force this specific field to update
        print(
            f"DEBUG - Quote {quote.id} reference: '{quote.quote_reference}'"
        )  # Add debugging

        # Add this debugging after the quote is saved
        print(f"DEBUG - Quote ID: {quote.id}")
        print(f"DEBUG - Quote Number: {quote.quote_number}")
        print(f"DEBUG - Quote Description: {quote.description}")
        print(f"DEBUG - Quote Reference: {quote.quote_reference}")

        # Optional: Query the database directly to verify
        from django.db import connection

        cursor = connection.cursor()
        cursor.execute(
            f"SELECT quote_reference FROM quotes_quoterequest WHERE id = {quote.id}"
        )
        row = cursor.fetchone()
        print(f"DEBUG - Direct DB Query Result: {row[0] if row else 'NULL'}")

        # Convert delivery items to quote items with proper field population
        for item in delivery.items.all():
            # Handle pricing information safely
            selling_price = (
                item.price if hasattr(item, "price") and item.price else Decimal("0.00")
            )
            cost_price = Decimal("0.00")

            if hasattr(item, "cost_price") and item.cost_price:
                cost_price = item.cost_price
            elif selling_price > 0:
                # Estimate cost price if not available (using a 25% markup)
                cost_price = selling_price / Decimal("1.25")

            # Calculate markup
            markup = 25.0  # Default markup
            if cost_price and selling_price > 0:
                markup = ((selling_price / cost_price) - 1) * 100

            # Get supplier if available
            supplier = None
            if hasattr(item, "supplier") and item.supplier:
                supplier = item.supplier

            # Create quote item
            quote_item = QuoteItem(
                quote=quote,
                description=item.description,  # ✓ SET THE SAME VALUE FOR description
                quantity=item.quantity,
                quote_number=quote.quote_number,
                quote_reference=item.description,  # ✓ Matches description as required
                cost_price=cost_price,
                selling_price=selling_price,
                markup=markup,
                notes=item.notes,
                supplier=supplier,  # ✓ SET SUPPLIER IF AVAILABLE
                included_in_quote=True,  # Default to including in quote
            )
            quote_item.save()

        # Update delivery note
        delivery.status = "converted"
        delivery.converted_to_quote = quote
        delivery.converted_at = timezone.now()
        delivery.save()

        messages.success(
            request,
            f"Delivery note successfully converted to Quote #{quote.quote_number}",
        )
        return redirect("quotes:quote_detail", pk=quote.id)

    except Exception as e:
        messages.error(request, f"Error converting delivery note to quote: {str(e)}")
        return redirect("delivery_notes:detail", pk=delivery.pk)


@login_required
@require_POST
def generate_quote(request, pk):
    """Generate quote from delivery note with selected letterhead"""

    delivery = get_object_or_404(DeliveryNote, pk=pk)
    letterhead = request.POST.get("letterhead", "CNL")

    # Check if all items have prices
    if not delivery.has_all_items_priced():
        messages.error(request, "All items must have pricing before generating a quote")
        # Redirect back to the detail page if triggered from there, or list page otherwise
        referer = request.META.get("HTTP_REFERER")
        if referer and reverse("delivery_notes:detail", kwargs={"pk": pk}) in referer:
            return redirect("delivery_notes:detail", pk=pk)
        return redirect("delivery_notes:list")

    try:
        with transaction.atomic():
            # Create customer if needed
            # ... (existing customer creation logic) ...
            if (
                hasattr(delivery.company, "customer_set")
                and delivery.company.customer_set.exists()
            ):
                customer = delivery.company.customer_set.first()
            else:
                # Create a new customer based on company
                # Ensure Company model is imported or handle appropriately
                # from wfdash.models import Company # Example import
                customer = Customers.objects.create(
                    # Assuming company is a ForeignKey to a Company model in wfdash
                    # If delivery.company IS the Customers model instance, adjust accordingly
                    company=(
                        delivery.company.company
                        if hasattr(delivery.company, "company")
                        else str(delivery.company)
                    ),  # Adjust based on your actual Company model structure
                    customer=delivery.contact_person,
                    email=delivery.contact_email,
                    number=delivery.contact_phone,
                    # Add other required fields for Customers model if any
                    dateadded=timezone.now(),  # Example
                )

            # Create quote with approved status
            quote = QuoteRequest.objects.create(
                customer=customer,
                rep=request.user,
                user=request.user,
                assigned_to=request.user,
                description=f"Quote from Delivery Note {delivery.delivery_number}",
                notes=delivery.notes,
                status="approved",  # Set as approved directly
                quote_number=generate_unique_quote_number(),
                company_letterhead=letterhead,
                # Add quote_reference if needed
                quote_reference=f" {delivery.delivery_number}",
            )

            # Create quote items
            for item in delivery.items.all():
                if item.price and item.price > 0:
                    QuoteItem.objects.create(
                        quote=quote,
                        description=item.description,
                        quantity=item.quantity,
                        selling_price=item.price,
                        cost_price=getattr(item, "cost_price", None),
                        markup=getattr(item, "markup", None),
                        notes=item.notes,
                        included_in_quote=True,  # Ensure items are included
                    )

            # Update delivery status and store reference to quote
            delivery.status = "converted"
            delivery.converted_to_quote = quote  # Store reference to quote
            delivery.save()

            # Generate the PDF for the quote silently in the background
            # You might need to import the PDF generation function from the quotes app
            try:
                # Call the function WITHOUT as_response
                generate_quote_pdf(request, quote.id)  # Removed as_response=False
                logger.info(
                    f"Generated PDF for auto-approved quote {quote.quote_number}"
                )
            except Exception as pdf_error:
                # Log the specific error from PDF generation
                logger.error(
                    f"Could not auto-generate PDF for quote {quote.quote_number}: {pdf_error}",
                    exc_info=True,
                )  # Add exc_info for full traceback
                messages.warning(
                    request,
                    f"Quote {quote.quote_number} created and approved, but PDF generation failed: {pdf_error}",
                )

            # Add success message indicating approval
            messages.success(
                request,
                f"Quote {quote.quote_number} created and automatically approved from Delivery Note {delivery.delivery_number}.",
            )

            # Redirect back to the delivery note list view
            return redirect("delivery_notes:list")

    except Exception as e:
        logger.error(
            f"Error generating quote from delivery {pk}: {str(e)}\n{traceback.format_exc()}"
        )  # Log full traceback
        messages.error(request, f"Error generating quote: {str(e)}")
        # Redirect back to the detail page if triggered from there, or list page otherwise
        referer = request.META.get("HTTP_REFERER")
        if referer and reverse("delivery_notes:detail", kwargs={"pk": pk}) in referer:
            return redirect("delivery_notes:detail", pk=pk)
        return redirect("delivery_notes:list")


@login_required
def view_delivery_pdf(request, pk):
    """View the delivery note PDF in the browser"""
    try:
        delivery = get_object_or_404(DeliveryNote, pk=pk)

        # Generate PDF if it doesn't exist
        if not delivery.pdf_file or not os.path.exists(delivery.pdf_file.path):
            return generate_delivery_pdf(request, pk, download=False)

        # Return existing PDF
        response = HttpResponse(delivery.pdf_file, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="{os.path.basename(delivery.pdf_file.name)}"'
        )

        # Auto-print if requested
        if request.GET.get("print") == "1":
            response.content = response.content.decode("latin-1")
            response.content = response.content.replace(
                "</body>",
                "<script>window.onload = function() { setTimeout(function() { window.print(); }, 1000); }</script></body>",
            )
            response.content = response.content.encode("latin-1")

        return response
    except Exception as e:
        logger.exception("Error viewing PDF")
        messages.error(request, f"Error viewing PDF: {str(e)}")
        return redirect("delivery_notes:detail", pk=pk)


@login_required
def download_delivery_pdf(request, pk):
    """Download the delivery note PDF"""
    try:
        delivery = get_object_or_404(DeliveryNote, pk=pk)

        # Generate PDF if it doesn't exist
        if not delivery.pdf_file or not os.path.exists(delivery.pdf_file.path):
            return generate_delivery_pdf(request, pk, download=True)

        # Return existing PDF for download
        response = HttpResponse(delivery.pdf_file, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="{os.path.basename(delivery.pdf_file.name)}"'
        )
        return response
    except Exception as e:
        logger.exception("Error downloading PDF")
        messages.error(request, f"Error downloading PDF: {str(e)}")
        return redirect("delivery_notes:detail", pk=pk)


@login_required
@require_POST
def update_item_pricing(request, item_id):
    """Update the price of a delivery item regardless of delivery status"""
    try:
        # Get the item regardless of parent delivery status
        item = get_object_or_404(DeliveryItem, id=item_id)

        # Get price values from the request
        try:
            price = Decimal(request.POST.get("price", "0"))
            cost_price = Decimal(request.POST.get("cost_price", "0"))
            markup = Decimal(request.POST.get("markup", "0"))
        except InvalidOperation:
            return JsonResponse(
                {"status": "error", "message": "Invalid price value"}, status=400
            )

        # Get notes field
        notes = request.POST.get("notes", "")

        # Update all fields including notes
        item.price = price
        item.cost_price = cost_price
        item.markup = markup
        item.notes = notes
        item.save()

        # Check if delivery is now ready to process
        check_delivery_ready_status(item.delivery_note)

        # Return success response with all updated values
        return JsonResponse(
            {
                "status": "success",
                "message": "Price updated successfully",
                "price": float(price),
                "cost_price": float(cost_price),
                "markup": float(markup),
                "notes": notes,
                "item_id": item_id,
            }
        )

    except Exception as e:
        logger.error(f"Error updating item price: {str(e)}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_GET
def item_search(request):
    """Search for items by description for autocomplete"""
    try:
        term = request.GET.get("term", "")
        if len(term) < 2:
            return JsonResponse([], safe=False)

        results = []
        now = timezone.now()
        import datetime  # Import the datetime module explicitly

        # Search in DeliveryItem model (keep your existing code)
        delivery_items = DeliveryItem.objects.filter(
            description__icontains=term
        ).distinct()[:15]

        for item in delivery_items:
            # Your existing code for processing delivery items
            # Skip duplicates
            if any(
                r.get("value") == item.description
                and r.get("price")
                and item.price
                and abs(float(r.get("price")) - float(item.price)) < 0.01
                for r in results
            ):
                continue

            # Get company name
            company_name = getattr(
                getattr(getattr(item, "delivery_note", None), "company", None),
                "company",
                "Unknown",
            )

            # Calculate days ago
            days_ago = None
            time_text = "Unknown date"
            if (
                hasattr(item, "delivery_note")
                and item.delivery_note
                and hasattr(item.delivery_note, "delivery_date")
                and item.delivery_note.delivery_date
            ):
                # Fix: Use datetime.date directly, not timezone.datetime.date
                if isinstance(item.delivery_note.delivery_date, datetime.date):
                    days_ago = (now.date() - item.delivery_note.delivery_date).days
                    if days_ago == 0:
                        time_text = "Today"
                    elif days_ago == 1:
                        time_text = "Yesterday"
                    elif days_ago < 30:
                        time_text = f"{days_ago} days ago"
                    elif days_ago < 365:
                        months = days_ago // 30
                        time_text = f"{months} month{'s' if months > 1 else ''} ago"
                    else:
                        years = days_ago // 365
                        time_text = f"{years} year{'s' if years > 1 else ''} ago"

            results.append(
                {
                    "label": item.description,
                    "value": item.description,
                    "full_description": item.description,
                    "price": float(item.price) if item.price else None,
                    "cost_price": (
                        float(item.cost_price)
                        if hasattr(item, "cost_price") and item.cost_price
                        else None
                    ),
                    "markup": None,
                    "company": company_name,
                    "source": "Previous Deliveries",
                    "days_ago": days_ago,
                    "time_text": time_text,
                }
            )

        # IMPLEMENTED: Search Quote Items (you likely have this already)
        try:
            from quotes.models import QuoteItem

            quote_items = (
                QuoteItem.objects.filter(description__icontains=term)
                .distinct()
                .select_related("quote", "quote__customer", "supplier")[:15]
            )

            for item in quote_items:
                # Process each quote item
                # Skip duplicates check...

                company_name = "Unknown"
                if (
                    hasattr(item, "quote")
                    and item.quote
                    and hasattr(item.quote, "customer")
                ):
                    company_name = item.quote.customer.company

                # Calculate days ago...
                days_ago = None
                time_text = "Unknown date"
                if (
                    hasattr(item, "quote")
                    and item.quote
                    and hasattr(item.quote, "created_at")
                ):
                    days_ago = (now.date() - item.quote.created_at.date()).days
                    # Format time_text based on days_ago...

                # Calculate markup
                markup = None
                if (
                    item.cost_price
                    and item.cost_price > 0
                    and item.selling_price
                    and item.selling_price > 0
                ):
                    markup = (
                        (float(item.selling_price) - float(item.cost_price))
                        / float(item.cost_price)
                    ) * 100

                results.append(
                    {
                        "label": item.description,
                        "value": item.description,
                        "full_description": item.description,
                        "price": (
                            float(item.selling_price) if item.selling_price else None
                        ),
                        "cost_price": (
                            float(item.cost_price) if item.cost_price else None
                        ),
                        "markup": markup,
                        "company": company_name,
                        "quote_number": item.quote.quote_number if item.quote else None,
                        "source": "Quote",
                        "days_ago": days_ago,
                        "time_text": time_text,
                    }
                )
        except Exception as e:
            print(f"Error searching QuoteItems: {str(e)}")

        # IMPLEMENTING: Search Stock Items
        try:
            # Import the StockItem model and search for matching items
            from stock_management.models import StockItem

            # Remove 'supplier' from select_related - it doesn't exist on StockItem
            stock_items = (
                StockItem.objects.filter(order_item__description__icontains=term)
                .distinct()
                .select_related("order_item")[:15]  # Only include valid relationships
            )

            for item in stock_items:
                # Skip items without order_item relation
                if not item.order_item:
                    continue

                # Get description from the related order_item
                description = item.order_item.description

                # Skip duplicates with the same price
                selling_price = getattr(item.order_item, "selling_price", None)
                if selling_price and any(
                    r.get("value") == description
                    and r.get("price")
                    and abs(float(r.get("price")) - float(selling_price)) < 0.01
                    for r in results
                ):
                    continue

                # Get supplier name from order_item instead
                supplier_name = "Unknown"
                if hasattr(item.order_item, "supplier") and item.order_item.supplier:
                    supplier_name = (
                        item.order_item.supplier.name
                        if hasattr(item.order_item.supplier, "name")
                        else "Unknown"
                    )

                # Get cost price and calculate markup
                cost_price = getattr(item.order_item, "cost_price", None)
                markup = None
                if (
                    cost_price
                    and cost_price > 0
                    and selling_price
                    and selling_price > 0
                ):
                    markup = (
                        (float(selling_price) - float(cost_price)) / float(cost_price)
                    ) * 100

                # Determine age of item
                days_ago = None
                time_text = "Current Stock"
                if hasattr(item, "updated_at") and item.updated_at:
                    days_ago = (now.date() - item.updated_at.date()).days
                    if days_ago == 0:
                        time_text = "Updated today"
                    elif days_ago == 1:
                        time_text = "Updated yesterday"
                    elif days_ago < 30:
                        time_text = f"Updated {days_ago} days ago"
                    else:
                        months = days_ago // 30
                        time_text = (
                            f"Updated {months} month{'s' if months > 1 else ''} ago"
                        )

                results.append(
                    {
                        "label": description,
                        "value": description,
                        "full_description": description,
                        "price": float(selling_price) if selling_price else None,
                        "cost_price": float(cost_price) if cost_price else None,
                        "markup": markup,
                        "company": supplier_name,
                        "source": "Stock",
                        "days_ago": days_ago,
                        "time_text": time_text,
                    }
                )
        except Exception as e:
            print(f"Error searching StockItems: {str(e)}")
            import traceback

            print(traceback.format_exc())

        # IMPLEMENTING: Search Order Items
        try:
            from orders.models import OrderItem

            order_items = (
                OrderItem.objects.filter(description__icontains=term)
                .distinct()
                .select_related("order", "order__company", "supplier")[:15]
            )

            for item in order_items:
                # Skip duplicates
                selling_price = item.selling_price
                if selling_price and any(
                    r.get("value") == item.description
                    and r.get("price")
                    and abs(float(r.get("price")) - float(selling_price)) < 0.01
                    for r in results
                ):
                    continue

                # Get company name
                company_name = "Unknown"
                if (
                    hasattr(item, "order")
                    and item.order
                    and hasattr(item.order, "company")
                ):
                    company_name = item.order.company.company

                # Calculate days ago
                days_ago = None
                time_text = "Unknown date"
                if (
                    hasattr(item, "order")
                    and item.order
                    and hasattr(item.order, "created_at")
                ):
                    days_ago = (now.date() - item.order.created_at.date()).days
                    if days_ago == 0:
                        time_text = "Today"
                    elif days_ago == 1:
                        time_text = "Yesterday"
                    elif days_ago < 30:
                        time_text = f"{days_ago} days ago"
                    elif days_ago < 365:
                        months = days_ago // 30
                        time_text = f"{months} month{'s' if months > 1 else ''} ago"
                    else:
                        years = days_ago // 365
                        time_text = f"{years} year{'s' if years > 1 else ''} ago"

                # Calculate markup
                markup = None
                if (
                    item.cost_price
                    and item.cost_price > 0
                    and item.selling_price
                    and item.selling_price > 0
                ):
                    markup = (
                        (float(item.selling_price) - float(item.cost_price))
                        / float(item.cost_price)
                    ) * 100

                # Get supplier name
                supplier_name = None
                if hasattr(item, "supplier") and item.supplier:
                    supplier_name = getattr(
                        item.supplier,
                        "name",
                        getattr(item.supplier, "company_name", None),
                    )
                elif hasattr(item.order, "supplier") and item.order.supplier:
                    supplier_name = getattr(
                        item.order.supplier,
                        "name",
                        getattr(item.order.supplier, "company_name", None),
                    )

                results.append(
                    {
                        "label": item.description,
                        "value": item.description,
                        "full_description": item.description,
                        "price": float(selling_price) if selling_price else None,
                        "cost_price": (
                            float(item.cost_price) if item.cost_price else None
                        ),
                        "markup": markup,
                        "company": company_name,
                        "order_number": (
                            item.order.order_number
                            if hasattr(item.order, "order_number")
                            else None
                        ),
                        "source": "Order",
                        "days_ago": days_ago,
                        "time_text": time_text,
                        "supplier_name": supplier_name,
                    }
                )
        except Exception as e:
            print(f"Error searching OrderItems: {str(e)}")

        # NEW CODE: Search in Price List Items
        try:
            from internal_stock.models import PriceListItem

            price_list_items = (
                PriceListItem.objects.filter(
                    Q(description__icontains=term) | Q(part_number__icontains=term)
                )
                .distinct()
                .select_related("price_list", "price_list__supplier")[:15]
            )

            for item in price_list_items:
                # Skip duplicates with the same price
                if item.selling_price and any(
                    r.get("value") == item.description
                    and r.get("price")
                    and abs(float(r.get("price")) - float(item.selling_price)) < 0.01
                    for r in results
                ):
                    continue

                # Get supplier name
                supplier_name = "Unknown"
                if item.price_list and item.price_list.supplier:
                    supplier_name = item.price_list.supplier.suppliername

                # Check price list validity
                is_valid = False
                if item.price_list:
                    today = now.date()
                    is_valid = item.price_list.valid_from <= today and (
                        not item.price_list.valid_until
                        or item.price_list.valid_until >= today
                    )

                # Format validity text and time info
                validity_text = "Valid" if is_valid else "Expired"
                price_list_info = (
                    f"{item.price_list.name} ({item.price_list.year})"
                    if item.price_list
                    else "Unknown List"
                )

                # Time text
                time_text = "Unknown validity"
                if item.price_list:
                    if is_valid:
                        if item.price_list.valid_until:
                            days_remaining = (item.price_list.valid_until - today).days
                            time_text = f"Valid for {days_remaining} more days"
                        else:
                            time_text = "No expiration date"
                    else:
                        if today < item.price_list.valid_from:
                            days_until = (item.price_list.valid_from - today).days
                            time_text = f"Will be valid in {days_until} days"
                        else:
                            days_expired = (today - item.price_list.valid_until).days
                            time_text = f"Expired {days_expired} days ago"

                results.append(
                    {
                        "id": f"price_list_{item.id}",
                        "label": f"{item.part_number or ''} - {item.description} ({price_list_info})",
                        "value": item.description,
                        "full_description": item.description,
                        "price": (
                            float(item.selling_price) if item.selling_price else None
                        ),
                        "cost_price": (
                            float(item.cost_price) if item.cost_price else None
                        ),
                        "markup": float(item.markup) if item.markup else None,
                        "company": supplier_name,
                        "source": f"Price List ({validity_text})",
                        "is_valid_price": is_valid,  # New flag for styling
                        "days_ago": 0,  # Not relevant for price lists
                        "time_text": time_text,
                        "part_number": item.part_number or "",
                        "supplier_name": supplier_name,
                        "supplier_id": (
                            item.price_list.supplier.id
                            if item.price_list and item.price_list.supplier
                            else None
                        ),
                    }
                )
        except Exception as e:
            print(f"Error searching PriceListItems: {str(e)}")
            import traceback

            print(traceback.format_exc())

        # Filter out items without prices
        filtered_results = [
            item
            for item in results
            if (item.get("price") and item["price"] > 0)
            or (item.get("cost_price") and item["cost_price"] > 0)
        ]

        # Sort the filtered results
        filtered_results.sort(
            key=lambda x: (
                # First sort by how closely the term matches
                (
                    0
                    if x["value"].lower() == term.lower()
                    else (
                        1
                        if x["value"].lower().startswith(term.lower())
                        else 2 if term.lower() in x["value"].lower() else 3
                    )
                ),
                # Then by how recent the item is
                x["days_ago"] if x["days_ago"] is not None else 9999,
            )
        )

        return JsonResponse(filtered_results[:15], safe=False)

    except Exception as e:
        import traceback

        print(f"Error in item_search: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def create_from_stock(request):
    """Create a delivery note from stock items"""
    print("Stock model available:", "stock_management" in settings.INSTALLED_APPS)
    print("Orders model available:", "orders" in settings.INSTALLED_APPS)
    if request.method == "POST":
        try:
            item_ids = request.POST.getlist("item_ids", [])
            company_id = request.POST.get("company_id")

            if not item_ids or not company_id:
                messages.error(
                    request, "Missing required parameters: item IDs or company"
                )
                return redirect("stock_management:stock_list")

            company = get_object_or_404(Company, id=company_id)

            # Create new delivery note
            delivery = DeliveryNote.objects.create(
                company=company,
                created_by=request.user,
                delivery_date=timezone.now(),
                status="draft",
            )

            # Create delivery items from stock items
            stock_items = StockItem.objects.filter(id__in=item_ids)
            for stock_item in stock_items:
                DeliveryItem.objects.create(
                    delivery_note=delivery,
                    description=stock_item.order_item.description,
                    quantity=stock_item.verified_quantity,
                    price=(
                        stock_item.order_item.selling_price
                        if hasattr(stock_item.order_item, "selling_price")
                        else None
                    ),
                    notes=f"From Stock Item #{stock_item.id}",
                )

                # Update stock item status
                stock_item.status = "ready_for_delivery"
                stock_item.delivered_in = delivery
                stock_item.save()

            # Generate PDF
            generate_delivery_pdf(request, delivery.pk)

            messages.success(
                request,
                f"Delivery note {delivery.delivery_number} created successfully with {len(item_ids)} items",
            )
            return redirect("delivery_notes:detail", pk=delivery.pk)

        except Exception as e:
            messages.error(request, f"Error creating delivery note: {str(e)}")
            return redirect("stock_management:stock_list")
    else:
        messages.error(request, "Invalid request method")
        return redirect("stock_management:stock_list")


@login_required
def regenerate_pdf_with_signature(request, pk):
    """Regenerate the delivery note PDF with signature"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    # Check if AJAX request - determines if we show modal or direct download
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # Set include_signature to True to include the signature in the PDF
    response = generate_delivery_pdf(
        request, pk, include_signature=True, download=False
    )

    if response:
        # For AJAX requests, return JSON with success and PDF URL
        if is_ajax:
            # Update timestamp to prevent caching
            timestamp = int(timezone.now().timestamp())
            pdf_url = f"{delivery.pdf_file.url}?t={timestamp}"

            return JsonResponse(
                {
                    "success": True,
                    "message": f"PDF for delivery note {delivery.delivery_number} regenerated successfully.",
                    "pdf_url": pdf_url,
                }
            )
        else:
            # For non-AJAX requests, return the PDF directly (backward compatibility)
            messages.success(
                request,
                f"PDF for delivery note {delivery.delivery_number} regenerated successfully with signature.",
            )
            return response
    else:
        # Handle error case
        error_msg = "Failed to regenerate PDF with signature."
        if is_ajax:
            return JsonResponse({"success": False, "message": error_msg})
        else:
            messages.error(request, error_msg)
            return redirect("delivery_notes:detail", pk=pk)


@login_required
def mobile_delivery_actions(request, pk):
    """Mobile-friendly view for QR code actions"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    # Determine if user can access this delivery
    can_access = request.user.is_staff or delivery.created_by == request.user

    return render(
        request,
        "delivery_notes/mobile/delivery_actions.html",
        {
            "delivery": delivery,
            "can_access": can_access,
        },
    )


@login_required
def record_invoice(request, pk):
    try:
        delivery = get_object_or_404(DeliveryNote, pk=pk)
        invoice_number = request.POST.get("invoice_number")

        if invoice_number:
            delivery.invoice_number = invoice_number
            delivery.save()

            # Add a success message
            messages.success(
                request,
                f"Invoice number {invoice_number} recorded successfully for delivery {delivery.delivery_number}",
            )

            # Redirect to list view to refresh the categories
            return redirect("delivery_notes:list")
        else:
            messages.error(request, "Please provide an invoice number")
            return redirect("delivery_notes:detail", pk=pk)
    except Exception as e:
        messages.error(request, f"Error recording invoice: {str(e)}")
        return redirect("delivery_notes:detail", pk=pk)


@login_required
def return_from_quote_generation(request, pk):
    """Handle return from quote PDF generation"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    if delivery.converted_to_quote:
        messages.success(
            request,
            f"Quote {delivery.converted_to_quote.quote_number} created and approved. PDF generated successfully.",
        )

    return redirect("delivery_notes:detail", pk=pk)


@login_required
def get_delivery_items_json(request, pk):
    """Return JSON data for delivery items"""
    try:
        delivery = get_object_or_404(DeliveryNote, pk=pk)
        items = delivery.items.all()

        items_data = []
        for item in items:
            items_data.append(
                {
                    "id": item.id,
                    "description": item.description,
                    "quantity": item.quantity,
                    "price": float(item.price) if item.price else None,
                    "cost_price": float(item.cost_price) if item.cost_price else None,
                    "markup": float(item.markup) if item.markup else None,
                    "notes": item.notes,
                }
            )

        return JsonResponse(
            {"success": True, "delivery_id": delivery.pk, "items": items_data}
        )
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@require_POST
def update_delivery_status(request, pk):
    try:
        delivery = DeliveryNote.objects.get(pk=pk)
        new_status = request.POST.get("status")

        if new_status:
            delivery.save()
            return JsonResponse({"status": "success"})
        else:
            return JsonResponse({"status": "error", "message": "No status provided"})
    except DeliveryNote.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Delivery note not found"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})


@login_required
@require_POST
def request_order_number(request, pk):
    try:
        delivery = get_object_or_404(DeliveryNote, pk=pk)

        # Check if the delivery has a quote and is signed
        if not delivery.converted_to_quote or not delivery.is_signed():
            return JsonResponse(
                {
                    "status": "error",
                    "message": "Delivery must have a quote and be signed",
                }
            )

        # Get email details from form
        to_email = request.POST.get("email_to")
        cc_emails = (
            request.POST.get("email_cc", "").split(",")
            if request.POST.get("email_cc")
            else []
        )
        subject = request.POST.get("email_subject")
        body = request.POST.get("email_body")

        # Check if we need to attach files
        attach_delivery = request.POST.get("attach_delivery") == "on"
        attach_quote = request.POST.get("attach_quote") == "on"

        # Create the email
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
            cc=cc_emails,
        )

        # Attach the delivery note if requested
        if attach_delivery:
            if delivery.signed_document and os.path.exists(
                delivery.signed_document.path
            ):
                # Use the uploaded signed document (prioritize this)
                file_path = delivery.signed_document.path
                original_filename = os.path.basename(file_path)
                # Guess the MIME type based on the file extension
                mime_type, _ = mimetypes.guess_type(file_path)
                if mime_type is None:
                    mime_type = "application/octet-stream"  # Default if type unknown

                with open(file_path, "rb") as f:
                    email.attach(
                        f"Signed_{original_filename}",  # Use original filename (or a variation)
                        f.read(),
                        mime_type,  # Use the guessed MIME type
                    )
            elif delivery.pdf_file and os.path.exists(delivery.pdf_file.path):
                # Fallback to the system-generated PDF if signed doc doesn't exist
                with open(delivery.pdf_file.path, "rb") as f:
                    email.attach(
                        f"Delivery_{delivery.delivery_number}.pdf",
                        f.read(),
                        "application/pdf",
                    )
            else:
                # Only as a last resort, generate a new PDF (without signature)
                try:
                    # Assuming generate_delivery_pdf can return content when as_response=False
                    pdf_content = generate_delivery_pdf(
                        request, pk, as_response=False
                    )  # Consider adding include_signature=False if supported
                    if pdf_content:
                        email.attach(
                            f"Delivery_{delivery.delivery_number}.pdf",
                            pdf_content,
                            "application/pdf",
                        )
                    else:
                        logger.warning(
                            f"Could not generate fallback PDF for delivery {pk}"
                        )
                except Exception as pdf_gen_error:
                    logger.error(
                        f"Error generating fallback PDF for delivery {pk}: {pdf_gen_error}"
                    )

        # Attach the quote if requested
        if attach_quote and delivery.converted_to_quote:
            quote = delivery.converted_to_quote
            if (
                hasattr(quote, "pdf_file")
                and quote.pdf_file
                and os.path.exists(quote.pdf_file.path)
            ):
                # Use the existing quote PDF file
                with open(quote.pdf_file.path, "rb") as f:
                    email.attach(
                        f"Quote_{quote.quote_number}.pdf", f.read(), "application/pdf"
                    )
            else:
                # If no PDF exists, we'll skip it - don't try to generate
                messages.warning(
                    request, f"Could not attach quote PDF - file not found"
                )

        # Send the email
        email.send()

        # Record that an order number was requested
        delivery.order_requests_count += 1
        delivery.last_order_requested_date = timezone.now()
        delivery.last_order_requested_by = request.user
        delivery.save()

        return JsonResponse(
            {"status": "success", "message": "Email sent successfully!"}
        )
    except Exception as e:
        logger.error(
            f"Error in request_order_number for delivery {pk}: {str(e)}\n{traceback.format_exc()}"
        )  # Added traceback logging
        return JsonResponse({"status": "error", "message": str(e)})


@login_required
def get_delivery_info(request, pk):
    try:
        delivery = get_object_or_404(DeliveryNote, pk=pk)

        data = {
            "delivery_number": delivery.delivery_number,
            "quote_number": (
                delivery.converted_to_quote.quote_number
                if delivery.converted_to_quote
                else None
            ),
            "company": delivery.company.company if delivery.company else None,
        }

        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})


@login_required
def regenerate_quote(request, pk):
    """Regenerate a quote that failed to generate properly"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    # Check if delivery has been converted but the quote is missing or broken
    if not delivery.converted_to_quote:
        messages.error(
            request, "This delivery note has not been converted to a quote yet."
        )
        return redirect("delivery_notes:detail", pk=pk)

    try:
        # Get the existing quote
        quote = delivery.converted_to_quote

        # Regenerate the quote PDF - remove the problematic parameter
        from quotes.views import generate_quote_pdf

        # Check the signature of the generate_quote_pdf function before calling it
        import inspect

        sig = inspect.signature(generate_quote_pdf)
        if "as_response" in sig.parameters:
            # If the function expects as_response parameter
            generate_quote_pdf(request, quote.id, as_response=False)
        else:
            # If it doesn't expect this parameter, call it without
            generate_quote_pdf(request, quote.id)

        messages.success(
            request, f"Quote {quote.quote_number} regenerated successfully."
        )

    except Exception as e:
        logger.error(f"Error regenerating quote for delivery {pk}: {str(e)}")
        messages.error(request, f"Error regenerating quote: {str(e)}")

    # Redirect back to delivery list
    return redirect("delivery_notes:list")


@login_required
@require_POST
@transaction.atomic
def ajax_save_bulk_pricing_view(request):
    """Handles saving pricing for multiple delivery items via AJAX from form data."""
    try:
        # Parse form data using request.POST
        item_ids = request.POST.getlist("item_ids[]")  # Get list of item IDs
        delivery_id = request.POST.get("delivery_id")  # Get the delivery ID

        if not item_ids:
            return JsonResponse(
                {"success": False, "error": "No item IDs provided"}, status=400
            )

        updated_items_count = 0
        errors = []
        delivery_note = None
        if delivery_id:
            try:
                delivery_note = DeliveryNote.objects.get(id=delivery_id)
            except DeliveryNote.DoesNotExist:
                logger.warning(
                    f"Delivery note ID {delivery_id} provided but not found during bulk save."
                )
                # Continue processing items but won't update delivery status

        for item_id in item_ids:
            try:
                item = DeliveryItem.objects.get(id=item_id)

                # Construct keys for form data
                cost_key = f"cost_price_{item_id}"
                markup_key = f"markup_{item_id}"
                price_key = f"price_{item_id}"
                notes_key = (
                    f"notes_{item_id}"  # Assuming notes are still sent, even if hidden
                )

                # Get values, providing defaults for empty strings
                cost_str = request.POST.get(cost_key, "")
                markup_str = request.POST.get(markup_key, "")
                price_str = request.POST.get(price_key, "")
                notes = request.POST.get(notes_key, "")

                # Convert to Decimal, handling empty strings and potential errors
                try:
                    cost_price = Decimal(cost_str) if cost_str else None
                    markup = Decimal(markup_str) if markup_str else None
                    price = Decimal(price_str) if price_str else None
                except InvalidOperation:
                    errors.append(f"Invalid number format for item {item_id}.")
                    continue  # Skip this item

                # Update item fields
                item.cost_price = cost_price
                item.markup = markup
                item.price = price
                item.notes = notes  # Update notes as well
                item.save()
                updated_items_count += 1

                # Associate with delivery note if found
                if delivery_note and item.delivery_note != delivery_note:
                    logger.warning(
                        f"Item {item_id} belongs to a different delivery note ({item.delivery_note_id}) than expected ({delivery_id})."
                    )
                    # Decide how to handle this - maybe add to errors? For now, just log.

            except DeliveryItem.DoesNotExist:
                errors.append(f"Item ID {item_id} not found.")
            except Exception as e:
                logger.error(f"Error updating item {item_id} during bulk save: {e}")
                errors.append(f"Error processing item {item_id}: {e}")

        # After loop, check delivery status if applicable
        if delivery_note:
            check_delivery_ready_status(
                delivery_note
            )  # Make sure this function is defined correctly

        if errors:
            return JsonResponse(
                {
                    "success": False,
                    "error": f"Completed with errors. Updated {updated_items_count} items. Errors: {'; '.join(errors)}",
                    "updated_count": updated_items_count,
                },
                status=207,
            )  # 207 Multi-Status might be appropriate

        return JsonResponse(
            {
                "success": True,
                "message": f"Successfully updated {updated_items_count} items.",
                "updated_count": updated_items_count,
                "delivery_id": delivery_id,
            }
        )

    except Exception as e:
        logger.exception(
            "Error during bulk item price update (outer try):"
        )  # Log full traceback
        return JsonResponse(
            {"success": False, "error": f"An unexpected error occurred: {str(e)}"},
            status=500,
        )
