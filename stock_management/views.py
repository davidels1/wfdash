from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db import models
from decimal import Decimal, InvalidOperation
from .models import StockItem  # Import from local models
from driver_list.models import Collection  # Import from driver_list app
from itertools import groupby
from operator import attrgetter
import logging
import json  # Add this import
import os  # Add this import
from django.views.decorators.http import (
    require_POST,
    require_http_methods,
)  # Add require_http_methods here
from django.views.decorators.csrf import ensure_csrf_cookie  # Add this import
from reportlab.lib import colors  # Add this import
from reportlab.lib.pagesizes import letter, A4  # Add A4 import
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)  # Add this import
from reportlab.lib.styles import (
    getSampleStyleSheet,
    ParagraphStyle,
)  # Add ParagraphStyle import
from reportlab.lib.units import inch, cm, mm  # Add cm import
from io import BytesIO  # Add this import
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image
from django.db import transaction
from django.core.exceptions import ValidationError
from django.contrib import messages
from .utils import is_mobile
from delivery_notes.models import DeliveryNote, DeliveryItem
from delivery_notes.views import generate_delivery_pdf

# Add this import specifically - the model might be in a different app than 'wfdash'
try:
    from wfdash.models import Company
except ImportError:
    try:
        from customer_management.models import Company
    except ImportError:
        try:
            from orders.models import Company
        except ImportError:
            # Last resort - do a project-wide search for the Company model
            from django.apps import apps

            Company = apps.get_model("wfdash", "Company")

logger = logging.getLogger(__name__)


# Add this function to check status changes
def debug_item_status(item, before_status, after_status):
    logger.info(
        f"""
    Item Status Change:
    ID: {item.id}
    Before: {before_status}
    After: {after_status}
    Picked: {item.picked}
    Picked By: {item.picked_by}
    """
    )


@login_required
def stock_verification(request):
    # Print debug information about collections
    all_collected = Collection.objects.filter(status="collected").count()
    print(f"Total collected items: {all_collected}")

    # Query for collections to verify
    collections = (
        Collection.objects.filter(
            status="collected",
            stockitem__isnull=True,  # Only show unverified collections
        )
        .select_related(
            "order_item__order", "order_item__purchase_order", "supplier", "driver"
        )
        .order_by("supplier__suppliername")
    )

    print(f"Found {collections.count()} collections to verify after filtering")

    # Group collections by supplier and then by PO number
    grouped_collections = {}

    for collection in collections:
        supplier_name = collection.supplier.suppliername

        # Safely get the PO number
        po_number = "No PO"
        if (
            collection.order_item
            and hasattr(collection.order_item, "purchase_order")
            and collection.order_item.purchase_order
        ):
            po_number = collection.order_item.purchase_order.po_number

        if supplier_name not in grouped_collections:
            grouped_collections[supplier_name] = {
                "pos": {},
                "supplier_id": collection.supplier.id,
            }

        if po_number not in grouped_collections[supplier_name]["pos"]:
            grouped_collections[supplier_name]["pos"][po_number] = []

        grouped_collections[supplier_name]["pos"][po_number].append(collection)

    template_name = (
        "stock_management/stock_verification_mobile.html"
        if is_mobile(request)
        else "stock_management/stock_verification.html"
    )

    return render(request, template_name, {"grouped_collections": grouped_collections})


@login_required
def verify_stock(request, collection_id):
    if request.method == "POST":
        try:
            collection = get_object_or_404(Collection, id=collection_id)

            external_invoice_number = request.POST.get("external_invoice_number")
            external_invoice_date = request.POST.get("external_invoice_date")

            # Properly handle decimal conversion
            verified_quantity_str = request.POST.get("verified_quantity", "0")
            verified_quantity_str = verified_quantity_str.replace(",", ".")

            try:
                verified_quantity = Decimal(verified_quantity_str)
            except (InvalidOperation, ValueError):
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Invalid quantity format. Please use a valid number.",
                    },
                    status=400,
                )

            notes = request.POST.get("notes", "")

            # Check if quantity exceeds order quantity for notification
            excess_qty = 0
            order_qty = collection.order_item.quantity
            if verified_quantity > order_qty:
                excess_qty = verified_quantity - order_qty

            # Create StockItem with correct field names
            stock_item = StockItem.objects.create(
                order_item=collection.order_item,
                collection=collection,
                received_qty=verified_quantity,
                verified_quantity=verified_quantity,
                external_invoice_number=external_invoice_number,
                external_invoice_date=external_invoice_date,
                notes=notes
                + (f"\nExcess quantity: {excess_qty}" if excess_qty > 0 else ""),
                verified_by=request.user,
                status="verified",  # Initially set as verified, will be split when invoiced
            )

            # Update OrderItem status
            collection.order_item.item_status = "stock_verified"
            collection.order_item.save(update_fields=["item_status"])

            # Update collection status
            collection.status = "in_stock"
            collection.notes = (
                (collection.notes or "")
                + f"\nVerified by {request.user} on {timezone.now().strftime('%Y-%m-%d %H:%M')}"
            )
            collection.save()

            # Return success with excess information if any
            return JsonResponse(
                {
                    "status": "success",
                    "message": "Stock verified successfully"
                    + (f" ({excess_qty} units excess)" if excess_qty > 0 else ""),
                }
            )

        except Exception as e:
            import traceback

            traceback.print_exc()
            return JsonResponse(
                {"status": "error", "message": f"Error verifying stock: {str(e)}"},
                status=500,
            )

    return JsonResponse(
        {"status": "error", "message": "Invalid request method"}, status=405
    )


