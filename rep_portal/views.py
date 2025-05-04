import os
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, HttpResponseBadRequest
from django.forms import formset_factory
from django.utils.crypto import get_random_string
from django.db import transaction
from django.db.models import (
    Q,
    Value,
    CharField,
    Case,
    When,
    IntegerField,
    F,
    DecimalField,
)
from django.db.models.functions import Concat, Coalesce, Now
from django.utils.timesince import timesince
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from decimal import Decimal
import json
import logging
import datetime

from .forms import (
    RepQuoteForm,
    RepOrderForm,
    ItemForm,
    ItemFormSet,
    RepQuoteItemForm,
    RepQuoteItemFormSet,
    RepDeliveryForm,
    DeliveryItemFormSet,
)
from .models import RepSubmission
from quotes.models import QuoteRequest, QuoteItem, QuoteAttachment
from orders.models import Order, OrderItem
from wfdash.models import Customers, Company
from quotes.utils import generate_unique_quote_number
from delivery_notes.models import DeliveryNote, DeliveryItem
from stock_management.models import StockItem
from internal_stock.models import PriceListItem

logger = logging.getLogger(__name__)


@login_required
def home(request):
    """Home page for rep portal"""
    return render(request, "rep_portal/home.html")


@login_required
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def serve_portal_serviceworker(request):
    """Serve the rep portal service worker with proper headers"""
    sw_path = os.path.join(
        settings.STATIC_ROOT, "rep_portal", "portal-serviceworker.js"
    )

    if not os.path.exists(sw_path):
        sw_path = os.path.join(
            settings.BASE_DIR,
            "rep_portal",
            "static",
            "rep_portal",
            "portal-serviceworker.js",
        )

    with open(sw_path, "r") as f:
        content = f.read()

    response = HttpResponse(content, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/rep/"
    return response


@login_required
def quote_request(request):
    if request.method == "POST":
        form = RepQuoteForm(request.POST)
        formset = RepQuoteItemFormSet(request.POST)

        if not form.is_valid():
            for field, errors in form.errors.items():
                print(f"Field '{field}' errors: {errors}")

        if formset.is_valid():
            valid_formset = formset
        else:
            has_data = False
            for form_data in formset.cleaned_data:
                if form_data and not form_data.get("DELETE", False):
                    has_data = True
                    break

            if not has_data and len(formset.forms) > 1:
                valid_formset = False
                form.add_error(
                    None, "Please add at least one item to your quote request."
                )
            else:
                valid_formset = False

        if form.is_valid() and valid_formset is not False:
            try:
                with transaction.atomic():
                    rep = request.user

                    if form.cleaned_data.get("customer"):
                        customer = form.cleaned_data["customer"]
                    else:
                        customer, created = Customers.objects.get_or_create(
                            email=form.cleaned_data["email"],
                            defaults={
                                "customer": form.cleaned_data["name"],
                                "company": form.cleaned_data.get("company", ""),
                                "number": form.cleaned_data.get("phone", ""),
                            },
                        )

                    description = form.cleaned_data.get("description", "")
                    if not description:
                        for item_form in formset:
                            if (
                                item_form.is_valid()
                                and item_form.cleaned_data
                                and "description" in item_form.cleaned_data
                            ):
                                first_item = item_form.cleaned_data["description"]
                                description = f"Quote request for: {first_item}"
                                break

                        if not description:
                            description = (
                                f"Quote request - {timezone.now().strftime('%Y-%m-%d')}"
                            )

                    quote = QuoteRequest(
                        user=rep,
                        rep=rep,
                        assigned_to=None,
                        quote_number=generate_unique_quote_number(),
                        customer=customer,
                        description=description,
                        status="new",
                        has_attachments=bool(request.FILES.getlist("attachments[]")),
                    )
                    quote.save()

                    items = []
                    for item_form in valid_formset:
                        if (
                            item_form.has_changed()
                            and item_form.cleaned_data
                            and "description" in item_form.cleaned_data
                        ):
                            item = QuoteItem.objects.create(
                                quote=quote,
                                description=item_form.cleaned_data["description"],
                                quantity=item_form.cleaned_data["quantity"],
                            )
                            items.append(item)

                    attachment_files = request.FILES.getlist("attachments[]")
                    for uploaded_file in attachment_files:
                        attachment = QuoteAttachment(
                            quote=quote, file=uploaded_file, filename=uploaded_file.name
                        )
                        attachment.save()

                    messages.success(
                        request,
                        f"Quote {quote.quote_number} created successfully and is now in the processing queue.",
                    )
                    return redirect(
                        "rep_portal:success", type="quote", reference=quote.quote_number
                    )

            except Exception as e:
                import traceback

                traceback.print_exc()
                form.add_error(None, f"Error: {str(e)}")
    else:
        form = RepQuoteForm()
        formset = RepQuoteItemFormSet()

    return render(
        request, "rep_portal/quote_form.html", {"form": form, "formset": formset}
    )


@login_required
def order_submit(request):
    if request.method == "POST":
        form = RepOrderForm(request.POST)
        formset = ItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    rep = request.user

                    customer = form.cleaned_data.get("customer")
                    if not customer:
                        form.add_error(None, "Please select an existing customer")
                        raise ValueError("No customer selected")

                    company_name = (
                        customer.company if customer.company else customer.customer
                    )

                    try:
                        company = Company.objects.get(company=company_name)
                    except Company.DoesNotExist:
                        company = Company.objects.create(
                            company=company_name,
                            address="Address not provided",
                        )

                    prefix = "WO"
                    date_str = timezone.now().strftime("%y%m%d")
                    random_suffix = get_random_string(
                        length=3, allowed_chars="0123456789"
                    )
                    order_number = f"{prefix}{date_str}{random_suffix}"

                    order_data = {
                        "order_number": order_number,
                        "company": company,
                        "rep": rep,
                        "status": "new",
                        "notes": form.cleaned_data.get("notes", "") or "",
                    }

                    customer_info = (
                        f"Customer Name: {form.cleaned_data.get('name')}\n"
                        f"Customer Email: {form.cleaned_data.get('email')}\n"
                        f"Customer Phone: {form.cleaned_data.get('phone')}\n"
                    )
                    order_data["notes"] = f"{customer_info}\n{order_data['notes']}"

                    po_number = form.cleaned_data.get("purchase_order", "")
                    if po_number:
                        order_data["notes"] = f"PO: {po_number}\n{order_data['notes']}"

                    order = Order.objects.create(**order_data)

                    for item_form in formset:
                        if item_form.has_changed() and item_form.cleaned_data:
                            OrderItem.objects.create(
                                order=order,
                                description=item_form.cleaned_data["description"],
                                quantity=item_form.cleaned_data["quantity"],
                                notes=item_form.cleaned_data.get("notes", ""),
                                selling_price=Decimal("0.00"),
                            )

                    messages.success(
                        request, f"Order {order.order_number} created successfully"
                    )
                    return redirect(
                        "rep_portal:success", type="order", reference=order.order_number
                    )

            except ValueError as e:
                print(f"Validation error: {str(e)}")
            except Exception as e:
                import traceback

                traceback.print_exc()
                form.add_error(None, f"Error: {str(e)}")
        else:
            if not form.is_valid():
                print(f"Form errors: {form.errors}")
            if not formset.is_valid():
                print(f"Formset errors: {formset.errors}")
    else:
        form = RepOrderForm()
        formset = ItemFormSet(prefix="items")

    return render(
        request, "rep_portal/order_form.html", {"form": form, "formset": formset}
    )


@login_required
def delivery_create(request):
    """Create a delivery note using the rep portal interface"""
    if request.method == "POST":
        form = RepDeliveryForm(request.POST)
        formset = DeliveryItemFormSet(request.POST, prefix="items")

        if form.is_valid() and formset.is_valid():
            try:
                with transaction.atomic():
                    customer = form.cleaned_data.get("customer")
                    company = None

                    if customer:
                        company_name = customer.company or customer.customer
                        company, _ = Company.objects.get_or_create(company=company_name)
                    else:
                        company_name = form.cleaned_data.get("name", "Unknown")
                        company, _ = Company.objects.get_or_create(company=company_name)

                    prefix = "DN"
                    date_str = timezone.now().strftime("%y%m%d")
                    random_suffix = get_random_string(
                        length=3, allowed_chars="0123456789"
                    )
                    delivery_number = f"{prefix}{date_str}{random_suffix}"

                    digital_signature = request.POST.get("digital_signature", "")
                    signed_by = request.POST.get(
                        "signed_by", form.cleaned_data.get("name", "")
                    )
                    has_signature = bool(digital_signature)

                    delivery = DeliveryNote.objects.create(
                        delivery_number=delivery_number,
                        company=company,
                        contact_person=form.cleaned_data.get("name", ""),
                        contact_email=form.cleaned_data.get("email", ""),
                        contact_phone=form.cleaned_data.get("phone", ""),
                        customer_order_number=form.cleaned_data.get("order_number", ""),
                        notes=form.cleaned_data.get("notes", ""),
                        created_by=request.user,
                        delivery_date=timezone.now().date(),
                        status="signed" if has_signature else "draft",
                        digital_signature=digital_signature,
                        signed_by=signed_by,
                        signature_date=timezone.now() if has_signature else None,
                    )

                    for item_form in formset:
                        if item_form.has_changed() and item_form.cleaned_data:
                            DeliveryItem.objects.create(
                                delivery_note=delivery,
                                description=item_form.cleaned_data["description"],
                                quantity=item_form.cleaned_data["quantity"],
                                notes=item_form.cleaned_data.get("notes", ""),
                            )

                    try:
                        from delivery_notes.views import generate_delivery_pdf

                        request._skip_response = True

                        generate_delivery_pdf(request, delivery.pk)

                    except Exception as pdf_error:
                        import traceback

                        traceback.print_exc()

                    return redirect(
                        "rep_portal:success_with_id",
                        type="delivery",
                        reference=delivery_number,
                        delivery_id=delivery.pk,
                    )

            except Exception as e:
                import traceback

                traceback.print_exc()
                form.add_error(None, f"Error: {str(e)}")
        else:
            print(f"Form errors: {form.errors}")
            if formset.errors:
                print(f"Formset errors: {formset.errors}")
    else:
        form = RepDeliveryForm()
        formset = DeliveryItemFormSet(prefix="items")

    return render(
        request, "rep_portal/delivery_form.html", {"form": form, "formset": formset}
    )


@login_required
def offline(request):
    """Render the offline page for the portal"""
    return render(request, "rep_portal/offline.html")


@login_required
def success(request, type, reference, delivery_id=None):
    """Success page after form submission"""
    title = "Success!"
    message = "Your request has been processed successfully."
    icon = "fa-check-circle"

    if type == "delivery":
        title = "Delivery Note Created!"
        message = (
            "Your delivery note has been successfully created and is ready to view."
        )
        icon = "fa-truck"
    elif type == "quote":
        title = "Quote Request Submitted!"
        message = "Your quote request has been successfully submitted."
        icon = "fa-file-invoice-dollar"
    elif type == "order":
        title = "Order Submitted!"
        message = "Your order has been successfully submitted."
        icon = "fa-shopping-cart"

    context = {
        "type": type,
        "title": title,
        "message": message,
        "icon": icon,
        "reference": reference,
        "delivery_id": delivery_id,
    }

    return render(request, "rep_portal/success.html", context)


@login_required
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def portal_serviceworker(request):
    """Serve service worker with proper headers"""
    sw_path = os.path.join(
        settings.STATIC_ROOT, "rep_portal", "portal-serviceworker.js"
    )

    if not os.path.exists(sw_path):
        sw_path = os.path.join(
            settings.BASE_DIR,
            "rep_portal",
            "static",
            "rep_portal",
            "portal-serviceworker.js",
        )

    try:
        with open(sw_path, "r") as f:
            content = f.read()

        response = HttpResponse(content, content_type="application/javascript")
        response["Service-Worker-Allowed"] = "/rep/"
        return response
    except FileNotFoundError:
        content = """
        // Rep Portal Service Worker
        const CACHE_NAME = 'rep-portal-cache-v1';

        self.addEventListener('install', event => {
            console.log('Rep Portal Service Worker installing.');
        });

        self.addEventListener('fetch', event => {
            event.respondWith(
                fetch(event.request)
                    .catch(() => {
                        return caches.match(event.request)
                            .then(response => {
                                if (response) {
                                    return response;
                                }
                                
                                if (event.request.mode === 'navigate') {
                                    return caches.match('/rep/offline/');
                                }
                                
                                return new Response('Not found', {
                                    status: 404,
                                    statusText: 'Not found'
                                });
                            });
                    })
            );
        });
        """
        response = HttpResponse(content, content_type="application/javascript")
        response["Service-Worker-Allowed"] = "/rep/"
        return response


@login_required
def get_customer_details(request, customer_id):
    """API endpoint to get customer details for auto-filling form"""
    try:
        customer = Customers.objects.get(id=customer_id)
        data = {
            "customer": customer.customer,
            "email": customer.email,
            "number": customer.number,
            "company": customer.company,
        }
        return JsonResponse(data)
    except Customers.DoesNotExist:
        return JsonResponse({"error": "Customer not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def tasks(request):
    """Tasks dashboard for managing pending actions"""
    pending_quotes = QuoteRequest.objects.filter(
        status="approval_pending", rep=request.user
    ).order_by("-created_at")

    delivery_notes = []

    all_notes = DeliveryNote.objects.filter(created_by=request.user).order_by(
        "-created_at"
    )

    for note in all_notes:
        items_missing_price = note.items.filter(
            Q(price__isnull=True) | Q(price=0)
        ).count()

        if items_missing_price > 0:
            note.items_missing_price = items_missing_price
            delivery_notes.append(note)

    context = {
        "pending_quotes": pending_quotes,
        "delivery_notes": delivery_notes,
    }

    return render(request, "rep_portal/tasks.html", context)


@login_required
@require_POST
def approve_quote(request, quote_id):
    """API endpoint to approve a quote"""
    quote = get_object_or_404(QuoteRequest, id=quote_id, rep=request.user)

    if quote.status != "approval_pending":
        return JsonResponse(
            {"success": False, "error": "Quote is not pending approval"}
        )

    try:
        quote.status = "approved"
        quote.save()
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


@login_required
@require_POST
def reject_quote(request, quote_id):
    """API endpoint to reject a quote"""
    data = json.loads(request.body)
    reason = data.get("reason", "")

    quote = get_object_or_404(QuoteRequest, id=quote_id, rep=request.user)

    if quote.status != "approval_pending":
        return JsonResponse(
            {"success": False, "error": "Quote is not pending approval"}
        )

    try:
        quote.status = "rejected"
        quote.notes += f"\n\nRejected by {request.user.get_full_name()} on {timezone.now().strftime('%Y-%m-%d %H:%M')}. Reason: {reason}"
        quote.save()
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})


@login_required
def get_delivery_items(request, delivery_id):
    """API endpoint to get delivery items for a specific delivery note"""
    delivery = get_object_or_404(DeliveryNote, id=delivery_id, created_by=request.user)

    items = []
    for item in delivery.items.all():
        items.append(
            {
                "id": item.id,
                "description": item.description,
                "quantity": item.quantity,
                "price": float(item.price) if item.price else None,
            }
        )

    return JsonResponse({"success": True, "items": items})


@login_required
@require_POST
def update_prices(request, delivery_id):
    """API endpoint to update prices for delivery items"""
    data = json.loads(request.body)
    items_data = data.get("items", {})

    delivery = get_object_or_404(DeliveryNote, id=delivery_id, created_by=request.user)

    try:
        with transaction.atomic():
            updated_count = 0
            for item_id, item_data in items_data.items():
                try:
                    item = DeliveryItem.objects.get(
                        id=int(item_id), delivery_note=delivery
                    )

                    price = item_data.get("price")
                    cost_price = item_data.get("cost_price")
                    markup = item_data.get("markup")

                    if price is not None:
                        item.price = Decimal(str(price))

                    if cost_price is not None:
                        item.cost_price = Decimal(str(cost_price))

                    if markup is not None:
                        item.markup = Decimal(str(markup))

                    item.save()
                    updated_count += 1

                except (DeliveryItem.DoesNotExist, ValueError, TypeError) as e:
                    continue

            return JsonResponse(
                {
                    "success": True,
                    "message": f"Successfully updated {updated_count} items",
                    "updated_count": updated_count,
                }
            )

    except Exception as e:
        import traceback

        traceback.print_exc()
        return JsonResponse({"success": False, "error": str(e)})


@login_required
def get_quote_details(request, quote_id):
    """API endpoint to get full quote details for preview"""
    try:
        quote = get_object_or_404(QuoteRequest, id=quote_id, rep=request.user)

        items = []
        for item in quote.items.all():
            items.append(
                {
                    "id": item.id,
                    "description": item.description,
                    "quantity": item.quantity,
                    "notes": item.notes if hasattr(item, "notes") else "",
                }
            )

        attachments = []
        for attachment in quote.attachments.all():
            attachments.append(
                {
                    "id": attachment.id,
                    "filename": attachment.filename,
                    "url": attachment.file.url if attachment.file else None,
                }
            )

        data = {
            "id": quote.id,
            "quote_number": quote.quote_number,
            "customer_name": quote.customer.customer if quote.customer else "Unknown",
            "company": quote.customer.company if quote.customer else "Unknown",
            "created_at": quote.created_at.strftime("%d %b %Y"),
            "created_by": quote.user.get_full_name() if quote.user else "Unknown",
            "rep": quote.rep.get_full_name() if quote.rep else "Unknown",
            "description": quote.description,
            "notes": quote.notes,
            "status": quote.status,
            "items": items,
            "attachments": attachments,
        }

        return JsonResponse(data)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def rep_item_search_api(request):
    """
    API endpoint for rep portal item autocomplete search.
    Searches OrderItem, QuoteItem, and PriceListItem.
    Returns detailed JSON for richer display.
    """
    term = request.GET.get("term", "").strip()
    field_id = request.GET.get("field_id", "unknown")  # For logging
    logger.debug(f"[Rep API Search] Received term '{term}' from field '{field_id}'")

    if len(term) < 2:
        return JsonResponse([], safe=False)

    results = []
    limit = 20
    processed_values = set()
    now = timezone.now()
    default_decimal = Value(
        Decimal("0.00"), output_field=DecimalField()
    )  # Default for Coalesce

    # --- ADJUSTED SEARCH LOGIC ---

    # 1. Search Order Items
    try:
        order_items_qs = (
            OrderItem.objects.filter(description__icontains=term)
            .select_related(
                "order",
                "order__quote",
                "order__quote__customer",
                "supplier",
            )
            .annotate(
                source_val=Value("Order", output_field=CharField()),
                created_at_val=Coalesce("order__created_at", Now()),
                customer_name=F("order__quote__customer__company"),
                selling_price_val=Coalesce("selling_price", default_decimal),
                cost_price_val=Coalesce("cost_price", default_decimal),
                supplier_name_val=F("supplier__suppliername"),
            )
            .order_by("-order__created_at")
            .values(
                "description",
                "customer_name",
                "created_at_val",
                "source_val",
                "selling_price_val",
                "cost_price_val",
                "supplier_name_val",
            )[:limit]
        )

        for item in order_items_qs:
            value = item["description"].strip()
            if value not in processed_values:
                cust_name = item["customer_name"] or "Unknown"
                label = f"{value} (Order: {cust_name})"
                time_text = "Unknown date"
                if item["created_at_val"]:
                    time_text = f"{timesince(item['created_at_val'], now=now)} ago"

                markup = None
                cost = item["cost_price_val"]
                selling = item["selling_price_val"]
                if cost and selling and cost > 0:
                    markup = ((selling - cost) / cost) * 100

                results.append(
                    {
                        "label": label,
                        "value": value,
                        "full_description": value,
                        "source": item["source_val"],
                        "time_text": time_text,
                        "company": cust_name,
                        "selling_price": float(selling) if selling else None,
                        "cost_price": float(cost) if cost else None,
                        "markup": float(markup) if markup is not None else None,
                        "supplier_name": item.get("supplier_name_val"),
                        "part_number": None,
                    }
                )
                processed_values.add(value)

    except Exception as e:
        logger.error(f"Error querying OrderItems in rep search: {e}", exc_info=True)

    # 2. Search Quote Items
    if len(results) < limit:
        try:
            quote_items_qs = (
                QuoteItem.objects.filter(description__icontains=term)
                .select_related("quote", "quote__customer", "supplier")
                .annotate(
                    source_val=Value("Quote", output_field=CharField()),
                    created_at_val=Coalesce("quote__created_at", Now()),
                    customer_name=F("quote__customer__company"),
                    selling_price_val=Coalesce("selling_price", default_decimal),
                    cost_price_val=Coalesce("cost_price", default_decimal),
                    supplier_name_val=F("supplier__suppliername"),
                )
                .order_by("-quote__created_at")
                .values(
                    "description",
                    "customer_name",
                    "created_at_val",
                    "source_val",
                    "selling_price_val",
                    "cost_price_val",
                    "supplier_name_val",
                )[: limit - len(results)]
            )

            for item in quote_items_qs:
                value = item["description"].strip()
                if value not in processed_values:
                    cust_name = item["customer_name"] or "Unknown"
                    label = f"{value} (Quote: {cust_name})"
                    time_text = "Unknown date"
                    if item["created_at_val"]:
                        time_text = f"{timesince(item['created_at_val'], now=now)} ago"

                    markup = None
                    cost = item["cost_price_val"]
                    selling = item["selling_price_val"]
                    if cost and selling and cost > 0:
                        markup = ((selling - cost) / cost) * 100

                    results.append(
                        {
                            "label": label,
                            "value": value,
                            "full_description": value,
                            "source": item["source_val"],
                            "time_text": time_text,
                            "company": cust_name,
                            "selling_price": float(selling) if selling else None,
                            "cost_price": float(cost) if cost else None,
                            "markup": float(markup) if markup is not None else None,
                            "supplier_name": item.get("supplier_name_val"),
                            "part_number": None,
                        }
                    )
                    processed_values.add(value)
        except Exception as e:
            logger.error(f"Error querying QuoteItems in rep search: {e}", exc_info=True)

    # 3. Search Price List Items
    if len(results) < limit:
        try:
            price_list_items_qs = (
                PriceListItem.objects.filter(
                    Q(description__icontains=term) | Q(part_number__icontains=term)
                )
                .select_related("price_list", "price_list__supplier")
                .annotate(
                    source_val=Value("Price List", output_field=CharField()),
                    is_valid=Case(
                        When(
                            Q(price_list__valid_from__lte=now.date())
                            & (
                                Q(price_list__valid_until__isnull=True)
                                | Q(price_list__valid_until__gte=now.date())
                            ),
                            then=Value(1),
                        ),
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                    selling_price_val=Coalesce("selling_price", default_decimal),
                    cost_price_val=Coalesce("cost_price", default_decimal),
                    markup_val=Coalesce("markup", default_decimal),
                    supplier_name_val=F("price_list__supplier__suppliername"),
                )
                .order_by("-is_valid", "-price_list__year", "-price_list__valid_from")
                .values(
                    "description",
                    "part_number",
                    "price_list__name",
                    "price_list__year",
                    "price_list__valid_from",
                    "price_list__valid_until",
                    "is_valid",
                    "source_val",
                    "selling_price_val",
                    "cost_price_val",
                    "markup_val",
                    "supplier_name_val",
                )[: limit - len(results)]
            )

            for item in price_list_items_qs:
                value = item["description"].strip()
                part_num = item["part_number"] or ""
                unique_key = f"{value}|{part_num}" if part_num else value

                if unique_key not in processed_values:
                    supplier_name = item.get("supplier_name_val") or "Unknown Supplier"
                    list_info = f"{item['price_list__name'] or 'Unknown List'} ({item['price_list__year'] or 'N/A'})"

                    label_parts = []
                    if part_num:
                        label_parts.append(f"[{part_num}]")
                    label_parts.append(value)
                    label_parts.append(f"({list_info} - {supplier_name})")
                    label = " ".join(label_parts)

                    time_text = "Validity Unknown"
                    today = now.date()
                    valid_from = item["price_list__valid_from"]
                    valid_until = item["price_list__valid_until"]
                    if item["is_valid"]:
                        if valid_until:
                            days_remaining = (valid_until - today).days
                            time_text = (
                                f"Valid ({days_remaining} days left)"
                                if days_remaining >= 0
                                else "Valid (Expiring Today)"
                            )
                        else:
                            time_text = "Valid (No Expiry)"
                    else:
                        if valid_from and today < valid_from:
                            days_until = (valid_from - today).days
                            time_text = f"Future ({days_until} days)"
                        elif valid_until and today > valid_until:
                            days_expired = (today - valid_until).days
                            time_text = f"Expired ({days_expired} days ago)"
                        else:
                            time_text = "Expired/Invalid"

                    selling = item["selling_price_val"]
                    cost = item["cost_price_val"]
                    markup = item["markup_val"]

                    if (
                        (markup is None or markup == 0)
                        and cost
                        and selling
                        and cost > 0
                    ):
                        markup = ((selling - cost) / cost) * 100

                    results.append(
                        {
                            "label": label,
                            "value": value,
                            "full_description": value,
                            "source": item["source_val"],
                            "time_text": time_text,
                            "company": supplier_name,
                            "selling_price": float(selling) if selling else None,
                            "cost_price": float(cost) if cost else None,
                            "markup": float(markup) if markup is not None else None,
                            "supplier_name": supplier_name,
                            "part_number": part_num,
                        }
                    )
                    processed_values.add(unique_key)
        except Exception as e:
            logger.error(
                f"Error querying PriceListItems in rep search: {e}", exc_info=True
            )

    logger.debug(
        f"[Rep API Search] Found {len(results)} unique results for term '{term}'"
    )
    return JsonResponse(results[:limit], safe=False)


@login_required
def rep_customer_detail_api(request, customer_id):
    try:
        customer = get_object_or_404(Customers, pk=customer_id)
        data = {
            "id": customer.id,
            "customer": customer.customer,
            "email": customer.email,
            "number": customer.number,
        }
        return JsonResponse(data)
    except Exception as e:
        logger.error(f"Error fetching customer details for ID {customer_id}: {e}")
        return JsonResponse(
            {"error": "Customer not found or error occurred"}, status=404
        )
