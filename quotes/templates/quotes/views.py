from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from django.utils import timezone
from django.template.loader import render_to_string
from django.core.paginator import Paginator
from datetime import timedelta
from django import forms

from django.db import models, IntegrityError  # Add IntegrityError here
from django.conf import settings

from .models import QuoteRequest, QuoteItem, QuoteAttachment
from .forms import QuoteRequestForm, QuoteItemFormSet
from wfdash.models import Suppliers, Company  # Add this import
from .models import VoiceNote  # Import the VoiceNote model

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
)  # Add Image here
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from io import BytesIO
from django.core.files.base import ContentFile
import os
from decimal import Decimal, InvalidOperation

from .utils import is_mobile
from quotes.utils import generate_unique_quote_number

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from django.views.decorators.http import require_http_methods
import json
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import ensure_csrf_cookie


class QuoteListView(LoginRequiredMixin, ListView):
    model = QuoteRequest
    template_name = "quotes/quote_list.html"
    context_object_name = "quotes"
    login_url = "//accounts/login-v3/"


@login_required
def quote_list(request):
    """Display quotes based on user's group membership, with comprehensive search."""
    is_admin = (
        request.user.is_superuser or request.user.groups.filter(name="ADMIN").exists()
    )
    is_quoter = request.user.groups.filter(name="QUOTERS").exists()
    is_rep = request.user.groups.filter(name="REP").exists()
    is_buyer = request.user.groups.filter(name="BUYER").exists()

    # Get base queryset with all related fields to avoid N+1 queries
    if is_admin or is_quoter or is_buyer:
        quotes = QuoteRequest.objects.select_related(
            "customer", "assigned_to", "rep"
        ).prefetch_related("items")
    elif is_rep:
        quotes = (
            QuoteRequest.objects.filter(rep=request.user)
            .select_related("customer", "assigned_to", "rep")
            .prefetch_related("items")
        )
    else:
        quotes = QuoteRequest.objects.none()

    search_query = request.GET.get("search", "")
    if search_query:
        quotes = quotes.filter(
            Q(quote_number__icontains=search_query)
            | Q(customer__company__icontains=search_query)
            | Q(customer__customer__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(rep__first_name__icontains=search_query)
            | Q(rep__last_name__icontains=search_query)
            | Q(items__description__icontains=search_query)
            | Q(items__notes__icontains=search_query)
            | Q(items__quantity__icontains=search_query)
            | Q(notes__icontains=search_query)
            | Q(status__icontains=search_query)
        ).distinct()

    quotes = quotes.order_by(
        "-created_at"
    )  # Sort all quotes by creation date, newest first

    # Group quotes by status
    quotes_by_status = {}

    # Define ordered status mapping (display_name: internal_status)
    status_mapping = {
        "New": "new",
        "Claimed": "claimed",
        "Processed": "processed",
        "Complete": "complete",
        "Cancelled": "cancelled",
    }

    # Initialize all status categories with empty data
    for display_name in status_mapping.keys():
        quotes_by_status[display_name] = {"quotes": [], "count": 0, "total_value": 0}

    for quote in quotes:
        # Map internal status to display name
        for display_name, internal_status in status_mapping.items():
            if quote.status == internal_status:
                status = display_name
                break
        else:
            # If status not found in mapping, use capitalized status as fallback
            status = quote.status.capitalize()

        # Add quote to appropriate status group
        if status not in quotes_by_status:
            quotes_by_status[status] = {"quotes": [], "count": 0, "total_value": 0}

        quotes_by_status[status]["quotes"].append(quote)
        quotes_by_status[status]["count"] += 1
        try:
            total = quote.get_total()
            quotes_by_status[status]["total_value"] += total if total else 0
        except:
            # Handle any potential errors when calculating total
            continue

    # Sort quotes within each status group
    for status in quotes_by_status:
        quotes_by_status[status]["quotes"] = sorted(
            quotes_by_status[status]["quotes"],
            key=lambda q: q.created_at,
            reverse=True,  # Newest first
        )

    # Remove empty status categories
    quotes_by_status = {k: v for k, v in quotes_by_status.items() if v["count"] > 0}

    context = {
        "quotes_by_status": quotes_by_status,
        "search_query": search_query,
        "is_admin": is_admin,
        "is_quoter": is_quoter,
        "is_rep": is_rep,
        "is_buyer": is_buyer,
    }

    template = (
        "quotes/quote_list_mobile.html"
        if is_mobile(request)
        else "quotes/quote_list.html"
    )
    return render(request, template, context)


@login_required
def quote_create(request):
    if request.method == "POST":
        form = QuoteRequestForm(request.POST, request.FILES)

        # Get descriptions from items
        descriptions = request.POST.getlist("description[]")

        # If the form doesn't have a description field populated,
        # but we have item descriptions, use the first item description
        if "description" not in request.POST or not request.POST["description"].strip():
            if descriptions and descriptions[0].strip():
                # Create a copy of POST data we can modify
                post_data = request.POST.copy()
                post_data["description"] = descriptions[0]
                # Update the form with modified data
                form = QuoteRequestForm(post_data, request.FILES)

        if form.is_valid():
            # The rest of your existing code
            try:
                # Create quote
                quote = form.save(commit=False)
                quote.rep = request.user
                quote.user = request.user

                # If we still don't have a description (unlikely), set a default
                if not quote.description:
                    quote.description = "New Quote Request"

                # Use the new standardized function
                max_attempts = 3
                for attempt in range(max_attempts):
                    try:
                        quote.quote_number = generate_unique_quote_number()
                        quote.save()
                        break  # Success!
                    except IntegrityError:
                        if attempt == max_attempts - 1:
                            raise  # Give up after max attempts
                        # Try again with new number

                # Handle the photo field for backward compatibility
                if "photo" in request.FILES:
                    quote.photo = request.FILES["photo"]
                    quote.save()

                # Handle multiple file uploads
                attachment_files = request.FILES.getlist("attachments[]")
                for uploaded_file in attachment_files:
                    attachment = QuoteAttachment(
                        quote=quote, file=uploaded_file, filename=uploaded_file.name
                    )
                    attachment.save()

                # Process voice note if provided
                voice_note_data = request.POST.get("voiceNoteData")
                if voice_note_data and voice_note_data.startswith("data:audio"):
                    try:
                        voice_note = VoiceNote(quote_request=quote)
                        voice_note.save_audio(voice_note_data)
                        voice_note.save()
                        print("Voice note saved successfully")
                    except Exception as e:
                        print(f"Error saving voice note: {e}")

                # Process quote items
                descriptions = request.POST.getlist("description[]")
                quantities = request.POST.getlist("quantity[]")
                notes_list = request.POST.getlist("notes[]")

                # Create items
                for i in range(len(descriptions)):
                    if descriptions[i].strip():  # Only create items with descriptions
                        QuoteItem.objects.create(
                            quote=quote,
                            description=descriptions[i],
                            quantity=int(quantities[i]) if quantities[i] else 1,
                            notes=notes_list[i] if i < len(notes_list) else "",
                        )

                messages.success(
                    request, f"Quote #{quote.quote_number} created successfully!"
                )
                return redirect("quotes:quote_detail", pk=quote.id)

            except Exception as e:
                messages.error(request, f"Error creating quote: {str(e)}")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Error in {field}: {error}")
    else:
        form = QuoteRequestForm()

    context = {"form": form, "segment": "quotes", "title": "New Quote"}
    return render(request, "quotes/quote_form.html", context)


@login_required
def quote_detail(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)

    # Get all customers for the dropdown
    from wfdash.models import Customers

    customers = Customers.objects.all().order_by("company")

    if request.method == "POST":
        if "assign" in request.POST:
            quote.assigned_to = request.user
            quote.status = "claimed"
            quote.save()
            messages.success(request, "Quote assigned to you successfully!")
            return redirect("quotes:quote_process", pk=quote.pk)
        elif "complete" in request.POST:
            if quote.can_complete():
                quote.status = "complete"
                quote.save()
                messages.success(request, "Quote marked as complete!")
            else:
                messages.error(
                    request,
                    "Cannot complete quote - some items are missing information",
                )
        elif "problem" in request.POST:
            # Get problem reason from the form
            problem_reason = request.POST.get("problem_reason", "")

            # Change status to problem instead of just setting a flag
            quote.has_problems = True
            quote.status = "problem"  # New status for problematic quotes

            # Add the problem reason to notes with a timestamp
            current_time = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            problem_note = f"PROBLEM REPORTED ({current_time}):\n{problem_reason}\n\n"

            # Prepend to existing notes or create new notes
            if quote.notes:
                quote.notes = problem_note + quote.notes
            else:
                quote.notes = problem_note

            quote.save()
            messages.warning(
                request, "Quote marked as problematic and returned for review!"
            )

            # If it was pending approval, notify the original submitter
            if (
                quote.assigned_to
                and quote.assigned_to.email
                and quote.assigned_to != request.user
            ):
                try:
                    # Send notification email to the assigned user
                    subject = f"Problem reported with Quote #{quote.quote_number}"
                    message = f"""
                    A problem has been reported with Quote #{quote.quote_number} by {request.user.get_full_name() or request.user.username}.

                    Reason:
                    {problem_reason}

                    Please review and address this issue.
                    """
                    quote.assigned_to.email_user(subject, message)
                except Exception as e:
                    # Just log the error, don't stop the flow
                    print(f"Error sending email: {str(e)}")

    items = quote.items.all()
    return render(
        request,
        "quotes/quote_detail.html",
        {
            "quote": quote,
            "items": items,
            "segment": "quotes",
            "customers": customers,
        },
    )


@login_required
def quote_edit(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)
    if quote.is_complete:
        messages.error(request, "Cannot edit completed quotes!")
        return redirect("quotes:quote_detail", pk=quote.pk)

    if request.method == "POST":
        form = QuoteRequestForm(request.POST, request.FILES, instance=quote)
        formset = QuoteItemFormSet(request.POST, instance=quote)
        if form.is_valid() and formset.is_valid():
            # Save the main form
            form.save()
            formset.save()

            # Handle multiple file uploads
            attachment_files = request.FILES.getlist("attachments[]")
            for uploaded_file in attachment_files:
                attachment = QuoteAttachment(
                    quote=quote, file=uploaded_file, filename=uploaded_file.name
                )
                attachment.save()

            messages.success(request, "Quote updated successfully!")
            return redirect("quotes:quote_detail", pk=quote.pk)
    else:
        form = QuoteRequestForm(instance=quote)
        formset = QuoteItemFormSet(instance=quote)

    return render(
        request,
        "quotes/quote_form.html",
        {
            "form": form,
            "formset": formset,
            "quote": quote,
            "segment": "quotes",
            "title": "Edit Quote",
        },
    )


@login_required
def quote_delete(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)

    # Security check - only quote owner or admin can delete
    if not (request.user == quote.rep or request.user.is_staff):
        messages.error(request, "You don't have permission to delete this quote.")
        return redirect("quotes:quote_detail", pk=pk)

    if request.method == "POST":
        quote_number = quote.quote_number

        try:
            # Delete all related items first
            quote.items.all().delete()

            # Delete attachments
            if hasattr(quote, "attachments"):
                for attachment in quote.attachments.all():
                    # Delete the actual file
                    if (
                        attachment.file
                        and hasattr(attachment.file, "path")
                        and os.path.exists(attachment.file.path)
                    ):
                        os.remove(attachment.file.path)
                    attachment.delete()

            # Delete voice notes
            if hasattr(quote, "voice_notes"):
                for voice_note in quote.voice_notes.all():
                    if (
                        voice_note.audio
                        and hasattr(voice_note.audio, "path")
                        and os.path.exists(voice_note.audio.path)
                    ):
                        os.remove(voice_note.audio.path)
                    voice_note.delete()

            # Delete the quote itself
            quote.delete()

            messages.success(
                request, f"Quote {quote_number} has been deleted successfully."
            )
            return redirect("quotes:quote_list")

        except Exception as e:
            messages.error(request, f"Error deleting quote: {str(e)}")
            return redirect("quotes:quote_detail", pk=pk)

    # If not POST, show confirmation page (though we're using JS confirmation)
    return render(request, "quotes/quote_confirm_delete.html", {"quote": quote})


@login_required
def quote_claim(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)
    if request.method == "POST":
        quote.assigned_to = request.user
        quote.status = "claimed"
        quote.save()
        messages.success(request, f"Quote #{quote.quote_number} has been claimed")
        return redirect("quotes:quote_process", pk=quote.pk)
    return redirect("quotes:quote_list")


@login_required
def quote_process(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)
    items = quote.items.all().order_by("id")
    suppliers = Suppliers.objects.all().order_by("suppliername")

    if request.method == "POST":
        # Check if add_item button was clicked
        if "add_item" in request.POST:
            # Create a blank item
            QuoteItem.objects.create(
                quote=quote,
                description="",
                quantity=1,
                quote_number=quote.quote_number,
                quote_reference="",
                cost_price=0,
                selling_price=0,
                markup=30,  # Default markup
            )
            messages.success(request, "New item added successfully!")
            return redirect("quotes:quote_process", pk=pk)

        # Handle other form submissions...
        # Your existing form processing code

    # Rest of your view...
    return render(
        request,
        "quotes/quote_process.html",
        {"quote": quote, "items": items, "suppliers": suppliers, "segment": "quotes"},
    )


@login_required
@require_http_methods(["POST"])
def save_quote_item(request, item_id):
    """Save a quote item via Ajax."""
    if request.method == "POST":
        item = get_object_or_404(QuoteItem, id=item_id)

        # Server-side validation for required fields
        supplier_id = request.POST.get(f"supplier_{item_id}")
        cost_price = request.POST.get(f"cost_price_{item_id}")
        markup = request.POST.get(f"markup_{item_id}")

        if not supplier_id:
            return JsonResponse({"status": "error", "message": "Supplier is required"})

        if not cost_price:
            return JsonResponse(
                {"status": "error", "message": "Cost price is required"}
            )

        # Add markup validation
        if not markup:
            return JsonResponse(
                {"status": "error", "message": "Markup percentage is required"}
            )

        # Continue with your existing save logic...

    try:
        # Process text fields
        item.quote_number = request.POST.get(f"quote_number_{item_id}", "")
        item.quote_reference = request.POST.get(f"quote_reference_{item_id}", "")
        item.description = request.POST.get(f"description_{item_id}", "")
        item.notes = request.POST.get(f"notes_{item_id}", "")
        item.quantity = request.POST.get(f"quantity_{item_id}", item.quantity)

        # Process decimal fields
        try:
            item.cost_price = float(request.POST.get(f"cost_price_{item_id}", 0))
            item.markup = float(request.POST.get(f"markup_{item_id}", 0))
            item.selling_price = float(request.POST.get(f"selling_price_{item_id}", 0))
        except ValueError:
            pass

        # Process supplier
        supplier_id = request.POST.get(f"supplier_{item_id}")
        if supplier_id:
            item.supplier_id = supplier_id

        # Mark item as processed
        item.is_processed = True
        item.save()

        return JsonResponse({"status": "success", "message": "Item saved successfully"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})


@login_required
@require_http_methods(["POST"])  # Use this instead of require_POST
def delete_quote_item(request, item_id):
    """Delete a quote item."""
    try:
        # Try to get the item but handle case where it might not exist
        try:
            item = QuoteItem.objects.get(pk=item_id)
        except QuoteItem.DoesNotExist:
            # Item already deleted, return success since the end goal is achieved
            return JsonResponse(
                {"status": "success", "message": "Item already deleted"}
            )

        quote_id = item.quote.id

        # Check if user has permission to delete this item
        if (
            request.user.is_staff
            or request.user == item.quote.assigned_to
            or request.user == item.quote.rep
        ):
            # Delete the item
            item.delete()
            return JsonResponse(
                {"status": "success", "message": "Item deleted successfully"}
            )
        else:
            return JsonResponse(
                {"status": "error", "message": "Permission denied"}, status=403
            )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def get_decimal_or_none(field_name, request):
    """Helper function to convert form values to decimal or None"""
    value = request.POST.get(field_name)
    try:
        return Decimal(value) if value else None
    except InvalidOperation:
        return None


@login_required
def add_quote_item(request):
    if request.method == "POST":
        # Get the quote_id from the POST data
        quote_id = request.POST.get("quote_id")
        if not quote_id:
            return JsonResponse({"status": "error", "message": "Quote ID is required"})

        try:
            # Get the quote
            quote = QuoteRequest.objects.get(id=quote_id)

            # Create a new QuoteItem instance
            new_item = QuoteItem.objects.create(
                quote=quote,
                description="",
                quantity=1,
                quote_number=quote.quote_number,
            )

            # Get all suppliers
            suppliers = Suppliers.objects.all()

            # Wrap the item in a proper container div before rendering the partial
            wrapped_html = (
                f'<div class="item-section card mb-3" data-item-id="{new_item.id}">'
            )
            wrapped_html += render_to_string(
                "quotes/partials/quote_item.html",
                {
                    "item": new_item,
                    "quote": quote,  # Include 'quote' in the context
                    "suppliers": suppliers,
                    "forloop": {"counter": quote.items.count()},
                    "checked": True,
                },
                request=request,
            )
            wrapped_html += "</div>"

            return JsonResponse(
                {"status": "success", "html": wrapped_html, "item_id": new_item.id}
            )

        except QuoteRequest.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Quote not found"})
        except Exception as e:
            import traceback

            print(traceback.format_exc())  # Print detailed error for debugging
            return JsonResponse({"status": "error", "message": str(e)})

    return JsonResponse({"status": "error", "message": "Invalid request method"})


@login_required
@ensure_csrf_cookie  # This decorator ensures the CSRF cookie is set
def add_item_view(request):
    if request.method == "POST":
        quote_id = request.POST.get("quote_id")
        try:
            quote = get_object_or_404(QuoteRequest, id=quote_id)

            # Create a new QuoteItem instance
            new_item = QuoteItem.objects.create(
                quote=quote,
                description="",
                quantity=1,
                quote_number=quote.quote_number,
            )

            # Get all suppliers
            suppliers = Suppliers.objects.all()

            # Render the item HTML
            html = render_to_string(
                "quotes/partials/quote_item.html",
                {
                    "item": new_item,
                    "quote": quote,
                    "suppliers": suppliers,
                },
                request=request,
            )

            return JsonResponse(
                {
                    "status": "success",
                    "message": "Item added successfully",
                    "html": html,
                    "item_id": new_item.id,
                }
            )
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})