@login_required
def stock_list(request):
    """View stock items"""
    # Filter out items that have been delivered
    stock_items = StockItem.objects.exclude(status="delivered")

    stock_items = (
        StockItem.objects.filter(
            status="verified"  # Changed from 'in_stock' to 'verified'
        )
        .select_related(
            "order_item__order", "order_item__purchase_order", "collection__supplier"
        )
        .order_by("order_item__order__order_number", "created_at")
    )

    # Group items by order number
    grouped_items = {}
    for item in stock_items:
        order_number = item.order_item.order.order_number
        if order_number not in grouped_items:
            grouped_items[order_number] = []
        grouped_items[order_number].append(item)

    # Make sure companies are available for the modal
    companies = Company.objects.all().order_by("company")

    context = {
        "grouped_items": grouped_items,
        "companies": companies,
        # Other context variables...
    }

    return render(request, "stock_management/stock_list.html", context)


@login_required
def update_invoice(request, stock_id):
    """Update invoice details and split excess stock"""
    if request.method == "POST":
        stock_item = get_object_or_404(StockItem, id=stock_id)
        invoice_number = request.POST.get("invoice_number")
        invoice_date = request.POST.get("invoice_date")

        try:
            # Get order quantity and already invoiced quantity
            order_qty = stock_item.order_item.quantity
            already_invoiced = (
                StockItem.objects.filter(
                    order_item=stock_item.order_item, status="invoiced"
                ).aggregate(total=models.Sum("received_qty"))["total"]
                or 0
            )

            remaining_needed = order_qty - already_invoiced
            if stock_item.received_qty > remaining_needed and remaining_needed > 0:
                # Transaction to ensure both operations succeed or fail together
                with transaction.atomic():
                    # Create new stock item for excess
                    excess_qty = stock_item.received_qty - remaining_needed
                    # Update original item with needed quantity
                    stock_item.received_qty = remaining_needed
                    stock_item.invoice_number = invoice_number
                    stock_item.invoice_date = invoice_date
                    stock_item.status = "invoiced"
                    stock_item.save()

                    # Create new item for excess
                    excess_item = StockItem.objects.create(
                        collection=stock_item.collection,
                        order_item=stock_item.order_item,
                        received_qty=excess_qty,
                        verified_quantity=excess_qty,
                        external_invoice_number=stock_item.external_invoice_number,
                        external_invoice_date=stock_item.external_invoice_date,
                        verified_by=stock_item.verified_by,
                        status="office_stock",
                    )

                message = f"Invoice updated. {excess_qty} units moved to office stock."
            else:
                # Update original item as normal
                stock_item.invoice_number = invoice_number
                stock_item.invoice_date = invoice_date
                stock_item.status = "invoiced"
                stock_item.save()
                message = "Invoice details updated successfully"

            # Check if request expects JSON (AJAX)
            if "application/json" in request.headers.get("Accept", ""):
                return JsonResponse(
                    {
                        "status": "success",
                        "message": message,
                        "excess_created": stock_item.received_qty > remaining_needed
                        and remaining_needed > 0,
                    }
                )
            else:
                messages.success(request, message)
                return redirect("stock_management:stock_list")

        except Exception as e:
            error_message = f"Error updating invoice: {str(e)}"
            if "application/json" in request.headers.get("Accept", ""):
                return JsonResponse(
                    {"status": "error", "message": error_message}, status=400
                )
            else:
                messages.error(error_message)
                return redirect("stock_management:stock_list")

    # Handle non-POST requests
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse(
            {"status": "error", "message": "Invalid request method"}, status=405
        )
    else:
        return redirect("stock_management:stock_list")


@login_required
def ready_for_delivery(request):
    """View items ready for delivery grouped by company then invoice"""
    stock_items = (
        StockItem.objects.filter(status="ready_for_delivery", picked=True)
        .select_related(
            "order_item__order__company",
            "collection__supplier",
            "order_item__purchase_order",
        )
        .order_by(
            "order_item__order__company__company", "invoice_number", "invoice_date"
        )
    )

    # Group items by company first, then by invoice
    companies = {}
    all_companies = set()  # For filter dropdown

    for item in stock_items:
        company_name = item.order_item.order.company.company
        all_companies.add(company_name)
        invoice_number = item.invoice_number or "No Invoice"

        # Initialize company dict if not exists
        if company_name not in companies:
            companies[company_name] = {"invoices": {}, "total_items": 0}

        # Initialize invoice dict if not exists
        if invoice_number not in companies[company_name]["invoices"]:
            companies[company_name]["invoices"][invoice_number] = {
                "items": [],
                "item_ids": [],
            }

        # Add item to the appropriate company and invoice
        companies[company_name]["invoices"][invoice_number]["items"].append(item)
        companies[company_name]["invoices"][invoice_number]["item_ids"].append(
            str(item.id)
        )
        companies[company_name]["total_items"] += 1

    context = {
        "companies": companies,
        "all_companies": sorted(list(all_companies)),
        "page_title": "Ready for Delivery",
    }
    return render(request, "stock_management/ready_for_delivery.html", context)


