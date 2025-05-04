from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.urls import reverse
from .models import QuoteRequest


def prepare_quote_email(quote_id, letterhead, selected_items=None):
    """
    Prepares email data for a quote without modifying any models.
    This is a pure utility function that doesn't change database state.
    """
    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id)

        # Create email content
        company_name = quote.customer.company if quote.customer else "Customer"
        email_to = quote.customer.email if quote.customer else ""

        subject = f"Quotation {quote.quote_number} from {letterhead} TO: quote.customer.customer"

        # Create email body with appropriate letterhead
        if letterhead == "CNL":
            company_signature = "CNL Mining Supplies"
            sender_email = "quotes@wfsales.co.za"
        else:
            company_signature = "Isherwood Mining Supplies"
            sender_email = "quotes@wfsales.co.za"

        body = f"""Dear {company_name},

Thank you for your enquiry. Please find attached our quotation {quote.quote_number}.

Should you have any questions or require further information, please don't hesitate to contact us.

Kind regards,
{company_signature} Team
{sender_email}
"""

        # Generate the PDF filename
        pdf_filename = f"Quote-{quote.quote_number}.pdf"

        # Create a direct download URL for the PDF
        if letterhead == "CNL":
            pdf_url = reverse("quotes:generate_cnl_quote_pdf", args=[quote_id])
        else:
            pdf_url = reverse("quotes:generate_isherwood_quote_pdf", args=[quote_id])

        # Add selected items parameter if provided
        if selected_items:
            pdf_url += f"?items={selected_items}"

        # Return email data
        return {
            "status": "success",
            "email_data": {
                "to": email_to,
                "subject": subject,
                "body": body,
                "pdf_url": pdf_url,
                "pdf_filename": pdf_filename,
                "quote_number": quote.quote_number,
                "company": company_name,
                "sender": sender_email,
            },
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def mark_quote_as_emailed(quote_id, email_data):
    """
    Updates a quote to mark it as emailed.
    This is separated from the preparation function to allow for easy toggling.
    """
    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id)

        # Update the quote with email details
        quote.email_sent_at = timezone.now()

        # Only update these fields if they exist and have values
        if hasattr(quote, "email_subject") and email_data.get("subject"):
            quote.email_subject = email_data.get("subject", "")

        if hasattr(quote, "email_body") and email_data.get("body"):
            quote.email_body = email_data.get("body", "")

        # Always update the status to 'emailed'
        quote.status = "emailed"
        quote.save()

        return True
    except Exception as e:
        print(f"Error marking quote as emailed: {str(e)}")
        return False