def clean_customer(self):
    customer = self.cleaned_data.get("customer")
    if not customer:
        raise forms.ValidationError("Customer is required")
    return customer


def get_total(self):
    if self.quantity and self.selling_price:
        return self.quantity * self.selling_price
    return 0


@login_required
def generate_quote_pdf(request, quote_id):
    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id)

        # Get selected item IDs from query parameters
        selected_items_param = request.GET.get("items", "")

        if selected_items_param:
            # Parse the selected item IDs
            selected_item_ids = selected_items_param.split(",")

            # Filter to only include selected items
            items = quote.items.filter(id__in=selected_item_ids)
        else:
            # If no specific items selected, include all items that are complete
            items = (
                quote.items.filter(cost_price__gt=0, markup__gt=0)
                .exclude(description__isnull=True)
                .exclude(description="")
            )

        # No items to include in quote
        if not items.exists():
            messages.error(request, "No complete items selected for the quote PDF.")
            return redirect("quotes:quote_process", pk=quote_id)

        # Create PDF buffer
        buffer = BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        # Enhanced styles
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                name="RightAlign",
                parent=styles["Normal"],
                alignment=2,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="LeftAlign",
                parent=styles["Normal"],
                alignment=0,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="CompanyName",
                parent=styles["Heading1"],
                fontSize=14,
                textColor=colors.HexColor("#000000"),
                alignment=0,
                spaceBefore=12,
                spaceAfter=12,
            )
        )
        styles.add(
            ParagraphStyle(
                name="GrandTotal",
                parent=styles["Normal"],
                fontSize=12,
                fontName="Helvetica-Bold",
                alignment=2,
                spaceBefore=6,
                spaceAfter=6,
            )
        )

        # Add a custom paragraph style for descriptions with better word wrapping
        styles.add(
            ParagraphStyle(
                name="DescriptionStyle",
                parent=styles["LeftAlign"],
                wordWrap="CJK",
                spaceBefore=2,
                spaceAfter=2,
                leading=14,
            )
        )

        styles.add(
            ParagraphStyle(
                name="QuoteRefStyle",
                parent=styles["RightAlign"],
                fontName="Helvetica-Bold",
                fontSize=14,
            )
        )

        elements = []

        # Header with logo and company info side by side
        if quote.company_letterhead == "CNL":
            company_details = [
                [
                    Paragraph(
                        "<b>CNL Mining Supplies (Pty) Ltd</b>", styles["CompanyName"]
                    )
                ],
                [Paragraph("47 Station Street", styles["LeftAlign"])],
                [Paragraph("Carletonville, Gauteng 2499", styles["LeftAlign"])],
                [Paragraph("+27 18 786 2897", styles["LeftAlign"])],
                [Paragraph("laura@wfsales.co.za", styles["LeftAlign"])],
                [Paragraph("VAT No: 4840229449", styles["LeftAlign"])],
                [Paragraph("Business ID No: 2014/004024/07", styles["LeftAlign"])],
            ]
        else:
            company_details = [
                [
                    Paragraph(
                        "<b>ISHERWOOD MINING SUPPLIES (PTY) LTD</b>",
                        styles["CompanyName"],
                    )
                ],
                [Paragraph("VAT No: 4590136331", styles["LeftAlign"])],
                [
                    Paragraph(
                        "Physical Address: 47 Station Street, Carletonville, 2499",
                        styles["LeftAlign"],
                    )
                ],
                [Paragraph("Contact: +27 18 786 2499", styles["LeftAlign"])],
                [Paragraph("Email: laura@wfsales.co.za", styles["LeftAlign"])],
            ]

        # Create header table with company info left and logo right
        try:
            logo_path = os.path.join(
                settings.STATIC_ROOT,
                "assets",
                "images",
                (
                    "cnl_logo.png"
                    if quote.company_letterhead == "CNL"
                    else "isherwood_logo.png"
                ),
            )

            header_data = [
                [
                    Table(company_details, colWidths=[4 * inch]),
                    Image(logo_path, width=2.5 * inch, height=1.5 * inch),
                ]
            ]
        except:
            # Fallback if logo doesn't exist
            header_data = [
                [
                    Table(company_details, colWidths=[6 * inch]),
                    Paragraph("LOGO", styles["Normal"]),
                ]
            ]

        header_table = Table(header_data, colWidths=[6 * inch, 2 * inch])
        header_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(header_table)
        elements.append(Spacer(1, 20))

        # QUOTATION title
        elements.append(Paragraph("<b>QUOTATION</b>", styles["Heading1"]))
        elements.append(Spacer(1, 10))

        # Customer info and Quote details
        customer_info = [
            [Paragraph("<b>TO:</b>", styles["LeftAlign"])],
            [Paragraph(f"{quote.customer.company}", styles["LeftAlign"])],
            [
                Paragraph(
                    f"{quote.customer.email if quote.customer.email else ''}",
                    styles["LeftAlign"],
                )
            ],
            [
                Paragraph(
                    f"{quote.customer.number if quote.customer.number else ''}",
                    styles["LeftAlign"],
                )
            ],
        ]

        # Quote details
        quote_info = [
            [Paragraph(f"<b>Quote No:</b> {quote.quote_number}", styles["RightAlign"])],
            [
                Paragraph(
                    f"<b>Date:</b> {quote.created_at.strftime('%d %B %Y')}",
                    styles["RightAlign"],
                )
            ],
            [
                Paragraph(
                    f"<b>Valid until:</b> {(quote.created_at + timezone.timedelta(days=30)).strftime('%d %B %Y')}",
                    styles["RightAlign"],
                )
            ],
            [
                Paragraph(
                    f"Delivery Note: {quote.quote_reference}", styles["QuoteRefStyle"]
                )
            ],
        ]

        info_data = [
            [
                Table(customer_info, colWidths=[4 * inch]),
                Table(quote_info, colWidths=[4 * inch]),
            ]
        ]
        info_table = Table(info_data, colWidths=[4 * inch, 4 * inch])
        info_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(info_table)
        elements.append(Spacer(1, 20))

        # Items table
        table_data = [["Description", "Qty", "Unit Price", "Total"]]
        total = 0

        # Use only the selected items
        for item in items:
            amount = item.quantity * item.selling_price
            total += amount
            table_data.append(
                [
                    Paragraph(
                        (item.quote_reference or item.description).replace(
                            "\n", "<br />"
                        ),
                        styles["DescriptionStyle"],
                    ),
                    str(item.quantity),
                    f"R {item.selling_price:,.2f}",
                    f"R {amount:,.2f}",
                ]
            )

        # Add VAT and total
        vat = total * Decimal("0.15")
        grand_total = total + vat

        table_data.extend(
            [
                [
                    "",
                    "",
                    Paragraph("<b>Subtotal:</b>", styles["RightAlign"]),
                    f"R {total:,.2f}",
                ],
                [
                    "",
                    "",
                    Paragraph("<b>VAT (15%):</b>", styles["RightAlign"]),
                    f"R {vat:,.2f}",
                ],
                [
                    "",
                    "",
                    Paragraph("<b>Total:</b>", styles["GrandTotal"]),
                    f"R {grand_total:,.2f}",
                ],
            ]
        )

        table = Table(
            table_data, colWidths=[4 * inch, 1 * inch, 1.5 * inch, 1.5 * inch]
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B2BE80")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5B6711")),
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -4), colors.white),
                    ("LINEBELOW", (0, 0), (-1, -4), 0.25, colors.black),
                    ("LINEABOVE", (-2, -3), (-1, -3), 1, colors.black),
                    ("LINEABOVE", (-2, -1), (-1, -1), 2, colors.black),
                ]
            )
        )
        elements.append(table)

        # Terms and conditions
        elements.append(Spacer(1, 30))
        elements.append(Paragraph("<b>Terms and Conditions:</b>", styles["Heading4"]))
        terms = [
            "1. This quotation is valid for 30 days from the date of issue.",
            "2. Prices are quoted excluding VAT unless otherwise stated.",
            "3. Lead time will be confirmed upon receipt of order.",
        ]
        for term in terms:
            elements.append(Paragraph(term, styles["LeftAlign"]))

        # Banking details if CNL
        if quote.company_letterhead == "CNL":
            elements.append(Spacer(1, 20))
            elements.append(Paragraph("<b>Banking Details:</b>", styles["Heading4"]))
            banking_info = [
                "Standard Bank - Carletonville",
                "Current Account",
                "Branch Code: 016141",
                "Account Number: 022196552",
            ]

            for info in banking_info:
                elements.append(Paragraph(info, styles["LeftAlign"]))

        # BUILD THE DOCUMENT
        doc.build(elements)

        # After successful PDF generation, mark items as included in quote
        pdf_id = f"{quote.quote_number}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        items.update(included_in_quote=True, quote_pdf_id=pdf_id)

        # Save to quote object
        quote.pdf_file.save(
            f"Quote-{quote.quote_number}.pdf", ContentFile(buffer.getvalue())
        )

        # Update the generated timestamp
        quote.pdf_generated_at = timezone.now()
        quote.save()

        # Return PDF directly to browser
        return HttpResponse(
            buffer.getvalue(),
            content_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="Quote-{quote.quote_number}.pdf"'
            },
        )

    except Exception as e:
        messages.error(request, f"Error generating quote: {str(e)}")
        return redirect("quotes:quote_process", pk=quote_id)


