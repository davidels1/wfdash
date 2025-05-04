from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone
from django.contrib import messages
from .models import QuoteRequest, EmailClickTracker
from uuid import uuid4
from django.urls import reverse


@login_required
def email_quote(request, quote_id):
    """Endpoint to send a quote email"""
    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "Only POST requests are allowed"}
        )

    try:
        # Get form data
        letterhead = request.POST.get("letterhead", "CNL")
        selected_items = request.POST.get("items", "")
        to_email = request.POST.get("to", "")
        cc_email = request.POST.get("cc", "")
        bcc_email = request.POST.get("bcc", "")
        subject = request.POST.get("subject", "")
        body = request.POST.get("body", "")
        update_status = request.POST.get("update_status") == "true"

        # DEBUG: Print received parameters
        print(
            f"Email Parameters: to={to_email}, cc={cc_email}, bcc={bcc_email}, subject={subject[:20]}..."
        )
        print(f"Letterhead: {letterhead}, Update Status: {update_status}")

        # Validate email
        if not to_email:
            return JsonResponse(
                {"status": "error", "message": "Recipient email is required"}
            )

        # Get the quote object
        quote = get_object_or_404(QuoteRequest, id=quote_id)

        # Determine which PDF to use
        pdf_file = None
        if letterhead == "CNL":
            if hasattr(quote, "cnl_pdf_file") and quote.cnl_pdf_file:
                pdf_file = quote.cnl_pdf_file
            else:
                pdf_file = quote.pdf_file
        else:
            pdf_file = quote.pdf_file

        if not pdf_file:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "PDF file not found. Please generate the quote PDF first.",
                }
            )

        try:
            # Generate tracking ID
            tracking_id = str(uuid4())
            quote.email_tracking_id = tracking_id

            # Create tracking URL for open tracking
            tracking_url = request.build_absolute_uri(
                reverse("quotes:track_email_open", kwargs={"tracking_id": tracking_id})
            )

            # Add tracking pixel to email body (make it HTML)
            tracking_pixel = f'<img src="{tracking_url}" width="1" height="1" alt="" style="display:none" />'

            # Convert body to HTML if it's not already
            if not body.strip().startswith("<"):
                # Simple conversion of plain text to HTML
                html_body = body.replace("\n", "<br>")
                html_body = (
                    f'<div style="font-family: Arial, sans-serif;">{html_body}</div>'
                )
            else:
                html_body = body

            # Add tracking pixel to HTML body
            html_body = f"{html_body}\n{tracking_pixel}"

            # Create email message with HTML content
            email = EmailMessage(
                subject=subject,
                body=html_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[to_email] if to_email else [],
                cc=[cc_email] if cc_email else [],
                bcc=[bcc_email] if bcc_email else [],
            )
            email.content_subtype = "html"  # Main content is now HTML

            # Attach the PDF
            email.attach_file(pdf_file.path)

            # Actually send the email
            print("Attempting to send email...")
            email.send(fail_silently=False)
            print(f"Email sent successfully to {to_email}")

            # Optional: mark as emailed if requested
            if update_status:
                # Update quote status
                quote.status = "emailed"
                quote.email_delivered = True
                quote.email_delivered_at = timezone.now()
                quote.email_subject = subject
                quote.email_body = html_body
                quote.save()
                print(f"Quote {quote_id} marked as emailed")

            return JsonResponse(
                {"status": "success", "message": "Email sent successfully"}
            )

        except Exception as e:
            import traceback

            print(f"Email sending error: {str(e)}")
            print(traceback.format_exc())
            return JsonResponse(
                {"status": "error", "message": f"Failed to send email: {str(e)}"}
            )

    except Exception as e:
        import traceback

        print(f"General error in email_quote: {str(e)}")
        print(traceback.format_exc())
        return JsonResponse({"status": "error", "message": str(e)})


@login_required
def email_quote_info(request, quote_id):
    """Get email information for a quote"""
    quote = get_object_or_404(QuoteRequest, id=quote_id)
    letterhead = request.GET.get("letterhead", "CNL")

    # Prepare email content
    company_name = quote.customer.company if quote.customer else "Customer"
    email_to = quote.customer.email if quote.customer else ""

    # Get rep email if available
    rep_email = ""
    if quote.rep:
        rep_email = quote.rep.email

    # Create email body with appropriate letterhead
    if letterhead == "CNL":
        company_signature = "CNL Mining Supplies"
        sender_email = "quotes@wfsales.co.za"
    else:
        company_signature = "Isherwood Mining Supplies"
        sender_email = "quotes@wfsales.co.za"

    subject = f"Quotation {quote.quote_number} from {letterhead} TO: {quote.customer.customer}"
    body = f"""Dear {company_name},

Thank you for your enquiry. Please find attached our quotation {quote.quote_number}.

Should you have any questions or require further information, please don't hesitate to contact us.

Kind regards,
{company_signature} Team
{sender_email}
"""

    return JsonResponse(
        {
            "status": "success",
            "email_data": {
                "to": email_to,
                "rep_email": rep_email,
                "subject": subject,
                "body": body,
                "quote_number": quote.quote_number,
            },
        }
    )


