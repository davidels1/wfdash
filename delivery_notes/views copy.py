import os
import base64
import logging
import tempfile
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
        raise ValueError(f"File too large: {file_size / (1024*1024):.1f}MB")

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
    """Generate a unique quote number for quotes created from delivery notes"""
    today = timezone.now().date()
    prefix = f'Q{today.strftime("%y%m%d")}'

    latest_quote = (
        QuoteRequest.objects.filter(quote_number__startswith=prefix)
        .order_by("-quote_number")
        .first()
    )

    if latest_quote:
        try:
            last_num = int(latest_quote.quote_number[len(prefix) :])
            new_num = last_num + 1
        except ValueError:
            new_num = 1
    else:
        new_num = 1

    return f"{prefix}{new_num:03d}"


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
            message = f"""Dear {delivery.contact_person or 'Customer'},

Thank you for signing our delivery note.

Your delivery note number is: {delivery.delivery_number}
Date: {delivery.delivery_date.strftime('%d %B %Y')}

A copy of the signed delivery note is attached for your records.

If you have any questions about this delivery, please contact us.

Thank you for your business,
{delivery.created_by.get_full_name() if delivery.created_by else 'WF Sales Team'}
WF Group of Companies
"""
        elif email_type == "paper_signed":
            message = f"""Dear Team,

A paper-signed delivery note has been uploaded to the system.

Delivery Note: {delivery.delivery_number}
Date: {delivery.delivery_date.strftime('%d %B %Y')}
Customer: {delivery.company.company}
Signed By: {delivery.signed_by or "Unknown"}
Order Number: {delivery.customer_order_number or "Not provided"}

Both the original delivery note and the scanned signed copy are attached.

Uploaded by: {request.user.get_full_name() if request and request.user else "Unknown"}
"""
        else:  # confirmation or default
            message = f"""Dear {delivery.contact_person or 'Customer'},

Thank you for receiving our delivery.

Delivery Number: {delivery.delivery_number}
Date: {delivery.delivery_date.strftime('%d %B %Y')}
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


def generate_delivery_pdf(request, pk, include_signature=True, download=False):
    """
    Comprehensive PDF generator for delivery notes

    Parameters:
    - request: The HTTP request
    - pk: The primary key of the delivery note
    - include_signature: Whether to include signature in the PDF
    - download: Whether to download the PDF or view in browser

    Returns:
    - HttpResponse for PDF or redirection
    """
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
        img = PILImage.new("RGB", (200, 100), color=(255, 255, 255))
        img.save(temp_logo)
        logo_path = temp_logo

    # Header with logo and company info
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
            Image(logo_path, width=2.0 * inch, height=0.30 * inch),
        ]
    ]

    header_table = Table(header_data, colWidths=[4 * inch, 4 * inch])
    header_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 20),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 20))

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
    if any(item.price is not None and item.price > 0 for item in delivery.items.all()):
        # If any prices exist, show price columns
        table_data = [["Description", "Quantity", "Unit Price", "Total", "Notes"]]

        # Calculate grand total
        grand_total = Decimal("0.00")

        # Add items
        for item in delivery.items.all():
            item_total = None
            if item.price is not None:
                item_total = item.price * item.quantity
                grand_total += item_total

            description_text = item.description
            description_paragraph = Paragraph(description_text, styles["Normal"])

            table_data.append(
                [
                    description_paragraph,
                    str(item.quantity),
                    f"R {item.price:,.2f}" if item.price is not None else "-",
                    f"R {item_total:,.2f}" if item_total is not None else "-",
                    Paragraph(item.notes or "", styles["Normal"]),
                ]
            )

        # Add totals rows - match PO style
        vat_amount = grand_total * Decimal("0.15")
        table_data.extend(
            [
                ["", "", "Subtotal:", f"R {grand_total:,.2f}", ""],
                ["", "", "VAT (15%):", f"R {vat_amount:,.2f}", ""],
                ["", "", "Total:", f"R {(grand_total + vat_amount):,.2f}", ""],
            ]
        )

        # Create table with column widths
        items_table = Table(
            table_data,
            colWidths=[3.5 * inch, 0.8 * inch, 1.2 * inch, 1.2 * inch, 1.3 * inch],
        )

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
                    ("BACKGROUND", (0, 1), (-1, -4), colors.white),
                    ("ALIGN", (1, 1), (-1, -4), "RIGHT"),  # Right-align numeric columns
                    ("ALIGN", (0, 1), (0, -4), "LEFT"),  # Left-align description
                    ("ALIGN", (-1, 1), (-1, -4), "LEFT"),  # Left-align notes
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    # Gridlines
                    ("GRID", (0, 0), (-1, -4), 0.25, colors.grey),
                    # Total rows styling
                    ("LINEABOVE", (-2, -3), (-1, -3), 1, colors.grey),
                    ("LINEABOVE", (-2, -1), (-1, -1), 2, colors.HexColor("#e76240")),
                    ("FONTNAME", (-2, -1), (-1, -1), "Helvetica-Bold"),
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
    else:
        # If no prices, use simplified columns
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
    if include_signature and delivery.is_signed() and delivery.digital_signature:
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

    # Generate QR code URL with the delivery ID
    base_url = settings.BASE_URL  # Add this to your settings.py
    qr_url = f"{base_url}/delivery/{delivery.id}/mobile-actions/"

    # Create QR code and add to PDF
    qr_buffer = generate_qr_code(qr_url)
    qr_img = Image(qr_buffer, width=1.5 * inch, height=1.5 * inch)

    # Add it after signature section
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("<b>SCAN FOR ACTIONS</b>", styles["Heading3"]))
    elements.append(Paragraph("Scan to sign, upload, or view", styles["Normal"]))

    # Center QR code with proper spacing
    qr_img.hAlign = "CENTER"
    elements.append(qr_img)

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

    # Skip returning PDF response if requested (avoids redirecting to PDF view)
    if hasattr(request, "_skip_response") and request._skip_response:
        return None

    # Return PDF response
    response = HttpResponse(pdf_value, content_type="application/pdf")

    # Set disposition based on download flag
    if download:
        response["Content-Disposition"] = f'attachment; filename="{pdf_filename}"'
    else:
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
    """Function-based view for delivery note list (fallback)"""
    view = DeliveryNoteListView.as_view()
    return view(request)


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
                delivery.save()

                formset = DeliveryItemFormSet(request.POST, instance=delivery)
                if formset.is_valid():
                    formset.save()

                    # Generate PDF
                    generate_delivery_pdf(request, delivery.pk)

                    messages.success(
                        request,
                        f"Delivery note {delivery.delivery_number} created successfully.",
                    )
                    return redirect("delivery_notes:detail", pk=delivery.pk)
                else:
                    for form_errors in formset.errors:
                        for field, error in form_errors.items():
                            messages.error(request, f"{field}: {error[0]}")
        else:
            for field, error in form.errors.items():
                messages.error(request, f"{field}: {error[0]}")

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
                        for field, error in form_errors.items():
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
                generate_delivery_pdf(request, pk, include_signature=True)
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
                # Get values from the form
                signed_document = form.cleaned_data["signed_document"]
                signed_by = form.cleaned_data["signed_by"]
                customer_order_number = form.cleaned_data["customer_order_number"]

                # Update the delivery note
                delivery.signed_document = signed_document
                delivery.signed_by = signed_by
                delivery.customer_order_number = customer_order_number
                delivery.signature_date = timezone.now()
                delivery.status = "signed"

                # Set digital_signature to empty string to avoid NULL issues
                if not delivery.digital_signature:
                    delivery.digital_signature = ""

                delivery.save()

                # Generate a new PDF without including the signature image
                generate_delivery_pdf(request, pk, include_signature=False)

                # Send notification email
                send_delivery_email(delivery, "paper_signed", request=request)

                messages.success(
                    request,
                    f"Signed document uploaded successfully. Signed by: {signed_by or 'Unknown'}",
                )
                return redirect("delivery_notes:detail", pk=delivery.pk)

            except Exception as e:
                messages.error(request, f"Error uploading document: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

    # For GET request, show the upload form
    context = {"form": UploadSignatureForm(), "delivery": delivery}
    return render(request, "delivery_notes/upload_signature.html", context)


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
    """Convert a delivery note to a quote"""
    delivery = get_object_or_404(DeliveryNote, pk=pk)

    try:
        with transaction.atomic():
            # Find or create a customer based on the delivery note information
            customer = None
            try:
                # Try to find a customer with matching company name
                customer = Customers.objects.filter(
                    company__iexact=delivery.company.company
                ).first()
            except Exception as e:
                logger.error(f"Error finding customer: {str(e)}")

            # If no customer found, create a default one
            if not customer:
                customer_name = f"Delivery {delivery.delivery_number}"
                if delivery.contact_person:
                    customer_name = delivery.contact_person

                try:
                    # Create a new customer
                    customer = Customers.objects.create(
                        customer=customer_name,
                        email=delivery.contact_email or "",
                        number=delivery.contact_phone or "",
                        company=delivery.company.company,
                        dateadded=timezone.now(),
                    )
                except Exception as e:
                    logger.error(f"Error creating customer: {str(e)}")
                    # If customer creation fails, use None - the model should allow null

            # Create the quote
            quote = QuoteRequest.objects.create(
                quote_number=generate_unique_quote_number(),
                customer=customer,  # Use the found or created customer
                rep=request.user,
                description=f"Converted from Delivery Note #{delivery.delivery_number}",
                notes=delivery.notes,
                status="processed",
                company_letterhead="CNL",  # Default letterhead
                user=request.user,
            )

            # Copy items from delivery note to quote
            for item in delivery.items.all():
                QuoteItem.objects.create(
                    quote=quote,
                    description=item.description,
                    quantity=item.quantity,
                    notes=item.notes,
                    selling_price=item.price or 0,
                    cost_price=0,  # Default cost price
                    markup=0,  # Default markup
                )

            # Update delivery status
            delivery.status = "converted"
            delivery.save()

            messages.success(
                request, f"Delivery note converted to Quote #{quote.quote_number}"
            )
            return redirect("quotes:quote_detail", pk=quote.pk)

    except Exception as e:
        logger.error(f"Error converting delivery to quote: {str(e)}")
        messages.error(request, f"Error converting to quote: {str(e)}")
        return redirect("delivery_notes:detail", pk=pk)


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

        # Search in DeliveryItem model
        delivery_items = DeliveryItem.objects.filter(
            description__icontains=term
        ).distinct()[:15]

        for item in delivery_items:
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
            ):
                if isinstance(item.delivery_note.delivery_date, timezone.datetime.date):
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

            # Get cost price and markup
            cost_price = (
                float(item.cost_price)
                if hasattr(item, "cost_price") and item.cost_price
                else None
            )
            markup = None
            if cost_price and item.price:
                markup = ((float(item.price) - cost_price) / cost_price) * 100

            results.append(
                {
                    "id": item.id,
                    "label": item.description,
                    "value": item.description,
                    "price": float(item.price) if item.price else None,
                    "cost_price": cost_price,
                    "markup": markup,
                    "company": company_name,
                    "source": "Previous Deliveries",
                    "days_ago": days_ago,
                    "time_text": time_text,
                }
            )

        # Try to get items from other sources (OrderItem, StockItem)
        # This code follows the same pattern for each model

        # Sort results
        results.sort(
            key=lambda x: (
                (
                    0
                    if x.get("value", "").lower().startswith(term.lower())
                    else (1 if term.lower() in x.get("value", "").lower() else 2)
                ),
                x.get("days_ago", 9999) if x.get("days_ago") is not None else 9999,
            )
        )

        return JsonResponse(results[:15], safe=False)

    except Exception as e:
        logger.exception(f"Error in item_search: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def create_from_stock(request):
    """Create a delivery note from stock items"""
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