@login_required
def generated_quotes(request):
    # Only show approved quotes
    quotes_list = QuoteRequest.objects.filter(
        pdf_file__isnull=False,
        status="approved",  # Only show approved quotes
    ).order_by("-pdf_generated_at")

    # Search functionality
    search_query = request.GET.get("search")
    if search_query:
        quotes_list = quotes_list.filter(
            Q(quote_number__icontains=search_query)
            | Q(customer__company__icontains=search_query)
            | Q(quote_reference__icontains=search_query)
        )

    # Company filter
    company = request.GET.get("company")
    if company:
        quotes_list = quotes_list.filter(company_letterhead=company)

    # Date range filter
    date_range = request.GET.get("date_range")
    if date_range:
        today = timezone.now().date()
        if date_range == "today":
            quotes_list = quotes_list.filter(pdf_generated_at__date=today)
        elif date_range == "week":
            week_ago = today - timedelta(days=7)
            quotes_list = quotes_list.filter(pdf_generated_at__date__gte=week_ago)
        elif date_range == "month":
            month_ago = today - timedelta(days=30)
            quotes_list = quotes_list.filter(pdf_generated_at__date__gte=month_ago)

    # Pagination
    paginator = Paginator(quotes_list, 10)  # Show 10 quotes per page
    page = request.GET.get("page")
    quotes = paginator.get_page(page)

    context = {
        "quotes": quotes,
        "segment": "generated_quotes",
        "title": "Generated Quotes",
    }
    return render(request, "quotes/generated_quotes.html", context)