@login_required
@ensure_csrf_cookie
def ready_to_pick(request):
    """View items ready to pick grouped by invoice and customer"""
    stock_items = (
        StockItem.objects.filter(status="invoiced", picked=False)
        .select_related(
            "order_item__order__company",
            "collection__supplier",
            "order_item__purchase_order",
        )
        .order_by(
            "order_item__order__company__company", "invoice_number", "invoice_date"
        )
    )

    # First group items by customer, then by invoice
    customers = {}
    picking_data = {}

    for item in stock_items:
        if not item.invoice_number:
            continue  # Skip items without invoice numbers

        # Get customer name
        customer_name = item.order_item.order.company.company

        # Initialize customer if needed
        if customer_name not in customers:
            customers[customer_name] = {}

        # Initialize invoice if needed
        if item.invoice_number not in customers[customer_name]:
            customers[customer_name][item.invoice_number] = []

        # Add item to the invoice group
        customers[customer_name][item.invoice_number].append(item)

        # Prepare data for JavaScript
        if item.invoice_number not in picking_data:
            picking_data[item.invoice_number] = []

        # Get PO number safely
        po_number = (
            item.order_item.purchase_order.po_number
            if item.order_item.purchase_order
            else "N/A"
        )

        picking_data[item.invoice_number].append(
            {
                "id": item.id,
                "description": item.order_item.description,
                "quantity": str(item.received_qty),
                "supplier": (
                    item.collection.supplier.suppliername
                    if item.collection and item.collection.supplier
                    else "N/A"
                ),
                "po_number": po_number,
                "customer": customer_name,
            }
        )

    context = {
        "customers": customers,
        "picking_data": json.dumps(picking_data),
        "page_title": "Ready to Pick",
    }
    return render(request, "stock_management/ready_to_pick.html", context)


@login_required
@require_POST
def mark_picked(request, item_id):
    """Mark an item as picked and move to delivery pick list"""
    try:
        item = StockItem.objects.get(id=item_id)
        # Store current status for debugging
        before_status = item.status

        # Toggle picked status
        item.picked = not item.picked

        if item.picked:
            # When marking as picked
            item.picked_by = request.user
            item.picked_date = timezone.now()
            item.status = "picked"  # Set status to 'picked' for delivery pick list
        else:
            # When unmarking
            item.picked_by = None
            item.picked_date = None
            item.status = "invoiced"  # Reset to previous status

        item.save()
        # Log status change for debugging
        debug_item_status(item, before_status, item.status)

        return JsonResponse(
            {
                "status": "success",
                "message": "Item marked as picked" if item.picked else "Item unmarked",
                "new_status": item.status,
            }
        )
    except StockItem.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Item not found"})
    except Exception as e:
        logger.error(f"Error in mark_picked: {str(e)}")
        return JsonResponse({"status": "error", "message": str(e)})


