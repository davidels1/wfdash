from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db.models import Q
from .models import InternalStockItem, SupplierPriceList, PriceListItem
from wfdash.models import Suppliers  # Add this import
from .forms import (
    InternalStockItemForm,
    SupplierPriceListForm,
    PriceListItemForm,
    BulkItemUploadForm,
)
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import csv
from io import TextIOWrapper
from decimal import Decimal
import datetime  # Make sure this is imported for the form

# Create your views here.


@login_required
def search_internal_stock(request):
    query = request.GET.get("term", "")
    items = []
    if len(query) >= 2:  # Only search if query is 2+ chars
        results = InternalStockItem.objects.filter(
            Q(part_number__icontains=query)
            | Q(description__icontains=query)
            | Q(brand__icontains=query)
        )[:10]  # Limit results

        for item in results:
            items.append(
                {
                    "id": item.id,
                    "label": f"{item.part_number} - {item.description[:60]} ({item.brand})",
                    "value": item.description,
                    "part_number": item.part_number,
                    "brand": item.brand,
                    "description": item.description,
                    "supplier_id": item.supplier.id if item.supplier else "",
                    "supplier_name": item.supplier.suppliername
                    if item.supplier
                    else "",  # Add supplier name
                    "cost_price": str(item.cost_price) if item.cost_price else "",
                    "markup": str(item.markup) if item.markup else "",
                    "selling_price": str(item.selling_price)
                    if item.selling_price
                    else "",
                    "notes": item.notes,  # Include notes in the response
                }
            )
    return JsonResponse(items, safe=False)


@login_required
def internal_stock_list(request):
    """Displays a list of all internal stock items."""
    search_query = request.GET.get("search", "")
    if search_query:
        items = InternalStockItem.objects.filter(
            Q(part_number__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(brand__icontains=search_query)
        ).order_by("part_number")
    else:
        items = InternalStockItem.objects.all().order_by("part_number")

    context = {
        "items": items,
        "search_query": search_query,
    }
    return render(request, "internal_stock/internal_stock_list.html", context)


@login_required
def create_internal_stock_item(request):
    """Handles creation of a new internal stock item."""
    if request.method == "POST":
        form = InternalStockItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f"Successfully added item: {item.part_number}")
            return redirect(
                "internal_stock:list"
            )  # Redirect to the list view after saving
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = InternalStockItemForm()

    context = {
        "form": form,
        "form_title": "Add New Internal Stock Item",  # Title for the template
    }
    return render(request, "internal_stock/internal_stock_form.html", context)


@login_required
def edit_internal_stock_item(request, item_id):
    """Edit an existing internal stock item"""
    item = get_object_or_404(InternalStockItem, pk=item_id)

    if request.method == "POST":
        form = InternalStockItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"Item '{item.part_number}' updated successfully."
            )
            return redirect("internal_stock:list")
    else:
        form = InternalStockItemForm(instance=item)

    context = {
        "form": form,
        "item": item,
        "title": "Edit Stock Item",
        "is_edit": True,
    }
    return render(request, "internal_stock/internal_stock_form.html", context)


@login_required
def delete_internal_stock_item(request, item_id):
    """Delete an internal stock item (admin only)"""
    # Check if user is admin/staff
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, "You don't have permission to delete stock items.")
        return redirect("internal_stock:list")

    item = get_object_or_404(InternalStockItem, pk=item_id)
    part_number = item.part_number  # Save for message

    # Delete the item
    item.delete()
    messages.success(request, f"Item '{part_number}' has been deleted.")
    return redirect("internal_stock:list")


@login_required
def price_list_index(request):
    """View to list all supplier price lists"""
    price_lists = SupplierPriceList.objects.all().select_related("supplier")

    # Filter by supplier if specified
    supplier_id = request.GET.get("supplier")
    if supplier_id:
        try:
            price_lists = price_lists.filter(supplier_id=int(supplier_id))
        except (ValueError, TypeError):
            pass

    # Get list of suppliers for filter dropdown
    suppliers = Suppliers.objects.order_by("suppliername")

    context = {
        "price_lists": price_lists,
        "suppliers": suppliers,
        "selected_supplier": supplier_id,
    }
    return render(request, "internal_stock/price_list_index.html", context)


@login_required
def price_list_detail(request, pk):
    """View a specific price list and its items"""
    price_list = get_object_or_404(SupplierPriceList, pk=pk)
    items = price_list.items.all()

    # Handle sorting
    sort = request.GET.get("sort", "description")
    if sort == "price_low":
        items = items.order_by("cost_price")
    elif sort == "price_high":
        items = items.order_by("-cost_price")
    elif sort == "markup_high":
        items = items.order_by("-markup")
    else:
        items = items.order_by("description")

    context = {
        "price_list": price_list,
        "items": items,
        "sort": sort,
    }
    return render(request, "internal_stock/price_list_detail.html", context)