# Add these new views for letterhead-specific PDFs
@login_required
def generate_cnl_quote_pdf(request, quote_id):
    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id)

        # Force CNL letterhead
        quote.company_letterhead = "CNL"
        quote.save()

        # Get selected items
        selected_items_param = request.GET.get("items", "")

        if selected_items_param:
            selected_item_ids = selected_items_param.split(",")
            items = quote.items.filter(id__in=selected_item_ids)
        else:
            items = (
                quote.items.filter(cost_price__gt=0, markup__gt=0)
                .exclude(description__isnull=True)
                .exclude(description="")
            )

        if not items.exists():
            messages.error(request, "No complete items selected for the quote PDF.")
            return redirect("quotes:quote_process", pk=quote_id)

        # Create PDF
        buffer = BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        # Enhanced styles
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                name="RightAlign",
                parent=styles["Normal"],
                alignment=2,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="LeftAlign",
                parent=styles["Normal"],
                alignment=0,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="CompanyName",
                parent=styles["Heading1"],
                fontSize=14,
                textColor=colors.HexColor("#000000"),
                alignment=0,
                spaceBefore=12,
                spaceAfter=12,
            )
        )
        styles.add(
            ParagraphStyle(
                name="GrandTotal",
                parent=styles["Normal"],
                fontSize=12,
                fontName="Helvetica-Bold",
                alignment=2,
                spaceBefore=6,
                spaceAfter=6,
            )
        )

        # Add a custom paragraph style for descriptions with better word wrapping
        styles.add(
            ParagraphStyle(
                name="DescriptionStyle",
                parent=styles["LeftAlign"],
                wordWrap="CJK",  # Better word wrapping for all text types
                spaceBefore=2,
                spaceAfter=2,
                leading=14,  # Slightly more space between lines
            )
        )

        # --- Add this new style for the reference ---
        styles.add(
            ParagraphStyle(
                name="QuoteRefStyle",
                parent=styles["RightAlign"],  # Keep right alignment
                fontName="Helvetica-Bold",  # Make the font bold
                fontSize=16,  # Increase font size (adjust as needed, default is 10)
            )
        )
        # --- End of new style definition ---

        # Initialize elements list - THIS LINE WAS MISSING
        elements = []

        # CNL Mining specific header
        company_details = [
            [Paragraph("<b>CNL Mining Supplies (Pty) Ltd</b>", styles["CompanyName"])],
            [Paragraph("47 Station Street", styles["LeftAlign"])],
            [Paragraph("Carletonville, Gauteng 2499", styles["LeftAlign"])],
            [Paragraph("+27 18 786 2897", styles["LeftAlign"])],
            [Paragraph("laura@wfsales.co.za", styles["LeftAlign"])],
            [Paragraph("VAT No: 4840229449", styles["LeftAlign"])],
            [Paragraph("Business ID No: 2014/004024/07", styles["LeftAlign"])],
        ]

        # Add logo
        try:
            logo_path = os.path.join(
                settings.STATIC_ROOT, "assets", "images", "cnl_logo.png"
            )

            header_data = [
                [
                    Table(company_details, colWidths=[4 * inch]),
                    Image(logo_path, width=2.5 * inch, height=1.5 * inch),
                ]
            ]
        except Exception as e:
            # Fallback if logo doesn't exist
            print(f"Logo error: {str(e)}")
            header_data = [
                [
                    Table(company_details, colWidths=[6 * inch]),
                    Paragraph("LOGO", styles["Normal"]),
                ]
            ]

        header_table = Table(header_data, colWidths=[6 * inch, 2 * inch])
        header_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(header_table)
        elements.append(Spacer(1, 20))

        # QUOTATION title
        elements.append(Paragraph("<b>QUOTATION</b>", styles["Heading1"]))
        elements.append(Spacer(1, 10))

        # Customer info and Quote details
        customer_info = [
            [Paragraph("<b>TO:</b>", styles["LeftAlign"])],
            [Paragraph(f"{quote.customer.company}", styles["LeftAlign"])],
            [
                Paragraph(
                    f"{quote.customer.email if quote.customer.email else ''}",
                    styles["LeftAlign"],
                )
            ],
            [
                Paragraph(
                    f"{quote.customer.number if quote.customer.number else ''}",
                    styles["LeftAlign"],
                )
            ],
        ]

        # Quote details
        quote_info = [
            [Paragraph(f"<b>Quote No:</b> {quote.quote_number}", styles["RightAlign"])],
            [
                Paragraph(
                    f"<b>Date:</b> {quote.created_at.strftime('%d %B %Y')}",
                    styles["RightAlign"],
                )
            ],
            [
                Paragraph(
                    f"<b>Valid until:</b> {(quote.created_at + timezone.timedelta(days=30)).strftime('%d %B %Y')}",
                    styles["RightAlign"],
                )
            ],
            [
                # --- Apply the new style here ---
                Paragraph(
                    f"Reference: {quote.quote_reference}", styles["QuoteRefStyle"]
                )
                # --- End of change ---
            ],
        ]

        info_data = [
            [
                Table(customer_info, colWidths=[4 * inch]),
                Table(quote_info, colWidths=[4 * inch]),
            ]
        ]
        info_table = Table(info_data, colWidths=[4 * inch, 4 * inch])
        info_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(info_table)
        elements.append(Spacer(1, 20))

        # Items table
        table_data = [["Description", "Qty", "Unit Price", "Total"]]
        total = 0

        # Use only the selected items
        for item in items:
            amount = item.quantity * item.selling_price
            total += amount
            table_data.append(
                [
                    # Correct the line below
                    Paragraph(
                        (item.quote_reference or item.description).replace(
                            "\n", "<br />"
                        ),
                        styles["DescriptionStyle"],
                    ),
                    str(item.quantity),
                    f"R {item.selling_price:,.2f}",
                    f"R {amount:,.2f}",
                ]
            )

        # Add VAT and total
        vat = total * Decimal("0.15")
        grand_total = total + vat

        table_data.extend(
            [
                [
                    "",
                    "",
                    Paragraph("<b>Subtotal:</b>", styles["RightAlign"]),
                    f"R {total:,.2f}",
                ],
                [
                    "",
                    "",
                    Paragraph("<b>VAT (15%):</b>", styles["RightAlign"]),
                    f"R {vat:,.2f}",
                ],
                [
                    "",
                    "",
                    Paragraph("<b>Total:</b>", styles["GrandTotal"]),
                    f"R {grand_total:,.2f}",
                ],
            ]
        )

        table = Table(
            table_data, colWidths=[4 * inch, 1 * inch, 1.5 * inch, 1.5 * inch]
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B2BE80")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5B6711")),
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -4), colors.white),
                    ("LINEBELOW", (0, 0), (-1, -4), 0.25, colors.black),
                    ("LINEABOVE", (-2, -3), (-1, -3), 1, colors.black),
                    ("LINEABOVE", (-2, -1), (-1, -1), 2, colors.black),
                    # Add this to align content to the TOP of cells
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(table)

        # Terms and conditions
        elements.append(Spacer(1, 30))
        elements.append(Paragraph("<b>Terms and Conditions:</b>", styles["Heading4"]))
        terms = [
            "1. This quotation is valid for 30 days from the date of issue.",
            "2. Prices are quoted excluding VAT unless otherwise stated.",
            "3. Lead time will be confirmed upon receipt of order.",
        ]
        for term in terms:
            elements.append(Paragraph(term, styles["LeftAlign"]))

        # Banking details - CNL specific
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("<b>Banking Details:</b>", styles["Heading4"]))
        banking_info = [
            "Standard Bank - Carletonville",
            "Current Account",
            "Branch Code: 016141",
            "Account Number: 022196552",
        ]

        for info in banking_info:
            elements.append(Paragraph(info, styles["LeftAlign"]))

        # BUILD THE DOCUMENT
        doc.build(elements)

        # After successful PDF generation, mark items as included in quote
        pdf_id = f"{quote.quote_number}-CNL-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        items.update(included_in_quote=True, quote_pdf_id=pdf_id)

        # Save the PDF file
        buffer.seek(0)
        quote.pdf_file.save(
            f"Quote-CNL-{quote.quote_number}.pdf", ContentFile(buffer.getvalue())
        )

        # Update quote metadata
        quote.pdf_generated_at = timezone.now()
        quote.status = "approval_pending"
        quote.save()

        # Add success message
        messages.success(
            request,
            f"Quote {quote.quote_number} has been generated and submitted for approval",
        )

        # Redirect to the pending approvals page instead of returning the PDF
        return redirect("quotes:pending_approvals")

    except Exception as e:
        messages.error(request, f"Error generating CNL quote: {str(e)}")
        return redirect("quotes:quote_process", pk=quote_id)