@login_required
@require_http_methods(["POST"])
def save_picking_progress(request):
    try:
        data = json.loads(request.body)
        invoice = data.get("invoice")
        items = data.get("items", [])
        logger.info(
            f"Saving picking progress - Invoice: {invoice}, Items: {len(items)}"
        )
        if not invoice:
            return JsonResponse(
                {"status": "error", "message": "Invoice number required"}
            )

        for item_data in items:
            item_id = item_data.get("id")
            picked = item_data.get("picked", False)

            try:
                item = StockItem.objects.get(id=item_id)
                if picked:
                    item.status = (
                        "picked"  # Changed from 'ready_for_delivery' to 'picked'
                    )
                    item.picked = True
                    item.picked_by = request.user
                    item.picked_date = timezone.now()
                item.save()
                # Log status change
                logger.info(f"Item {item_id} status updated to: {item.status}")

            except StockItem.DoesNotExist:
                logger.error(f"Item not found: {item_id}")
                continue

        return JsonResponse({"status": "success", "message": "Picking progress saved"})

    except Exception as e:
        logger.error(f"Error saving picking progress: {str(e)}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def generate_picking_slip_pdf(request, invoice_number):
    """Generate PDF picking slip with modern styling"""
    stock_items = StockItem.objects.filter(
        invoice_number=invoice_number
    ).select_related(
        "order_item__order__company",
        "collection__supplier",
        "order_item__purchase_order",
    )

    if not stock_items.exists():
        return HttpResponse("No items found", status=404)

    # Create the PDF document
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30 * mm,
        leftMargin=30 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    elements = []
    styles = getSampleStyleSheet()

    # Create a specific style for wrapped text in cells
    cell_style = ParagraphStyle(
        "CellText",
        parent=styles["Normal"],
        fontSize=10,
        textColor=HexColor("#000000"),
        wordWrap="CJK",  # Better word wrapping for all text types
        alignment=0,  # Left alignment
    )

    # Add company logo
    logo_path = "static/images/company-logo.png"  # Update with your logo path
    if os.path.exists(logo_path):
        img = Image(logo_path, width=60 * mm, height=30 * mm)
        elements.append(img)

    # Modern title style
    title_style = ParagraphStyle(
        "ModernTitle",
        parent=styles["Heading1"],
        fontSize=24,
        textColor=HexColor("#1a237e"),  # Dark blue
        spaceAfter=30,
        spaceBefore=30,
        alignment=1,  # Center alignment
    )
    elements.append(Paragraph("Picking Slip", title_style))

    # Modern header style
    header_style = ParagraphStyle(
        "ModernHeader",
        parent=styles["Normal"],
        fontSize=12,
        textColor=HexColor("#37474f"),  # Dark gray
        spaceBefore=6,
        spaceAfter=6,
    )

    # Add header information in a more structured way
    header_data = [
        [
            Paragraph(f"<b>Invoice #:</b> {invoice_number}", header_style),
            Paragraph(
                f'<b>Date:</b> {timezone.now().strftime("%Y-%m-%d")}', header_style
            ),
        ],
        [
            Paragraph(
                f"<b>Customer:</b> {stock_items[0].order_item.order.company.company}",
                header_style,
            ),
            Paragraph("", header_style),
        ],  # Empty cell for alignment
    ]
    header_table = Table(header_data, colWidths=[250, 250])
    header_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 20))

    # Modern table style
    data = [["Description", "Qty", "Supplier", "PO #", "Picked"]]
    for item in stock_items:
        # Wrap text in Paragraph objects to enable proper text wrapping
        data.append(
            [
                Paragraph(item.order_item.description, cell_style),
                str(item.received_qty),
                Paragraph(
                    (
                        item.collection.supplier.suppliername
                        if item.collection and item.collection.supplier
                        else "N/A"
                    ),
                    cell_style,
                ),
                Paragraph(
                    (
                        item.order_item.purchase_order.po_number
                        if item.order_item.purchase_order
                        else "N/A"
                    ),
                    cell_style,
                ),
                "☐",  # Modern checkbox symbol
            ]
        )

    # Create the table with proper column widths
    table = Table(data, colWidths=[220, 40, 100, 80, 50])

    # Apply styling
    table.setStyle(
        TableStyle(
            [
                # Header style
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    HexColor("#1a237e"),
                ),  # Dark blue header
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 12),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                # Table body
                ("GRID", (0, 0), (-1, -1), 1, HexColor("#e0e0e0")),  # Light gray grid
                ("ALIGN", (1, 1), (1, -1), "CENTER"),  # Center quantity column
                ("ALIGN", (4, 1), (4, -1), "CENTER"),  # Center checkbox column
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 10),
                ("TOPPADDING", (0, 1), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 12),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [HexColor("#f5f5f5"), HexColor("#ffffff")],
                ),  # Zebra striping
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),  # Vertical alignment
            ]
        )
    )
    elements.append(table)

    # Modern signature section
    elements.append(Spacer(1, 40))
    signature_style = ParagraphStyle(
        "SignatureStyle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=HexColor("#37474f"),
    )

    signature_data = [
        [Paragraph("Picked by:", signature_style), "_" * 40],
        [Paragraph("Date:", signature_style), "_" * 40],
        [Paragraph("Signature:", signature_style), "_" * 40],
    ]
    signature_table = Table(signature_data, colWidths=[100, 200])
    signature_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                ("ALIGN", (1, 0), (1, -1), "LEFT"),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    elements.append(signature_table)

    # Build PDF
    doc.build(elements)
    # FileResponse sets the Content-Disposition header
    buffer.seek(0)
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="picking_slip_{invoice_number}.pdf"'
    )
    response.write(buffer.getvalue())
    buffer.close()

    return response


@login_required
def office_stock(request):
    """View office stock items"""
    stock_items = (
        StockItem.objects.filter(status="office_stock")
        .select_related(
            "order_item__order", "order_item__purchase_order", "collection__supplier"
        )
        .order_by("external_invoice_date")
    )

    # Calculate total office stock value
    total_office_stock_value = sum(
        item.received_qty * item.order_item.cost_price
        for item in stock_items
        if item.order_item.cost_price is not None
    )

    context = {
        "stock_items": stock_items,
        "page_title": "Office Stock",
        "total_office_stock_value": total_office_stock_value,
    }
    return render(request, "stock_management/office_stock.html", context)