@login_required
def update_quote_status(request, quote_id):
    """Update a quote's status"""
    from django.views.decorators.http import require_POST
    import json

    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "Only POST requests allowed"}
        )

    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id)

        # Parse the JSON data
        try:
            data = json.loads(request.body)
            new_status = data.get("status")
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON"})

        # Validate the status
        valid_statuses = [
            "new",
            "claimed",
            "processed",
            "emailed",
            "complete",
            "cancelled",
        ]
        if new_status not in valid_statuses:
            return JsonResponse(
                {"status": "error", "message": f"Invalid status: {new_status}"}
            )

        # Update the quote status
        quote.status = new_status

        # If marking as emailed, set the email timestamp
        if new_status == "emailed":
            from django.utils import timezone

            # Only set these fields if they exist on the model
            if hasattr(quote, "email_sent_at"):
                quote.email_sent_at = timezone.now()

            if hasattr(quote, "email_sent_by"):
                quote.email_sent_by = request.user.username

        quote.save()

        return JsonResponse(
            {"status": "success", "message": f"Quote status updated to {new_status}"}
        )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})


# Add a new view to track email opens


def track_email_open(request, tracking_id):
    """
    Track when an email is opened using a tracking pixel
    """
    try:
        quote = QuoteRequest.objects.get(email_tracking_id=tracking_id)

        # Update the quote with open information
        if not quote.email_opened:
            quote.email_opened = True
            quote.email_opened_at = timezone.now()
            quote.save(update_fields=["email_opened", "email_opened_at"])

            print(
                f"Email for quote #{quote.quote_number} was opened at {quote.email_opened_at}"
            )

        # Return a transparent 1x1 pixel GIF
        transparent_pixel = b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"
        return HttpResponse(transparent_pixel, content_type="image/gif")

    except QuoteRequest.DoesNotExist:
        # Still return a pixel even if tracking ID is invalid
        transparent_pixel = b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"
        return HttpResponse(transparent_pixel, content_type="image/gif")


# Add a new view to track email link clicks


def track_email_click(request, tracking_id):
    """
    Track when a link in an email is clicked
    """
    try:
        # Get the quote
        quote = QuoteRequest.objects.get(email_tracking_id=tracking_id)

        # Get the URL to redirect to
        redirect_url = request.GET.get("url", "")

        # Log the click
        from .models import EmailClickTracker

        EmailClickTracker.objects.create(
            quote=quote,
            clicked_url=redirect_url,
            clicked_at=timezone.now(),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            ip_address=request.META.get("REMOTE_ADDR", ""),
        )

        # Redirect to the original URL
        return redirect(redirect_url)

    except QuoteRequest.DoesNotExist:
        # If the tracking ID is invalid, redirect to homepage
        return redirect("/")


# Rewrite URLs in your email to go through a redirect


def add_click_tracking(body, quote_id, tracking_id, base_url):
    """
    Parse the email body and replace links with tracking redirects
    """
    import re
    from urllib.parse import quote_plus

    # Regular expression to find links
    link_pattern = r'href=[\'"]?([^\'" >]+)'

    def replace_link(match):
        original_url = match.group(1)
        encoded_url = quote_plus(original_url)
        tracking_url = f"{base_url}/quotes/track_click/{tracking_id}/?url={encoded_url}&quote_id={quote_id}"
        return f'href="{tracking_url}"'

    # Replace all links in the body
    return re.sub(link_pattern, replace_link, body)


# Add these new views


@login_required
def email_tracking_dashboard(request):
    """
    Email tracking dashboard showing all emails
    """
    # Get quotes with 'emailed' status
    quotes = QuoteRequest.objects.filter(status="emailed").order_by("-created_at")

    # Calculate statistics
    total_emails = quotes.count()
    opened_emails = quotes.filter(email_opened=True).count()
    total_clicks = EmailClickTracker.objects.count()

    open_rate = 0
    if total_emails > 0:
        open_rate = round((opened_emails / total_emails) * 100)

    context = {
        "quotes": quotes,
        "total_emails": total_emails,
        "opened_emails": opened_emails,
        "total_clicks": total_clicks,
        "open_rate": open_rate,
    }

    return render(request, "quotes/email_tracking.html", context)


@login_required
def email_tracking_detail(request, quote_id):
    """
    Detailed email tracking for a specific quote
    """
    quote = get_object_or_404(QuoteRequest, id=quote_id)

    context = {"quote": quote}

    return render(request, "quotes/email_tracking_detail.html", context)


@login_required
def email_form(request, quote_id):
    """Show email form after approval if needed"""
    quote = get_object_or_404(QuoteRequest, id=quote_id)
    approved = request.GET.get("approved") == "true"

    # Get default email data
    letterhead = quote.company_letterhead

    # Get email data from the email_quote_info endpoint
    email_data = {}
    try:
        # Use existing function to get email data
        company_name = quote.customer.company if quote.customer else "Customer"
        email_to = quote.customer.email if quote.customer else ""

        # Get rep email if available
        rep_email = ""
        if quote.rep:
            rep_email = quote.rep.email

        # Create email body with appropriate letterhead
        if letterhead == "CNL":
            company_signature = "CNL Mining Supplies"
            sender_email = "quotes@wfsales.co.za"
        else:
            company_signature = "Isherwood Mining Supplies"
            sender_email = "quotes@wfsales.co.za"

        subject = f"Quotation {quote.quote_number} from {letterhead}"
        body = f"""Dear {company_name},

Thank you for your enquiry. Please find attached our quotation {quote.quote_number}.

Should you have any questions or require further information, please don't hesitate to contact us.

Kind regards,
{company_signature} Team
{sender_email}
"""
        email_data = {
            "to": email_to,
            "rep_email": rep_email,
            "subject": subject,
            "body": body,
            "quote_number": quote.quote_number,
        }
    except Exception as e:
        messages.error(request, f"Error preparing email: {str(e)}")

    context = {"quote": quote, "approved": approved, "email_data": email_data}

    return render(request, "quotes/email_form.html", context)