@login_required
def generate_isherwood_quote_pdf(request, quote_id):
    try:
        # Get the quote
        quote = get_object_or_404(QuoteRequest, id=quote_id)

        # Force ISH letterhead
        quote.company_letterhead = "ISHERWOOD"
        quote.save()

        # FIXED: Get the company correctly from the customer
        company = None
        if quote.customer:
            # The customer model has 'company' field, not 'company_id'
            if hasattr(quote.customer, "company"):
                if isinstance(quote.customer.company, Company):
                    # If it's already a Company object
                    company = quote.customer.company
                elif quote.customer.company:  # Changed from company_id to company
                    # If it's a foreign key ID or string reference
                    try:
                        # Try to get as an ID first
                        company = Company.objects.filter(
                            id=quote.customer.company
                        ).first()
                    except (ValueError, TypeError):
                        # If that fails, try as a string name
                        company = Company.objects.filter(
                            company=quote.customer.company
                        ).first()
            # Backward compatibility for string company field
            elif hasattr(quote.customer, "company") and isinstance(
                quote.customer.company, str
            ):
                # Look up company by name if it's a string
                company = Company.objects.filter(company=quote.customer.company).first()

        # Get selected items
        selected_items_param = request.GET.get("items", "")

        if selected_items_param:
            selected_item_ids = selected_items_param.split(",")
            items = quote.items.filter(id__in=selected_item_ids)
        else:
            items = (
                quote.items.filter(cost_price__gt=0, markup__gt=0)
                .exclude(description__isnull=True)
                .exclude(description="")
            )

        if not items.exists():
            messages.error(request, "No complete items selected for the quote PDF.")
            return redirect("quotes:quote_process", pk=quote_id)

        # Create PDF
        buffer = BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        # Enhanced styles
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                name="RightAlign",
                parent=styles["Normal"],
                alignment=2,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="LeftAlign",
                parent=styles["Normal"],
                alignment=0,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="CompanyName",
                parent=styles["Heading1"],
                fontSize=14,
                textColor=colors.HexColor("#000000"),
                alignment=0,
                spaceBefore=12,
                spaceAfter=12,
            )
        )
        styles.add(
            ParagraphStyle(
                name="GrandTotal",
                parent=styles["Normal"],
                fontSize=12,
                fontName="Helvetica-Bold",
                alignment=2,
                spaceBefore=6,
                spaceAfter=6,
            )
        )

        # Add a custom paragraph style for descriptions with better word wrapping
        styles.add(
            ParagraphStyle(
                name="DescriptionStyle",
                parent=styles["LeftAlign"],
                wordWrap="CJK",  # Better word wrapping for all text types
                spaceBefore=2,
                spaceAfter=2,
                leading=14,  # Slightly more space between lines
            )
        )

        elements = []

        # ISHERWOOD MINING SUPPLIES specific header with correct details
        company_details = [
            [
                Paragraph(
                    "<b>ISHERWOOD MINING SUPPLIES (PTY) LTD</b>", styles["CompanyName"]
                )
            ],
            [Paragraph("VAT No: 4590136331", styles["LeftAlign"])],
            [
                Paragraph(
                    "Physical Address: 47 Station Street, Carletonville, 2499",
                    styles["LeftAlign"],
                )
            ],
            [Paragraph("Contact: +27 18 786 2499", styles["LeftAlign"])],
            [Paragraph("Email: laura@wfsales.co.za", styles["LeftAlign"])],
            [
                Paragraph(
                    f"Vendor Number: {company.vendor if company and company.vendor else 'N/A'}",
                    styles["LeftAlign"],
                )
            ],
        ]

        # Add logo
        try:
            logo_path = os.path.join(
                settings.STATIC_ROOT, "assets", "images", "isherwood_logo.png"
            )

            header_data = [
                [
                    Table(company_details, colWidths=[4 * inch]),
                    Image(logo_path, width=2.5 * inch, height=1.5 * inch),
                ]
            ]
        except Exception as e:
            # Fallback if logo doesn't exist
            print(f"Logo error: {str(e)}")
            header_data = [
                [
                    Table(company_details, colWidths=[6 * inch]),
                    Paragraph("ISHERWOOD", styles["Normal"]),
                ]
            ]

        header_table = Table(header_data, colWidths=[6 * inch, 2 * inch])
        header_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(header_table)
        elements.append(Spacer(1, 20))

        # QUOTATION title
        elements.append(Paragraph("<b>QUOTATION</b>", styles["Heading1"]))
        elements.append(Spacer(1, 10))

        # Customer info and Quote details
        customer_info = [
            [Paragraph("<b>TO:</b>", styles["LeftAlign"])],
            [Paragraph(f"{quote.customer.company}", styles["LeftAlign"])],
        ]

        # Only add customer name if company is not Northam Platinum
        if (
            not quote.customer.company
            or "Northam Platinum" not in quote.customer.company
        ):
            customer_info.append(
                [
                    Paragraph(
                        f"{quote.customer.customer if quote.customer.customer else ''}",
                        styles["LeftAlign"],
                    )
                ]
            )

        # Quote details
        quote_info = [
            [Paragraph(f"<b>Quote No:</b> {quote.quote_number}", styles["RightAlign"])],
            [
                Paragraph(
                    f"<b>Date:</b> {quote.created_at.strftime('%d %B %Y')}",
                    styles["RightAlign"],
                )
            ],
            [
                Paragraph(
                    f"<b>Reference:</b> {quote.quote_reference}", styles["RightAlign"]
                )
            ],
            [
                Paragraph(
                    f"<b>Valid until:</b> {(quote.created_at + timezone.timedelta(days=30)).strftime('%d %B %Y')}",
                    styles["RightAlign"],
                )
            ],
        ]

        info_data = [
            [
                Table(customer_info, colWidths=[4 * inch]),
                Table(quote_info, colWidths=[4 * inch]),
            ]
        ]
        info_table = Table(info_data, colWidths=[4 * inch, 4 * inch])
        info_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(info_table)
        elements.append(Spacer(1, 20))

        # Items table
        table_data = [["Description", "Qty", "Unit Price", "Total"]]
        total = 0

        # Use only the selected items
        for item in items:
            amount = item.quantity * item.selling_price
            total += amount
            table_data.append(
                [
                    # Correct the line below
                    Paragraph(
                        (item.quote_reference or item.description).replace(
                            "\n", "<br />"
                        ),
                        styles["DescriptionStyle"],
                    ),
                    str(item.quantity),
                    f"R {item.selling_price:,.2f}",
                    f"R {amount:,.2f}",
                ]
            )

        # Add VAT and total
        vat = total * Decimal("0.15")
        grand_total = total + vat

        table_data.extend(
            [
                [
                    "",
                    "",
                    Paragraph("<b>Subtotal:</b>", styles["RightAlign"]),
                    f"R {total:,.2f}",
                ],
                [
                    "",
                    "",
                    Paragraph("<b>VAT (15%):</b>", styles["RightAlign"]),
                    f"R {vat:,.2f}",
                ],
                [
                    "",
                    "",
                    Paragraph("<b>Total:</b>", styles["GrandTotal"]),
                    f"R {grand_total:,.2f}",
                ],
            ]
        )

        table = Table(
            table_data, colWidths=[4 * inch, 1 * inch, 1.5 * inch, 1.5 * inch]
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B2BE80")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5B6711")),
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -4), colors.white),
                    ("LINEBELOW", (0, 0), (-1, -4), 0.25, colors.black),
                    ("LINEABOVE", (-2, -3), (-1, -3), 1, colors.black),
                    ("LINEABOVE", (-2, -1), (-1, -1), 2, colors.black),
                    # Add this to align content to the TOP of cells
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(table)

        # Terms and conditions - Isherwood specific
        elements.append(Spacer(1, 30))
        elements.append(Paragraph("<b>Terms and Conditions:</b>", styles["Heading4"]))
        terms = [
            "1. This quotation is valid for 30 days from the date of issue.",
            "2. Prices are quoted excluding VAT unless otherwise stated.",
            "3. Lead time will be confirmed upon receipt of order.",
            "4. Isherwood Mining Supplies standard terms apply to all orders.",
        ]
        for term in terms:
            elements.append(Paragraph(term, styles["LeftAlign"]))

        # Banking details - Isherwood specific
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("<b>Banking Details:</b>", styles["Heading4"]))
        banking_info = [
            "Bank: FNB",
            "Account Name: Isherwood Mining Supplies (Pty) Ltd",
            "Account Number: 02-290-746-7",
            "Branch Code: 016141",
        ]

        for info in banking_info:
            elements.append(Paragraph(info, styles["LeftAlign"]))

        # BUILD THE DOCUMENT
        doc.build(elements)

        # After successful PDF generation, mark items as included in quote
        pdf_id = f"{quote.quote_number}-ISH-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        items.update(included_in_quote=True, quote_pdf_id=pdf_id)

        # Save PDF to quote object
        buffer.seek(0)
        quote.pdf_file.save(
            f"Quote-ISH-{quote.quote_number}.pdf", ContentFile(buffer.getvalue())
        )

        # Update the generated timestamp
        quote.pdf_generated_at = timezone.now()

        # CRITICAL FIX: Set status to approval_pending
        quote.status = "approval_pending"
        quote.save()

        messages.success(request, "Quote has been submitted for approval")

        # Redirect to the pending approvals page instead of returning the PDF
        return redirect("quotes:pending_approvals")

    except Exception as e:
        # Add this debug output to see the specific error
        import traceback

        print(f"ERROR GENERATING ISHERWOOD PDF: {str(e)}")
        print(traceback.format_exc())

        messages.error(request, f"Error generating Isherwood quote: {str(e)}")
        return redirect("quotes:quote_process", pk=quote_id)


@login_required
@require_POST
def update_quote_status(request, quote_id):
    """Update a quote's status"""
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

        quote.save()

        return JsonResponse(
            {"status": "success", "message": f"Quote status updated to {new_status}"}
        )

    except Exception as e:
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
        company_signature = "CNL Mining"
        sender_email = "sales@cnlmining.co.za"
    else:
        company_signature = "Isherwood Engineering"
        sender_email = "sales@isherwood.co.za"

    subject = f"Quotation {quote.quote_number} from {letterhead}"
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
def update_status(request, quote_id):
    """Update a quote's status"""
    if request.method != "POST":
        return JsonResponse(
            {"status": "error", "message": "Only POST requests allowed"}
        )

    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id)

        # Parse the JSON data
        data = json.loads(request.body)
        new_status = data.get("status")

        # Update the quote status
        quote.status = new_status
        quote.save()

        return JsonResponse(
            {"status": "success", "message": f"Quote status updated to {new_status}"}
        )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})


@login_required
def delete_attachment(request, pk):
    if request.method == "POST":
        attachment = get_object_or_404(QuoteAttachment, pk=pk)
        quote_id = attachment.quote.id

        # Check if user has permission
        if (
            request.user == attachment.quote.rep
            or request.user == attachment.quote.assigned_to
        ):
            # Delete the attachment
            filename = attachment.filename
            attachment.delete()

            messages.success(request, f'Attachment "{filename}" deleted successfully.')

            # Return JSON response for AJAX requests
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"status": "success"})

            # Redirect back to the quote for regular requests
            return redirect("quotes:quote_detail", pk=quote_id)
        else:
            messages.error(
                request, "You don't have permission to delete this attachment."
            )

    # Redirect to quote list for GET requests or failed deletions
    return redirect("quotes:quote_list")


@login_required
def pending_reviews(request):
    """Display quotes pending review by the current user."""
    quotes_list = QuoteRequest.objects.filter(
        status="pending_review", rep=request.user
    ).order_by("-pdf_generated_at")

    # Search functionality
    search_query = request.GET.get("search")
    if search_query:
        quotes_list = quotes_list.filter(
            Q(quote_number__icontains=search_query)
            | Q(customer__company__icontains=search_query)
            | Q(quote_reference__icontains=search_query)
        )

    # Pagination
    paginator = Paginator(quotes_list, 10)  # Show 10 quotes per page
    page = request.GET.get("page")
    quotes = paginator.get_page(page)

    context = {
        "quotes": quotes,
        "segment": "pending_reviews",
        "title": "Quotes Pending Review",
        "search_query": search_query,
    }
    return render(request, "quotes/pending_reviews.html", context)


@login_required
def quote_review(request, pk):
    """Handle quote review actions (approve or reject)."""
    quote = get_object_or_404(QuoteRequest, pk=pk)

    # Security check - only the original rep can review
    if request.user != quote.rep:
        messages.error(request, "You don't have permission to review this quote.")
        return redirect("quotes:quote_detail", pk=pk)

    if request.method == "POST":
        review_action = request.POST.get("review_action")
        comments = request.POST.get("comments", "")

        if review_action == "approve":
            quote.status = "approved"
            quote.save()
            messages.success(request, "Quote approved and ready to be sent to client!")

        elif review_action == "reject":
            quote.status = "rejected"
            # Add review comments to quote notes with timestamp
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
            if comments:
                if quote.notes:
                    quote.notes = f"{quote.notes}\n\n--- REVIEW FEEDBACK ({timestamp}) ---\n{comments}"
                else:
                    quote.notes = f"--- REVIEW FEEDBACK ({timestamp}) ---\n{comments}"
            quote.save()
            messages.warning(request, "Quote has been sent back for revision.")

        return redirect("quotes:quote_detail", pk=pk)

    # If not a POST request, just redirect to quote detail
    return redirect("quotes:quote_detail", pk=pk)


@login_required
def view_quote_pdf(request, quote_id):
    """View the generated PDF for a quote"""
    quote = get_object_or_404(QuoteRequest, id=quote_id)

    # Security check - only accessible by rep or assigned user
    if not (request.user == quote.rep or request.user == quote.assigned_to):
        messages.error(request, "You don't have permission to view this quote.")
        return redirect("quotes:quote_list")

    if quote.pdf_file:
        # Get the file path
        file_path = quote.pdf_file.path

        # Check if file exists
        if os.path.exists(file_path):
            with open(file_path, "rb") as pdf:
                response = HttpResponse(pdf.read(), content_type="application/pdf")
                response["Content-Disposition"] = (
                    f'inline; filename="{os.path.basename(file_path)}"'
                )
                return response
        else:
            messages.error(request, "PDF file not found on server.")
    else:
        messages.error(request, "No PDF has been generated for this quote.")

    return redirect("quotes:quote_detail", pk=quote_id)