@login_required
def create_price_list(request):
    """Create a new supplier price list"""
    if request.method == "POST":
        form = SupplierPriceListForm(request.POST)
        if form.is_valid():
            price_list = form.save()
            messages.success(
                request, f"Price list '{price_list.name}' created successfully."
            )
            return redirect("internal_stock:price_list_detail", pk=price_list.pk)
    else:
        form = SupplierPriceListForm()

    context = {
        "form": form,
        "title": "Create New Price List",
    }
    return render(request, "internal_stock/price_list_form.html", context)


@login_required
def edit_price_list(request, pk):
    """Edit an existing supplier price list"""
    price_list = get_object_or_404(SupplierPriceList, pk=pk)

    if request.method == "POST":
        form = SupplierPriceListForm(request.POST, instance=price_list)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"Price list '{price_list.name}' updated successfully."
            )
            return redirect("internal_stock:price_list_detail", pk=price_list.pk)
    else:
        form = SupplierPriceListForm(instance=price_list)

    context = {
        "form": form,
        "price_list": price_list,
        "title": f"Edit Price List: {price_list.name}",
    }
    return render(request, "internal_stock/price_list_form.html", context)


@login_required
def add_price_list_item(request, price_list_id):
    """Add a new item to a price list"""
    price_list = get_object_or_404(SupplierPriceList, pk=price_list_id)

    if request.method == "POST":
        form = PriceListItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.price_list = price_list
            item.save()
            messages.success(request, f"Item '{item.description}' added to price list.")

            # Check if user wants to add another item
            if "add_another" in request.POST:
                return redirect(
                    "internal_stock:add_price_list_item", price_list_id=price_list.pk
                )
            return redirect("internal_stock:price_list_detail", pk=price_list.pk)
    else:
        # Pre-fill with default markup from price list
        form = PriceListItemForm(initial={"markup": price_list.default_markup})

    context = {
        "form": form,
        "price_list": price_list,
        "title": f"Add Item to {price_list.name}",
    }
    return render(request, "internal_stock/price_list_item_form.html", context)


@login_required
def edit_price_list_item(request, item_id):
    """Edit an existing price list item"""
    item = get_object_or_404(PriceListItem, pk=item_id)
    price_list = item.price_list

    if request.method == "POST":
        form = PriceListItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(
                request, f"Item '{item.description}' updated successfully."
            )
            return redirect("internal_stock:price_list_detail", pk=price_list.pk)
    else:
        form = PriceListItemForm(instance=item)

    context = {
        "form": form,
        "item": item,
        "price_list": price_list,
        "title": f"Edit Item: {item.description}",
    }
    return render(request, "internal_stock/price_list_item_form.html", context)


@login_required
def delete_price_list_item(request, item_id):
    """Delete a price list item"""
    item = get_object_or_404(PriceListItem, pk=item_id)
    price_list = item.price_list

    if request.method == "POST":
        item.delete()
        messages.success(request, f"Item '{item.description}' deleted successfully.")
        return redirect("internal_stock:price_list_detail", pk=price_list.pk)

    context = {
        "item": item,
        "price_list": price_list,
        "title": f"Delete Item: {item.description}",
    }
    return render(request, "internal_stock/confirm_delete.html", context)


@login_required
def bulk_upload_items(request, price_list_id):
    """Bulk upload items to a price list from CSV"""
    price_list = get_object_or_404(SupplierPriceList, pk=price_list_id)

    if request.method == "POST":
        form = BulkItemUploadForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = TextIOWrapper(request.FILES["file"].file, encoding="utf-8-sig")
            reader = csv.DictReader(csv_file)

            success_count = 0
            error_count = 0
            errors = []

            for row in reader:
                try:
                    # Create item from CSV row
                    item = PriceListItem(
                        price_list=price_list,
                        part_number=row.get("part_number", ""),
                        description=row.get("description", ""),
                        brand=row.get("brand", ""),
                        cost_price=Decimal(row.get("cost_price", 0)),
                        notes=row.get("notes", ""),
                    )

                    # Set markup if provided, otherwise use price list default
                    if "markup" in row and row["markup"]:
                        item.markup = Decimal(row["markup"])
                    else:
                        item.markup = price_list.default_markup

                    # Set selling price if provided
                    if "selling_price" in row and row["selling_price"]:
                        item.selling_price = Decimal(row["selling_price"])

                    item.save()
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    errors.append(f"Error in row {reader.line_num}: {str(e)}")

            if success_count:
                messages.success(
                    request, f"Successfully imported {success_count} items."
                )
            if error_count:
                messages.error(request, f"Failed to import {error_count} items.")
                for error in errors[:10]:  # Show first 10 errors
                    messages.warning(request, error)

            return redirect("internal_stock:price_list_detail", pk=price_list.pk)
    else:
        form = BulkItemUploadForm()

    context = {
        "form": form,
        "price_list": price_list,
        "title": f"Bulk Upload Items to {price_list.name}",
    }
    return render(request, "internal_stock/bulk_upload_form.html", context)