@login_required
@ensure_csrf_cookie
def delivery_pick_list(request):
    """View items that have been picked and are ready to be loaded, grouped by company then invoice"""
    stock_items = (
        StockItem.objects.filter(
            status="picked",  # Only show items with 'picked' status
            picked=True,  # Ensure they are actually marked as picked
        )
        .select_related(
            "order_item__order__company",
            "collection__supplier",
            "order_item__purchase_order",
        )
        .order_by(
            "order_item__order__company__company", "invoice_number", "invoice_date"
        )
    )

    # Add debug logging
    logger.info(f"Delivery Pick List - Found {stock_items.count()} items")

    # First group by company, then by invoice number
    companies = {}

    for item in stock_items:
        company_name = item.order_item.order.company.company
        invoice_number = item.invoice_number or "No Invoice"

        # Initialize company dict if not exists
        if company_name not in companies:
            companies[company_name] = {
                "invoices": {},
                "company_id": item.order_item.order.company.id,
            }

        # Initialize invoice dict if not exists
        if invoice_number not in companies[company_name]["invoices"]:
            companies[company_name]["invoices"][invoice_number] = []

        # Add item to the appropriate company and invoice
        companies[company_name]["invoices"][invoice_number].append(item)

    # Calculate total items
    total_items_count = 0
    for company_name, company_data in companies.items():
        for invoice_number, items in company_data["invoices"].items():
            total_items_count += len(items)

    context = {
        "companies": companies,
        "page_title": "Delivery Pick List",
        "total_items_count": total_items_count,
    }
    return render(request, "stock_management/delivery_pick_list.html", context)