@login_required
def clone_quote(request, pk):
    original_quote = get_object_or_404(QuoteRequest, pk=pk)

    if request.method == "POST":
        # Get the selected customer from the form
        customer_id = request.POST.get("customer")
        try:
            # Import Customers at the top of your file if not already there
            from wfdash.models import Customers

            selected_customer = Customers.objects.get(id=customer_id)

            # Create new quote with data from original quote
            new_quote = QuoteRequest(
                customer=selected_customer,
                quote_number=generate_unique_quote_number(),
                description=original_quote.description + " (Cloned)",
                notes=original_quote.notes,
                status="new",
                rep=request.user,  # Set the rep to current user
                assigned_to=request.user,  # Also set assigned_to to current user
                user=request.user,  # Fix: Make sure to set the user field
                company_letterhead=original_quote.company_letterhead,
                created_at=timezone.now(),
                updated_at=timezone.now(),
            )
            new_quote.save()

            # Clone all items from the original quote
            for item in original_quote.items.all():
                QuoteItem.objects.create(
                    quote=new_quote,
                    description=item.description,
                    quantity=item.quantity,
                    quote_number=new_quote.quote_number,
                    quote_reference=item.quote_reference,
                    supplier=item.supplier,
                    cost_price=item.cost_price,
                    selling_price=item.selling_price,
                    markup=item.markup,
                    notes=item.notes,
                )

            messages.success(
                request,
                f"Quote #{original_quote.quote_number} successfully cloned to #{new_quote.quote_number}",
            )
            return redirect("quotes:quote_process", pk=new_quote.id)

        except Customers.DoesNotExist:
            messages.error(request, "Selected customer not found")
        except Exception as e:
            messages.error(request, f"Error cloning quote: {str(e)}")

    # If method is GET or form submission failed, show the form with customer selection
    from wfdash.models import Customers

    customers = Customers.objects.all().order_by("company")

    return render(
        request,
        "quotes/clone_quote.html",
        {"quote": original_quote, "customers": customers, "segment": "quotes"},
    )


# Modify the split_quote view to remove items from original quote
@login_required
def split_quote(request, pk):
    quote = get_object_or_404(QuoteRequest, pk=pk)
    items = quote.items.all()

    if request.method == "POST":
        # Get selected items
        selected_items = request.POST.getlist("selected_items")

        if not selected_items:
            messages.error(request, "Please select at least one item to split.")
            return redirect("quotes:split_quote", pk=pk)

        try:
            # Create a new quote based on the original quote
            new_quote = QuoteRequest.objects.create(
                quote_number=generate_unique_quote_number(),
                customer=quote.customer,
                rep=request.user,
                description=f"Split from {quote.quote_number}: {quote.description}",
                status="new",
                notes=f"This quote was split from {quote.quote_number}",
                user=request.user,  # Add this line to fix the error
                # Include other required fields
                company_letterhead=quote.company_letterhead,
            )

            # Move selected items to the new quote
            for item_id in selected_items:
                item = get_object_or_404(QuoteItem, id=item_id)
                # Create a copy of the item for the new quote
                QuoteItem.objects.create(
                    quote=new_quote,
                    description=item.description,
                    quantity=item.quantity,
                    supplier=item.supplier,
                    cost_price=item.cost_price,
                    selling_price=item.selling_price,
                    markup=item.markup,
                    notes=item.notes,
                )
                # Optional: Remove item from original quote
                item.delete()

            messages.success(
                request,
                f"Quote split successfully! New quote number: {new_quote.quote_number}",
            )
            return redirect("quotes:quote_detail", pk=new_quote.pk)

        except Exception as e:
            messages.error(request, f"Error splitting quote: {str(e)}")
            return redirect("quotes:split_quote", pk=pk)

    return render(
        request,
        "quotes/split_quote.html",
        {"quote": quote, "items": items, "segment": "quotes"},
    )


@login_required
def add_item_to_quote(request):
    if request.method == "POST":
        quote_id = request.POST.get("quote_id")
        try:
            quote = QuoteRequest.objects.get(id=quote_id)

            # Create a new item
            item = QuoteItem.objects.create(
                quote=quote,
                description="",
                quantity=1,
                quote_number=quote.quote_number,
                quote_reference="",
                cost_price=0,
                selling_price=0,
                markup=30,
            )

            # Include 'quote' in the context
            item_html = render_to_string(
                "quotes/partials/quote_item.html",
                {
                    "item": item,
                    "quote": quote,  # Add this line
                    "suppliers": Suppliers.objects.all().order_by("suppliername"),
                },
            )

            return JsonResponse(
                {"status": "success", "item_id": item.id, "html": item_html}
            )
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})

    return JsonResponse({"status": "error", "message": "Invalid request method"})


@login_required
def pending_approvals(request):
    # Check user permissions just like in quote_list
    is_admin = (
        request.user.is_superuser or request.user.groups.filter(name="ADMIN").exists()
    )
    is_quoter = request.user.groups.filter(name="QUOTERS").exists()
    is_buyer = request.user.groups.filter(name="BUYER").exists()

    # Start with base query for approval pending quotes
    base_query = QuoteRequest.objects.filter(
        status="approval_pending", pdf_file__isnull=False
    )

    # Filter based on permissions - admins/quoters/buyers see all, reps see only their own
    if is_admin or is_quoter or is_buyer:
        quotes_list = base_query
    else:
        # Regular users only see their own quotes
        quotes_list = base_query.filter(rep=request.user)

    # Order by generated date
    quotes_list = quotes_list.order_by("-pdf_generated_at")

    # Search functionality
    search_query = request.GET.get("search")
    if search_query:
        quotes_list = quotes_list.filter(
            Q(quote_number__icontains=search_query)
            | Q(customer__company__icontains=search_query)
            | Q(quote_reference__icontains=search_query)
        )

    # Company filter
    company = request.GET.get("company")
    if company:
        quotes_list = quotes_list.filter(company_letterhead=company)

    # Date range filter
    date_range = request.GET.get("date_range")
    if date_range:
        today = timezone.now().date()
        if date_range == "today":
            quotes_list = quotes_list.filter(pdf_generated_at__date=today)
        elif date_range == "week":
            week_start = today - timezone.timedelta(days=today.weekday())
            quotes_list = quotes_list.filter(pdf_generated_at__date__gte=week_start)
        elif date_range == "month":
            month_start = today.replace(day=1)
            quotes_list = quotes_list.filter(pdf_generated_at__date__gte=month_start)

    # Pagination
    paginator = Paginator(quotes_list, 10)
    page = request.GET.get("page")
    quotes = paginator.get_page(page)

    context = {
        "quotes": quotes,
        "segment": "pending_approvals",
        "title": "Quotes Pending Approval",
        "search_query": search_query,
        "is_admin": is_admin,
        "is_quoter": is_quoter,
        "is_buyer": is_buyer,
    }
    return render(request, "quotes/pending_approvals.html", context)


@login_required
def approve_quote(request, quote_id):
    """Approve a quote and optionally send email directly"""
    quote = get_object_or_404(QuoteRequest, id=quote_id)

    if request.method == "POST":
        # Check if the request includes email parameters
        send_email = request.POST.get("send_email") == "true"

        # Update quote status
        quote.status = "approved"
        quote.save()

        # Create success message
        messages.success(request, f"Quote #{quote.quote_number} has been approved.")

        # If email should be sent directly
        if send_email:
            # Get email parameters from POST data
            to_email = request.POST.get("to", "")
            cc_email = request.POST.get("cc", "")
            bcc_email = request.POST.get("bcc", "")
            subject = request.POST.get("subject", "")
            body = request.POST.get("body", "")
            letterhead = request.POST.get("letterhead", "CNL")

            # If email parameters are not provided, redirect to a form to collect them
            if not to_email or not subject or not body:
                # Prepare default email data and redirect to the email form
                return redirect(f"/quotes/email_form/{quote_id}/?approved=true")

            try:
                # Process the email using the existing email_quote function
                from .views_email import email_quote

                # Create a modified request for the email_quote function
                email_request = request
                email_request.method = "POST"
                email_request.POST = request.POST.copy()

                # Send the email
                result = email_quote(email_request, quote_id)

                # Check the result
                import json

                response_data = json.loads(result.content)
                if response_data.get("status") == "success":
                    messages.success(
                        request, "Quote approved and email sent successfully."
                    )
                else:
                    messages.error(
                        request,
                        f"Quote approved but email failed: {response_data.get('message')}",
                    )
            except Exception as e:
                messages.error(request, f"Quote approved but email failed: {str(e)}")

        # Redirect to the pending approvals page
        return redirect("quotes:pending_approvals")

    # For GET requests, display a confirmation page with email form
    return render(request, "quotes/approve_quote.html", {"quote": quote})


@login_required
def reject_quote(request, quote_id):
    quote = get_object_or_404(QuoteRequest, id=quote_id)

    if request.method == "POST":
        rejection_reason = request.POST.get("rejection_reason")

        # Mark as rejected
        quote.status = "rejected"

        # Add rejection reason to notes
        if rejection_reason:
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M")
            if quote.notes:
                quote.notes = f"{quote.notes}\n\n--- REJECTION REASON ({timestamp}) ---\n{rejection_reason}"
            else:
                quote.notes = (
                    f"--- REJECTION REASON ({timestamp}) ---\n{rejection_reason}"
                )

        quote.save()

        messages.warning(request, f"Quote #{quote.quote_number} has been rejected")

        # Optional: Notify assigned user
        if quote.assigned_to and quote.assigned_to.email:
            try:
                from django.core.mail import send_mail

                send_mail(
                    f"Quote #{quote.quote_number} Needs Revision",
                    f"Your quote #{quote.quote_number} has been rejected.\n\nReason: {rejection_reason}",
                    settings.DEFAULT_FROM_EMAIL,
                    [quote.assigned_to.email],
                    fail_silently=True,
                )
            except Exception as e:
                # Log the error but don't break the flow
                print(f"Email sending failed: {str(e)}")

    # Redirect back to the pending approvals page
    return redirect("quotes:pending_approvals")


@login_required
def preview_cnl_quote_pdf(request, quote_id):
    """Preview a CNL quote without saving or changing status"""
    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id)

        # Temporarily force CNL letterhead just for preview
        original_letterhead = quote.company_letterhead
        quote.company_letterhead = "CNL"

        # Get selected items
        selected_items_param = request.GET.get("items", "")

        if selected_items_param:
            selected_item_ids = selected_items_param.split(",")
            items = quote.items.filter(id__in=selected_item_ids)
        else:
            items = (
                quote.items.filter(cost_price__gt=0, markup__gt=0)
                .exclude(description__isnull=True)
                .exclude(description="")
            )

        if not items.exists():
            messages.error(request, "No complete items selected for the quote PDF.")
            return redirect("quotes:quote_process", pk=quote_id)

        # Create PDF
        buffer = BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        # Enhanced styles - copy all style definitions from your generate_cnl_quote_pdf function
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                name="RightAlign",
                parent=styles["Normal"],
                alignment=2,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="LeftAlign",
                parent=styles["Normal"],
                alignment=0,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="CompanyName",
                parent=styles["Heading1"],
                fontSize=14,
                textColor=colors.HexColor("#000000"),
                alignment=0,
                spaceBefore=12,
                spaceAfter=12,
            )
        )
        styles.add(
            ParagraphStyle(
                name="GrandTotal",
                parent=styles["Normal"],
                fontSize=12,
                fontName="Helvetica-Bold",
                alignment=2,
                spaceBefore=6,
                spaceAfter=6,
            )
        )

        # Add a custom paragraph style for descriptions with better word wrapping
        styles.add(
            ParagraphStyle(
                name="DescriptionStyle",
                parent=styles["LeftAlign"],
                wordWrap="CJK",  # Better word wrapping for all text types
                spaceBefore=2,
                spaceAfter=2,
                leading=14,  # Slightly more space between lines
            )
        )

        # Initialize elements list
        elements = []

        # CNL Mining specific header
        company_details = [
            [Paragraph("<b>CNL Mining Supplies (Pty) Ltd</b>", styles["CompanyName"])],
            [Paragraph("47 Station Street", styles["LeftAlign"])],
            [Paragraph("Carletonville, Gauteng 2499", styles["LeftAlign"])],
            [Paragraph("+27 18 786 2897", styles["LeftAlign"])],
            [Paragraph("laura@wfsales.co.za", styles["LeftAlign"])],
            [Paragraph("VAT No: 4840229449", styles["LeftAlign"])],
            [Paragraph("Business ID No: 2014/004024/07", styles["LeftAlign"])],
        ]

        # Add logo
        try:
            logo_path = os.path.join(
                settings.STATIC_ROOT, "assets", "images", "cnl_logo.png"
            )

            header_data = [
                [
                    Table(company_details, colWidths=[4 * inch]),
                    Image(logo_path, width=2.5 * inch, height=1.5 * inch),
                ]
            ]
        except Exception as e:
            # Fallback if logo doesn't exist
            print(f"Logo error: {str(e)}")
            header_data = [
                [
                    Table(company_details, colWidths=[6 * inch]),
                    Paragraph("LOGO", styles["Normal"]),
                ]
            ]

        header_table = Table(header_data, colWidths=[6 * inch, 2 * inch])
        header_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(header_table)
        elements.append(Spacer(1, 20))

        # QUOTATION title
        elements.append(Paragraph("<b>QUOTATION (PREVIEW)</b>", styles["Heading1"]))
        elements.append(Spacer(1, 10))

        # Customer info and Quote details
        customer_info = [
            [Paragraph("<b>TO:</b>", styles["LeftAlign"])],
            [Paragraph(f"{quote.customer.company}", styles["LeftAlign"])],
            [
                Paragraph(
                    f"{quote.customer.email if quote.customer.email else ''}",
                    styles["LeftAlign"],
                )
            ],
            [
                Paragraph(
                    f"{quote.customer.number if quote.customer.number else ''}",
                    styles["LeftAlign"],
                )
            ],
        ]

        # Quote details
        quote_info = [
            [Paragraph(f"<b>Quote No:</b> {quote.quote_number}", styles["RightAlign"])],
            [
                Paragraph(
                    f"<b>Date:</b> {quote.created_at.strftime('%d %B %Y')}",
                    styles["RightAlign"],
                )
            ],
            [
                Paragraph(
                    f"<b>Valid until:</b> {(quote.created_at + timezone.timedelta(days=30)).strftime('%d %B %Y')}",
                    styles["RightAlign"],
                )
            ],
        ]

        info_data = [
            [
                Table(customer_info, colWidths=[4 * inch]),
                Table(quote_info, colWidths=[4 * inch]),
            ]
        ]
        info_table = Table(info_data, colWidths=[4 * inch, 4 * inch])
        info_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(info_table)
        elements.append(Spacer(1, 20))

        # Items table
        table_data = [["Description", "Qty", "Unit Price", "Total"]]
        total = 0

        # Use only the selected items
        for item in items:
            amount = item.quantity * item.selling_price
            total += amount
            table_data.append(
                [
                    # Correct the line below
                    Paragraph(
                        (item.quote_reference or item.description).replace(
                            "\n", "<br />"
                        ),
                        styles["DescriptionStyle"],
                    ),
                    str(item.quantity),
                    f"R {item.selling_price:,.2f}",
                    f"R {amount:,.2f}",
                ]
            )

        # Add VAT and total
        vat = total * Decimal("0.15")
        grand_total = total + vat

        table_data.extend(
            [
                [
                    "",
                    "",
                    Paragraph("<b>Subtotal:</b>", styles["RightAlign"]),
                    f"R {total:,.2f}",
                ],
                [
                    "",
                    "",
                    Paragraph("<b>VAT (15%):</b>", styles["RightAlign"]),
                    f"R {vat:,.2f}",
                ],
                [
                    "",
                    "",
                    Paragraph("<b>Total:</b>", styles["GrandTotal"]),
                    f"R {grand_total:,.2f}",
                ],
            ]
        )

        table = Table(
            table_data, colWidths=[4 * inch, 1 * inch, 1.5 * inch, 1.5 * inch]
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B2BE80")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5B6711")),
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -4), colors.white),
                    ("LINEBELOW", (0, 0), (-1, -4), 0.25, colors.black),
                    ("LINEABOVE", (-2, -3), (-1, -3), 1, colors.black),
                    ("LINEABOVE", (-2, -1), (-1, -1), 2, colors.black),
                    # Add this to align content to the TOP of cells
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(table)

        # Terms and conditions
        elements.append(Spacer(1, 30))
        elements.append(Paragraph("<b>Terms and Conditions:</b>", styles["Heading4"]))
        terms = [
            "1. This quotation is valid for 30 days from the date of issue.",
            "2. Prices are quoted excluding VAT unless otherwise stated.",
            "3. Lead time will be confirmed upon receipt of order.",
        ]
        for term in terms:
            elements.append(Paragraph(term, styles["LeftAlign"]))

        # Banking details - CNL specific
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("<b>Banking Details:</b>", styles["Heading4"]))
        banking_info = [
            "Standard Bank - Carletonville",
            "Current Account",
            "Branch Code: 016141",
            "Account Number: 022196552",
        ]

        for info in banking_info:
            elements.append(Paragraph(info, styles["LeftAlign"]))

        # Add a preview watermark
        elements.append(Spacer(1, 20))
        elements.append(
            Paragraph(
                "<b>PREVIEW ONLY - NOT YET SUBMITTED FOR APPROVAL</b>",
                styles["RightAlign"],
            )
        )

        # BUILD THE DOCUMENT
        doc.build(elements)

        # Just return the preview without saving or changing status
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="Preview-CNL-{quote.quote_number}.pdf"'
        )

        # Restore original letterhead
        quote.company_letterhead = original_letterhead

        return response

    except Exception as e:
        import traceback

        print(f"ERROR GENERATING CNL PREVIEW: {str(e)}")
        print(traceback.format_exc())

        messages.error(request, f"Error generating preview: {str(e)}")
        return redirect("quotes:quote_process", pk=quote_id)