@login_required
@require_POST
def mark_loaded(request, item_id):
    """Mark an item as loaded for delivery"""
    try:
        item = StockItem.objects.get(id=item_id)

        # Log the status change
        logger.info(f"Marking item {item_id} as loaded. Current status: {item.status}")

        # Update item status
        item.status = "ready_for_delivery"
        item.loaded_by = request.user
        item.loaded_date = timezone.now()
        item.save()
        logger.info(f"Item {item_id} marked as loaded. New status: {item.status}")

        return JsonResponse({"status": "success", "message": "Item marked as loaded"})
    except StockItem.DoesNotExist:
        logger.error(f"Item {item_id} not found")
        return JsonResponse(
            {"status": "error", "message": "Item not found"}, status=404
        )
    except Exception as e:
        logger.error(f"Error marking item {item_id} as loaded: {str(e)}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_POST
def mark_group_delivered(request):
    logger.info("Processing mark_group_delivered request")
    try:
        data = json.loads(request.body)
        item_ids = data.get("item_ids", [])
        delivery_date = data.get("delivery_date")
        invoice_number = data.get("invoice_number")
        logger.info(
            f"Received data: items={item_ids}, date={delivery_date}, invoice={invoice_number}"
        )
        if not all([item_ids, delivery_date, invoice_number]):
            raise ValidationError("Missing required fields")

        with transaction.atomic():
            # Convert item_ids to list if it's not already
            if isinstance(item_ids, str):
                item_ids = item_ids.split(",")

            items = StockItem.objects.filter(id__in=item_ids)

            if not items.exists():
                raise ValidationError("No items found with provided IDs")

            for item in items:
                logger.info(f"Processing item {item.id}: current status={item.status}")
                if item.invoice_number != invoice_number:
                    raise ValidationError(f"Invoice number mismatch for item {item.id}")

                item.status = "delivered"
                item.delivered_by = request.user
                item.delivered_date = delivery_date
                item.save()
                logger.info(f"Updated item {item.id} to delivered status")

        return JsonResponse(
            {
                "status": "success",
                "message": f"Successfully marked {len(item_ids)} items as delivered",
            }
        )
    except ValidationError as e:
        logger.error(f"Validation error: {str(e)}")
        return JsonResponse({"status": "error", "message": str(e)}, status=400)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in request body")
        return JsonResponse(
            {"status": "error", "message": "Invalid request format"}, status=400
        )
    except Exception as e:
        logger.error(f"Unexpected error in mark_group_delivered: {str(e)}")
        return JsonResponse(
            {"status": "error", "message": f"An error occurred: {str(e)}"}, status=500
        )


@login_required
@require_POST
def get_items_details(request):
    """Get details for selected stock items"""
    try:
        data = json.loads(request.body)
        item_ids = data.get("item_ids", [])

        if not item_ids:
            return JsonResponse({"items": []})

        # Get items with related order_item data
        stock_items = StockItem.objects.filter(id__in=item_ids).select_related(
            "order_item", "collection", "collection__supplier"
        )

        items = []
        for item in stock_items:
            # Get order number from related order item
            order_number = (
                getattr(item.order_item.order, "order_number", "Unknown")
                if hasattr(item.order_item, "order")
                else "Unknown"
            )

            items.append(
                {
                    "id": item.id,
                    "description": item.order_item.description,
                    "quantity": item.received_qty,
                    "order_number": order_number,
                    "supplier": (
                        item.collection.supplier.suppliername
                        if (item.collection and item.collection.supplier)
                        else "Unknown"
                    ),
                }
            )

        return JsonResponse({"items": items})

    except Exception as e:
        import logging

        logging.error(f"Error fetching item details: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def bulk_update_invoice(request):
    """Update invoice details for multiple items"""
    try:
        data = json.loads(request.body)
        item_ids = data.get("item_ids", [])
        invoice_number = data.get("invoice_number")
        invoice_date = data.get("invoice_date")

        if not all([item_ids, invoice_number, invoice_date]):
            return JsonResponse(
                {"status": "error", "message": "Missing required fields"}, status=400
            )

        success_count = 0
        error_count = 0
        error_messages = []

        with transaction.atomic():
            # Fixed this line - changed id__in(item_ids) to id__in=item_ids
            items = StockItem.objects.filter(id__in=item_ids)

            for item in items:
                try:
                    # Rest of your processing logic...
                    order_qty = item.order_item.quantity
                    already_invoiced = (
                        StockItem.objects.filter(
                            order_item=item.order_item, status="invoiced"
                        ).aggregate(total=models.Sum("received_qty"))["total"]
                        or 0
                    )

                    remaining_needed = order_qty - already_invoiced
                    if item.received_qty > remaining_needed and remaining_needed > 0:
                        # Create new stock item for excess
                        excess_qty = item.received_qty - remaining_needed
                        # Update original item with needed quantity
                        item.received_qty = remaining_needed
                        item.invoice_number = invoice_number
                        item.invoice_date = invoice_date
                        item.status = "invoiced"
                        item.save()

                        # Create new item for excess
                        StockItem.objects.create(
                            collection=item.collection,
                            order_item=item.order_item,
                            received_qty=excess_qty,
                            verified_quantity=excess_qty,
                            external_invoice_number=item.external_invoice_number,
                            external_invoice_date=item.external_invoice_date,
                            verified_by=item.verified_by,
                            status="office_stock",
                        )
                    else:
                        # Update original item as normal
                        item.invoice_number = invoice_number
                        item.invoice_date = invoice_date
                        item.status = "invoiced"
                        item.save()

                    success_count += 1

                except Exception as e:
                    error_count += 1
                    error_messages.append(f"Error on item {item.id}: {str(e)}")
                    import logging

                    logging.error(f"Error processing item {item.id}: {str(e)}")

        if error_count == 0:
            return JsonResponse(
                {
                    "status": "success",
                    "message": f"Successfully updated {success_count} items",
                }
            )
        elif success_count > 0:
            return JsonResponse(
                {
                    "status": "partial",
                    "message": f"Updated {success_count} items with {error_count} errors",
                    "success_count": success_count,
                    "error_count": error_count,
                    "errors": error_messages[:5],
                }
            )
        else:
            return JsonResponse(
                {
                    "status": "error",
                    "message": f"Failed to update any items: {error_messages[0]}",
                    "errors": error_messages[:5],
                },
                status=500,
            )

    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)
    except Exception as e:
        import logging

        logging.error(f"Error in bulk invoice update: {str(e)}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_POST
def bulk_verify_stock(request):
    try:
        data = json.loads(request.body)

        items = data.get("items", [])
        external_invoice_number = data.get("external_invoice_number")
        external_invoice_date = data.get("external_invoice_date")
        notes = data.get("notes", "")

        success_count = 0
        error_count = 0
        error_items = []

        with transaction.atomic():
            for item in items:
                collection_id = item.get("id")
                verified_qty = float(item.get("qty"))

                try:
                    collection = Collection.objects.get(id=collection_id)

                    # Create a stock item from the collection
                    stock_item = StockItem.objects.create(
                        collection=collection,
                        order_item=collection.order_item,
                        received_qty=verified_qty,
                        verified_quantity=verified_qty,
                        external_invoice_number=external_invoice_number,
                        external_invoice_date=external_invoice_date,
                        notes=notes,
                        verified_by=request.user,
                        status="verified",
                    )

                    # Update collection status
                    collection.status = "in_stock"
                    collection.notes = (
                        (collection.notes or "")
                        + f"\nVerified by {request.user} on {timezone.now().strftime('%Y-%m-%d %H:%M')}"
                    )
                    collection.save()

                    success_count += 1

                except Exception as e:
                    error_count += 1
                    error_items.append({"id": collection_id, "error": str(e)})

        # Determine overall status
        if error_count == 0:
            status = "success"
        elif success_count > 0:
            status = "partial"
        else:
            status = "error"

        return JsonResponse(
            {
                "status": status,
                "success_count": success_count,
                "error_count": error_count,
                "error_items": error_items,
            }
        )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=400)


def some_view(request):
    new_stock_items_count = StockItem.objects.filter(seen=False).count()
    return render(
        request,
        "your_template.html",
        {
            "new_stock_items_count": new_stock_items_count,
            # other context variables
        },
    )


@login_required
def admin_dashboard(request):
    """Admin dashboard for stock management"""
    # Check if user is admin
    if (
        not request.user.is_superuser
        and not request.user.groups.filter(name="ADMIN").exists()
    ):
        messages.error(request, "You don't have permission to access this page.")
        return redirect("dashboard:rep_dashboard")

    # Get stock statistics
    # ... stock statistics code ...

    context = {
        "title": "Stock Administration Dashboard",
        "segment": "stock_admin",
    }

    return render(request, "stock_management/admin/dashboard.html", context)


@login_required
def inventory_audit(request):
    """Inventory audit tool"""
    # Check if user is admin
    if (
        not request.user.is_superuser
        and not request.user.groups.filter(name="ADMIN").exists()
    ):
        messages.error(request, "You don't have permission to access this page.")
        return redirect("dashboard:rep_dashboard")

    context = {
        "title": "Inventory Audit",
        "segment": "stock_admin",
    }

    return render(request, "stock_management/admin/inventory_audit.html", context)


@login_required
def stock_adjustments(request):
    """Stock adjustment interface"""
    # Check if user is admin
    if (
        not request.user.is_superuser
        and not request.user.groups.filter(name="ADMIN").exists()
    ):
        messages.error(request, "You don't have permission to access this page.")
        return redirect("dashboard:rep_dashboard")

    context = {
        "title": "Stock Adjustments",
        "segment": "stock_admin",
    }

    return render(request, "stock_management/admin/stock_adjustments.html", context)


@login_required
def stock_reports(request):
    """Stock reporting interface"""
    # Check if user is admin
    if (
        not request.user.is_superuser
        and not request.user.groups.filter(name="ADMIN").exists()
    ):
        messages.error(request, "You don't have permission to access this page.")
        return redirect("dashboard:rep_dashboard")

    context = {
        "title": "Stock Reports",
        "segment": "stock_admin",
    }

    return render(request, "stock_management/admin/stock_reports.html", context)


@login_required
def create_from_stock(request):
    if request.method == "POST":
        item_ids = request.POST.get("item_ids", "").split(",")
        company_id = request.POST.get("company_id")

        # If no items selected, show error
        if not item_ids:
            messages.error(request, "Please select items to create a delivery note")
            return redirect("stock_management:stock_list")

        try:
            # Try to auto-detect company if not provided
            if not company_id and item_ids:
                first_item = get_object_or_404(StockItem, pk=item_ids[0])
                # Try to get company from the order
                if (
                    first_item.order_item
                    and first_item.order_item.order
                    and first_item.order_item.order.company
                ):
                    company = first_item.order_item.order.company
                else:
                    # If we can't determine company and one wasn't provided, show error
                    messages.error(
                        request,
                        "Could not determine company. Please select one manually.",
                    )
                    return redirect("stock_management:stock_list")
            else:
                # Use the provided company ID
                company = get_object_or_404(Company, pk=company_id)

            # Generate delivery number
            delivery_number = generate_delivery_number()

            # Create delivery note
            delivery = DeliveryNote.objects.create(
                delivery_number=delivery_number,
                company=company,
                created_by=request.user,
                status="draft",
                contact_person=request.POST.get("contact_person", ""),
                contact_email=request.POST.get("contact_email", ""),
                contact_phone=request.POST.get("contact_phone", ""),
                notes=request.POST.get("notes", ""),
            )

            # Add items to the delivery note
            for item_id in item_ids:
                stock_item = get_object_or_404(StockItem, pk=item_id)

                # Create delivery item
                DeliveryItem.objects.create(
                    delivery_note=delivery,
                    stock_item=stock_item,
                    description=stock_item.order_item.description,
                    quantity=stock_item.received_qty,
                    price=stock_item.order_item.selling_price,
                    notes="Transferred from stock",
                )

                # Mark the stock item as delivered
                stock_item.status = "delivered"
                stock_item.delivered_in = delivery
                stock_item.save()

            # Generate PDF
            generate_delivery_pdf(request, delivery.pk)

            messages.success(
                request, f"Delivery note {delivery_number} created successfully"
            )
            return redirect("delivery_notes:detail", pk=delivery.pk)

        except Exception as e:
            import traceback

            traceback.print_exc()
            messages.error(request, f"Error creating delivery note: {str(e)}")
            return redirect("stock_management:stock_list")

    return redirect("stock_management:stock_list")


# Add this function to generate a delivery number (was missing)
def generate_delivery_number():
    """Generate a unique delivery number"""
    from django.utils.crypto import get_random_string

    prefix = "DN"
    date_str = timezone.now().strftime("%y%m%d")
    random_suffix = get_random_string(length=3, allowed_chars="0123456789")
    return f"{prefix}{date_str}{random_suffix}"


@login_required
def create_delivery_note_from_stock(request, item_id):
    """Create a delivery note directly from a stock item"""
    try:
        # Get the stock item
        stock_item = get_object_or_404(StockItem, pk=item_id)

        # Import the necessary models
        from delivery_notes.models import DeliveryNote, DeliveryItem
        from django.utils.crypto import get_random_string

        # Get the company directly from the order
        if not stock_item.order_item or not stock_item.order_item.order:
            messages.error(request, "Could not determine company from this item")
            return redirect("stock_management:stock_list")

        # Get company directly from the stock item's order
        company = stock_item.order_item.order.company

        # Generate delivery number
        prefix = "DN"
        date_str = timezone.now().strftime("%y%m%d")
        random_suffix = get_random_string(length=3, allowed_chars="0123456789")
        delivery_number = f"{prefix}{date_str}{random_suffix}"

        # Create the delivery note
        delivery = DeliveryNote.objects.create(
            delivery_number=delivery_number,
            company=company,  # Use company from the order
            created_by=request.user,
            status="draft",
            delivery_date=timezone.now().date(),
        )

        # --- Calculate Cost Price and Markup ---
        cost_price = stock_item.order_item.cost_price
        selling_price = stock_item.order_item.selling_price or Decimal(
            "0.00"
        )  # Default to 0 if None
        markup = None
        if cost_price and cost_price > 0 and selling_price:
            try:
                markup = ((selling_price - cost_price) / cost_price) * 100
            except (InvalidOperation, TypeError):
                markup = None  # Handle potential errors during calculation
        # --- End Calculation ---

        # Create delivery item WITH cost_price and markup
        DeliveryItem.objects.create(
            delivery_note=delivery,
            description=stock_item.order_item.description,
            quantity=stock_item.received_qty,
            price=selling_price,  # Use the fetched selling_price
            cost_price=cost_price,  # Add cost_price
            markup=markup,  # Add calculated markup
            notes="",  # Empty string instead of including item number
        )

        # Mark the stock item as delivered
        stock_item.status = "delivered"
        stock_item.save()

        # Generate PDF
        from delivery_notes.views import generate_delivery_pdf

        generate_delivery_pdf(request, delivery.pk)

        # Success message
        messages.success(
            request, f"Delivery note {delivery_number} created successfully"
        )
        return redirect("delivery_notes:detail", pk=delivery.pk)

    except Exception as e:
        import traceback

        traceback.print_exc()
        messages.error(request, f"Error creating delivery note: {str(e)}")
        return redirect("stock_management:stock_list")


@login_required
def create_bulk_delivery_note(request):
    """Create a delivery note from multiple stock items"""
    if request.method != "POST":
        return redirect("stock_management:stock_list")

    item_ids = request.POST.get("item_ids", "").split(",")

    # Add logging to debug
    print(f"Received item_ids: {item_ids}")

    if not item_ids or item_ids == [""]:
        messages.error(request, "No items selected")
        return redirect("stock_management:stock_list")

    try:
        # Import the necessary models
        from delivery_notes.models import DeliveryNote, DeliveryItem
        from django.utils.crypto import get_random_string

        # Get first stock item to determine company
        first_item = get_object_or_404(StockItem, pk=item_ids[0])

        print(
            f"First item: {first_item.id}, Order: {first_item.order_item.order if first_item.order_item else 'None'}"
        )

        # Get company directly from the first stock item's order
        if not first_item.order_item or not first_item.order_item.order:
            messages.error(request, "Could not determine company from selected items")
            return redirect("stock_management:stock_list")

        company = first_item.order_item.order.company

        # Generate delivery number
        prefix = "DN"
        date_str = timezone.now().strftime("%y%m%d")
        random_suffix = get_random_string(length=3, allowed_chars="0123456789")
        delivery_number = f"{prefix}{date_str}{random_suffix}"

        # Create the delivery note
        delivery = DeliveryNote.objects.create(
            delivery_number=delivery_number,
            company=company,
            created_by=request.user,
            status="draft",
            delivery_date=timezone.now().date(),
        )

        # Add all selected items to the delivery note
        for item_id in item_ids:
            stock_item = get_object_or_404(StockItem, pk=item_id)

            # --- Calculate Cost Price and Markup ---
            cost_price = stock_item.order_item.cost_price
            selling_price = stock_item.order_item.selling_price or Decimal(
                "0.00"
            )  # Default to 0 if None
            markup = None
            if cost_price and cost_price > 0 and selling_price:
                try:
                    markup = ((selling_price - cost_price) / cost_price) * 100
                except (InvalidOperation, TypeError):
                    markup = None  # Handle potential errors during calculation
            # --- End Calculation ---

            # Create delivery item WITH cost_price and markup
            DeliveryItem.objects.create(
                delivery_note=delivery,
                description=stock_item.order_item.description,
                quantity=stock_item.received_qty,
                price=selling_price,  # Use the fetched selling_price
                cost_price=cost_price,  # Add cost_price
                markup=markup,  # Add calculated markup
                notes="",  # Empty string instead of including item number
            )

            # Mark the stock item as delivered
            stock_item.status = "delivered"
            stock_item.save()

        # Generate PDF
        from delivery_notes.views import generate_delivery_pdf

        generate_delivery_pdf(request, delivery.pk)

        # Success message
        messages.success(
            request,
            f"Bulk delivery note {delivery_number} with {len(item_ids)} items created successfully",
        )
        return redirect("delivery_notes:detail", pk=delivery.pk)

    except Exception as e:
        import traceback

        traceback.print_exc()
        messages.error(request, f"Error creating bulk delivery note: {str(e)}")
        return redirect("stock_management:stock_list")