@login_required
def preview_isherwood_quote_pdf(request, quote_id):
    """Preview an Isherwood quote without saving or changing status"""
    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id)

        # Temporarily force ISHERWOOD letterhead just for preview
        original_letterhead = quote.company_letterhead
        quote.company_letterhead = "ISHERWOOD"

        # Get selected items
        selected_items_param = request.GET.get("items", "")

        if selected_items_param:
            selected_item_ids = selected_items_param.split(",")
            items = quote.items.filter(id__in=selected_item_ids)
        else:
            items = (
                quote.items.filter(cost_price__gt=0, markup__gt=0)
                .exclude(description__isnull=True)
                .exclude(description="")
            )

        if not items.exists():
            messages.error(request, "No complete items selected for the quote PDF.")
            return redirect("quotes:quote_process", pk=quote_id)

        # Create PDF
        buffer = BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        # Enhanced styles - copy all style definitions from your generate_isherwood_quote_pdf function
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                name="RightAlign",
                parent=styles["Normal"],
                alignment=2,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="LeftAlign",
                parent=styles["Normal"],
                alignment=0,
                spaceBefore=6,
                spaceAfter=6,
            )
        )
        styles.add(
            ParagraphStyle(
                name="CompanyName",
                parent=styles["Heading1"],
                fontSize=14,
                textColor=colors.HexColor("#000000"),
                alignment=0,
                spaceBefore=12,
                spaceAfter=12,
            )
        )
        styles.add(
            ParagraphStyle(
                name="GrandTotal",
                parent=styles["Normal"],
                fontSize=12,
                fontName="Helvetica-Bold",
                alignment=2,
                spaceBefore=6,
                spaceAfter=6,
            )
        )

        # Add a custom paragraph style for descriptions with better word wrapping
        styles.add(
            ParagraphStyle(
                name="DescriptionStyle",
                parent=styles["LeftAlign"],
                wordWrap="CJK",  # Better word wrapping for all text types
                spaceBefore=2,
                spaceAfter=2,
                leading=14,  # Slightly more space between lines
            )
        )

        elements = []

        # ISHERWOOD MINING SUPPLIES specific header with correct details
        company_details = [
            [
                Paragraph(
                    "<b>ISHERWOOD MINING SUPPLIES (PTY) LTD</b>", styles["CompanyName"]
                )
            ],
            [Paragraph("VAT No: 4590136331", styles["LeftAlign"])],
            [
                Paragraph(
                    "Physical Address: 47 Station Street, Carletonville, 2499",
                    styles["LeftAlign"],
                )
            ],
            [Paragraph("Contact: +27 18 786 2499", styles["LeftAlign"])],
            [Paragraph("Email: laura@wfsales.co.za", styles["LeftAlign"])],
        ]

        # Add logo
        try:
            logo_path = os.path.join(
                settings.STATIC_ROOT, "assets", "images", "isherwood_logo.png"
            )

            header_data = [
                [
                    Table(company_details, colWidths=[4 * inch]),
                    Image(logo_path, width=2.5 * inch, height=1.5 * inch),
                ]
            ]
        except Exception as e:
            # Fallback if logo doesn't exist
            print(f"Logo error: {str(e)}")
            header_data = [
                [
                    Table(company_details, colWidths=[6 * inch]),
                    Paragraph("ISHERWOOD", styles["Normal"]),
                ]
            ]

        header_table = Table(header_data, colWidths=[6 * inch, 2 * inch])
        header_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(header_table)
        elements.append(Spacer(1, 20))

        # QUOTATION title
        elements.append(Paragraph("<b>QUOTATION (PREVIEW)</b>", styles["Heading1"]))
        elements.append(Spacer(1, 10))

        # Customer info and Quote details
        customer_info = [
            [Paragraph("<b>TO:</b>", styles["LeftAlign"])],
            [Paragraph(f"{quote.customer.company}", styles["LeftAlign"])],
            [
                Paragraph(
                    f"{quote.customer.email if quote.customer.email else ''}",
                    styles["LeftAlign"],
                )
            ],
            [
                Paragraph(
                    f"{quote.customer.number if quote.customer.number else ''}",
                    styles["LeftAlign"],
                )
            ],
        ]

        # Quote details
        quote_info = [
            [Paragraph(f"<b>Quote No:</b> {quote.quote_number}", styles["RightAlign"])],
            [
                Paragraph(
                    f"<b>Date:</b> {quote.created_at.strftime('%d %B %Y')}",
                    styles["RightAlign"],
                )
            ],
            [
                Paragraph(
                    f"<b>Valid until:</b> {(quote.created_at + timezone.timedelta(days=30)).strftime('%d %B %Y')}",
                    styles["RightAlign"],
                )
            ],
        ]

        info_data = [
            [
                Table(customer_info, colWidths=[4 * inch]),
                Table(quote_info, colWidths=[4 * inch]),
            ]
        ]
        info_table = Table(info_data, colWidths=[4 * inch, 4 * inch])
        info_table.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(info_table)
        elements.append(Spacer(1, 20))

        # Items table
        table_data = [["Description", "Qty", "Unit Price", "Total"]]
        total = 0

        # Use only the selected items
        for item in items:
            amount = item.quantity * item.selling_price
            total += amount
            table_data.append(
                [
                    # Correct the line below
                    Paragraph(
                        (item.quote_reference or item.description).replace(
                            "\n", "<br />"
                        ),
                        styles["DescriptionStyle"],
                    ),
                    str(item.quantity),
                    f"R {item.selling_price:,.2f}",
                    f"R {amount:,.2f}",
                ]
            )

        # Add VAT and total
        vat = total * Decimal("0.15")
        grand_total = total + vat

        table_data.extend(
            [
                [
                    "",
                    "",
                    Paragraph("<b>Subtotal:</b>", styles["RightAlign"]),
                    f"R {total:,.2f}",
                ],
                [
                    "",
                    "",
                    Paragraph("<b>VAT (15%):</b>", styles["RightAlign"]),
                    f"R {vat:,.2f}",
                ],
                [
                    "",
                    "",
                    Paragraph("<b>Total:</b>", styles["GrandTotal"]),
                    f"R {grand_total:,.2f}",
                ],
            ]
        )

        table = Table(
            table_data, colWidths=[4 * inch, 1 * inch, 1.5 * inch, 1.5 * inch]
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#B2BE80")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5B6711")),
                    ("ALIGN", (0, 0), (0, -1), "LEFT"),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -4), colors.white),
                    ("LINEBELOW", (0, 0), (-1, -4), 0.25, colors.black),
                    ("LINEABOVE", (-2, -3), (-1, -3), 1, colors.black),
                    ("LINEABOVE", (-2, -1), (-1, -1), 2, colors.black),
                    # Add this to align content to the TOP of cells
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        elements.append(table)

        # Terms and conditions - Isherwood specific
        elements.append(Spacer(1, 30))
        elements.append(Paragraph("<b>Terms and Conditions:</b>", styles["Heading4"]))
        terms = [
            "1. This quotation is valid for 30 days from the date of issue.",
            "2. Prices are quoted excluding VAT unless otherwise stated.",
            "3. Lead time will be confirmed upon receipt of order.",
            "4. Isherwood Mining Supplies standard terms apply to all orders.",
        ]
        for term in terms:
            elements.append(Paragraph(term, styles["LeftAlign"]))

        # Banking details - Isherwood specific
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("<b>Banking Details:</b>", styles["Heading4"]))
        banking_info = [
            "Bank: FNB",
            "Account Name: Isherwood Mining Supplies (Pty) Ltd",
            "Account Number: 02-290-746-7",
            "Branch Code: 016141",
        ]

        for info in banking_info:
            elements.append(Paragraph(info, styles["LeftAlign"]))

        # Add a preview watermark
        elements.append(Spacer(1, 20))
        elements.append(
            Paragraph(
                "<b>PREVIEW ONLY - NOT YET SUBMITTED FOR APPROVAL</b>",
                styles["RightAlign"],
            )
        )

        # BUILD THE DOCUMENT
        doc.build(elements)

        # Just return the preview without saving or changing status
        buffer.seek(0)
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = (
            f'inline; filename="Preview-ISH-{quote.quote_number}.pdf"'
        )

        # Restore original letterhead
        quote.company_letterhead = original_letterhead

        return response

    except Exception as e:
        import traceback

        print(f"ERROR GENERATING ISHERWOOD PREVIEW: {str(e)}")
        print(traceback.format_exc())

        messages.error(request, f"Error generating preview: {str(e)}")
        return redirect("quotes:quote_process", pk=quote_id)


@login_required
def upload_attachments(request, quote_id):
    """Upload additional attachments to an existing quote"""
    quote = get_object_or_404(QuoteRequest, id=quote_id)

    # Check permissions - only assigned user or rep can upload
    if request.user != quote.rep and request.user != quote.assigned_to:
        messages.error(
            request, "You don't have permission to add attachments to this quote."
        )
        return redirect("quotes:quote_detail", pk=quote_id)

    if request.method == "POST":
        attachment_files = request.FILES.getlist("attachments[]")

        if not attachment_files:
            messages.error(request, "No files were selected.")
            return redirect("quotes:quote_detail", pk=quote_id)

        # Save all attachments
        for uploaded_file in attachment_files:
            attachment = QuoteAttachment(
                quote=quote, file=uploaded_file, filename=uploaded_file.name
            )
            attachment.save()

        messages.success(
            request, f"{len(attachment_files)} attachment(s) uploaded successfully."
        )

    return redirect("quotes:quote_detail", pk=quote_id)


@login_required
def update_customer(request, quote_id):
    """Update customer information for a quote"""
    quote = get_object_or_404(QuoteRequest, id=quote_id)

    # Security check - only assigned user, rep, or admin can update
    if not (
        request.user == quote.rep
        or request.user == quote.assigned_to
        or request.user.is_staff
    ):
        messages.error(
            request, "You don't have permission to update this customer information."
        )
        return redirect("quotes:quote_detail", pk=quote_id)

    if request.method == "POST":
        # Check if customer was selected from dropdown
        customer_id = request.POST.get("customer_id")

        if customer_id and customer_id.strip():
            # If a customer was selected from dropdown, use that customer
            try:
                from wfdash.models import Customers

                selected_customer = Customers.objects.get(id=customer_id)
                quote.customer = selected_customer
                quote.save()
                messages.success(request, "Customer information updated successfully.")
            except Exception as e:
                messages.error(request, f"Error updating customer: {str(e)}")
        else:
            # Otherwise use manually entered information
            customer_name = request.POST.get("customer_name", "")
            company_name = request.POST.get("company_name", "")
            email = request.POST.get("email", "")
            phone = request.POST.get("phone", "")

            # Update the customer information
            customer = quote.customer
            customer.customer = customer_name
            customer.company = company_name
            customer.email = email
            customer.number = phone
            customer.save()

            # Add success message
            messages.success(request, "Customer information updated successfully.")

    return redirect("quotes:quote_detail", pk=quote_id)


@login_required
def archived_quotes(request):
    """Display archived quotes with comprehensive search functionality"""

    # Base queryset for archived quotes - approved, completed and emailed
    quotes_list = (
        QuoteRequest.objects.filter(
            Q(status="approved") | Q(status="complete") | Q(status="emailed"),
            pdf_file__isnull=False,
        )
        .select_related(
            "customer",
            "rep",  # Optimize by selecting related models
        )
        .prefetch_related(
            "items"  # Also prefetch items for efficient access
        )
        .order_by("-pdf_generated_at")
    )

    # Total count for display
    total_count = quotes_list.count()

    # Search functionality
    search_query = request.GET.get("search", "")
    if search_query:
        # Enhanced search across multiple fields including items
        quotes_list = quotes_list.filter(
            # Quote fields
            Q(quote_number__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(notes__icontains=search_query)
            | Q(quote_reference__icontains=search_query)
            |
            # Customer fields
            Q(customer__company__icontains=search_query)
            | Q(customer__customer__icontains=search_query)
            | Q(customer__email__icontains=search_query)
            |
            # Rep fields
            Q(rep__first_name__icontains=search_query)
            | Q(rep__last_name__icontains=search_query)
            | Q(rep__username__icontains=search_query)
            | Q(rep__email__icontains=search_query)
            |
            # Item fields - search across all quote items
            Q(items__description__icontains=search_query)
            | Q(items__quote_reference__icontains=search_query)
            | Q(items__notes__icontains=search_query)
            | Q(items__supplier__suppliername__icontains=search_query)
            |
            # Price fields - convert search to number if possible for price comparison
            Q(items__cost_price__icontains=search_query)
            | Q(items__selling_price__icontains=search_query)
        ).distinct()  # Use distinct to avoid duplicates

    # Pagination
    paginator = Paginator(quotes_list, 10)  # Show 10 quotes per page
    page = request.GET.get("page")
    quotes = paginator.get_page(page)

    context = {
        "quotes": quotes,
        "segment": "archived_quotes",
        "title": "Archived Quotes",
        "search_query": search_query,
        "total_count": total_count,
    }

    return render(request, "quotes/archived_quotes.html", context)
