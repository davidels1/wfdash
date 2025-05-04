from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from django.core.cache import cache

from .forms import CustomersForm
from .models import Customers

from .forms import SuppliersForm
from .models import Suppliers

from .forms import CompanyForm
from .models import Company

from quotes.models import QuoteRequest
from orders.models import Order, OrderItem
from driver_list.models import Collection
from stock_management.models import StockItem


# ====================================================================================
# ================================        CUSTOMERS        ===========================
# ====================================================================================


@ensure_csrf_cookie
@login_required
def customers(request):
    if request.method == "POST":
        form = CustomersForm(request.POST)
        if form.is_valid():
            customer = form.save()

            # Check if it's an AJAX request
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": True,
                        "customer_name": customer.customer,
                        "customer_id": customer.id,
                    }
                )

            messages.success(
                request, f"Customer {customer.customer} added successfully!"
            )
            return redirect("wfdash:customers")  # Stay on same page
        else:
            # Return detailed error messages for AJAX
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                # Get all error messages
                errors = {
                    field: [str(e) for e in form.errors[field]] for field in form.errors
                }
                # Check for duplicate customer errors specifically
                customer_errors = errors.get("customer", [])
                if any(
                    "Duplicate customer found" in error for error in customer_errors
                ):
                    return JsonResponse(
                        {
                            "success": False,
                            "duplicate": True,
                            "errors": errors,
                            "message": customer_errors[
                                0
                            ],  # Return the first duplicate error message
                        },
                        status=400,
                    )
                return JsonResponse({"success": False, "errors": errors}, status=400)
    else:
        form = CustomersForm()

    customers_list = Customers.objects.all()
    context = {"segment": "customers", "form": form, "customers": customers_list}
    return render(request, "wfdash/customers.html", context)


@login_required
def customers_list(request):
    # Get query parameters
    search_query = request.GET.get("search", "")
    company_filter = request.GET.get("company", "")

    # Base queryset
    customers_queryset = Customers.objects.all()

    # Apply search filter if provided
    if search_query:
        customers_queryset = customers_queryset.filter(
            Q(customer__icontains=search_query)
            | Q(company__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(number__icontains=search_query)  # Changed from phone to number
        )

    # Apply company filter if provided
    if company_filter:
        customers_queryset = customers_queryset.filter(company__iexact=company_filter)

    # Order by date added (newest first)
    customers_queryset = customers_queryset.order_by("-dateadded")

    # Get unique companies for the filter dropdown
    unique_companies = (
        Customers.objects.values_list("company", flat=True)
        .distinct()
        .order_by("company")
    )

    # Pagination - 30 customers per page
    paginator = Paginator(customers_queryset, 30)  # Show 30 customers per page
    page = request.GET.get("page")

    try:
        customers = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page
        customers = paginator.page(1)
    except EmptyPage:
        # If page is out of range, deliver last page of results
        customers = paginator.page(paginator.num_pages)

    context = {
        "segment": "customers_list",
        "customers": customers,
        "search_query": search_query,
        "company_filter": company_filter,
        "unique_companies": unique_companies,
    }
    return render(request, "wfdash/customers_list.html", context)


@login_required
def customer_edit(request, pk):
    customer = get_object_or_404(Customers, pk=pk)
    if request.method == "POST":
        form = CustomersForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()

            # Check if it's an AJAX request
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {"success": True, "message": "Customer updated successfully!"}
                )

            messages.success(request, "Customer updated successfully!")
            return redirect("wfdash:customers_list")
        else:
            # Handle form errors for AJAX
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": False,
                        "errors": {
                            field: errors for field, errors in form.errors.items()
                        },
                        "message": "Please correct the errors below.",
                    },
                    status=400,
                )
    else:
        form = CustomersForm(instance=customer)

    return render(request, "wfdash/customers_edit.html", {"form": form})


@login_required
@require_http_methods(["POST"])
def customer_delete(request, pk):
    try:
        customer = get_object_or_404(Customers, pk=pk)
        customer_name = customer.customer  # Store name before deletion
        customer.delete()
        return JsonResponse(
            {
                "status": "success",
                "message": f"Customer {customer_name} deleted successfully!",
            }
        )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})


@login_required
def customer_list(request):
    customers = Customers.objects.all().order_by("company")
    return render(
        request,
        "wfdash/customer_list.html",
        {"customers": customers, "segment": "customers"},
    )


@login_required
def recent_customers(request):
    """Return the most recent 10 customers added"""
    recent = Customers.objects.all().order_by("-id")[:10]

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        html = render_to_string(
            "wfdash/includes/recent_customers.html", {"recent_customers": recent}
        )
        return JsonResponse({"html": html})

    return render(
        request, "wfdash/includes/recent_customers.html", {"recent_customers": recent}
    )


# ====================================================================================
# ================================        SUPPLIERS        ===========================
# ====================================================================================


@login_required
def suppliers(request):
    """
    Handles the add supplier form and adds a new supplier to the database
    """
    if request.method == "POST":
        # Create a form instance and populate it with the request data
        form = SuppliersForm(request.POST)

        # Check the form is valid
        if form.is_valid():
            # Save the supplier to the database
            supplier = form.save()

            # Check if it's an AJAX request
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": True,
                        "suppliername": supplier.suppliername,
                        "supplier_id": supplier.id,
                    }
                )

            messages.success(
                request, f"Supplier {supplier.suppliername} added successfully!"
            )
            return redirect("wfdash:suppliers_list")
        else:
            # Handle form errors for AJAX
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": False,
                        "errors": {
                            field: errors for field, errors in form.errors.items()
                        },
                    },
                    status=400,
                )
    else:
        # If it's a GET request, create an empty form instance
        form = SuppliersForm()

    context = {
        # Render the page with the form
        "segment": "suppliers",
        "form": form,
    }
    return render(request, "wfdash/suppliers.html", context)


@login_required
def suppliers_list(request):
    """
    Displays a paginated, searchable list of suppliers
    """
    # Get search parameters
    search_query = request.GET.get("search", "")

    # Base queryset
    suppliers_queryset = Suppliers.objects.all()

    # Apply search filter if provided
    if search_query:
        suppliers_queryset = suppliers_queryset.filter(
            Q(suppliername__icontains=search_query)
            | Q(supplieraddress__icontains=search_query)
            | Q(suppliernumber__icontains=search_query)  # Use suppliernumber instead
            | Q(supply_tags__icontains=search_query)
        )

    # Order suppliers by name
    suppliers_queryset = suppliers_queryset.order_by("suppliername")

    # Pagination - 30 suppliers per page
    paginator = Paginator(suppliers_queryset, 30)
    page = request.GET.get("page")

    try:
        suppliers = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page
        suppliers = paginator.page(1)
    except EmptyPage:
        # If page is out of range, deliver last page of results
        suppliers = paginator.page(paginator.num_pages)

    context = {
        "segment": "suppliers_list",
        "suppliers": suppliers,
        "search_query": search_query,
    }
    return render(request, "wfdash/suppliers_list.html", context)


@login_required
def supplier_edit(request, pk):
    """
    Handles editing of existing suppliers
    """
    supplier = get_object_or_404(Suppliers, pk=pk)
    if request.method == "POST":
        form = SuppliersForm(request.POST, instance=supplier)
        if form.is_valid():
            supplier = form.save()

            # Check if it's an AJAX request
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {"success": True, "message": "Supplier updated successfully!"}
                )

            messages.success(request, "Supplier updated successfully!")
            return redirect("wfdash:suppliers_list")
        else:
            # Handle form errors for AJAX
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": False,
                        "errors": {
                            field: errors for field, errors in form.errors.items()
                        },
                        "message": "Please correct the errors below.",
                    },
                    status=400,
                )
    else:
        form = SuppliersForm(instance=supplier)

    return render(
        request, "wfdash/suppliers_edit.html", {"form": form, "supplier": supplier}
    )


@login_required
@require_http_methods(["POST"])
def supplier_delete(request, pk):
    """
    Handles deletion of suppliers via AJAX
    """
    try:
        supplier = get_object_or_404(Suppliers, pk=pk)
        supplier_name = supplier.suppliername  # Store name before deletion
        supplier.delete()
        return JsonResponse(
            {
                "status": "success",
                "message": f"Supplier {supplier_name} deleted successfully!",
            }
        )
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})


@login_required
def supplier_search(request):
    """API endpoint for searching suppliers"""
    search = request.GET.get("search", "")

    try:
        # Add logging
        print(f"Supplier search for: '{search}'")

        if not search:
            # Return empty results for empty search
            print("Empty search term, returning empty results")
            return JsonResponse([], safe=False)

        # Get suppliers that match the search term
        suppliers = Suppliers.objects.filter(Q(suppliername__icontains=search)).values(
            "id", "suppliername"
        )[:10]

        # Log what we found
        print(f"Found {suppliers.count()} suppliers matching '{search}'")

        # Format as list of dicts for JSON response
        results = [{"id": s["id"], "text": s["suppliername"]} for s in suppliers]
        print(f"Returning results: {results}")
        return JsonResponse(results, safe=False)
    except Exception as e:
        print(f"Error in supplier search: {str(e)}")
        import traceback

        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


# ====================================================================================
# ================================        COMPANY          ===========================
# ====================================================================================


@login_required
def company(request):
    if request.method == "POST":
        form = CompanyForm(request.POST)
        if form.is_valid():
            company = form.save()

            # Check if it's an AJAX request
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": True,
                        "company": company.company,
                        "redirect_to_list": True,
                    }
                )

            messages.success(request, f"Company {company.company} added successfully!")
            return redirect("wfdash:company_list")
        else:
            # Handle form errors for AJAX
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": False,
                        "errors": {
                            field: errors for field, errors in form.errors.items()
                        },
                    },
                    status=400,
                )
    else:
        form = CompanyForm()

    return render(request, "wfdash/company.html", {"form": form})


@login_required
def company_list(request):
    search_query = request.GET.get("search", "")

    # Base queryset
    companies_queryset = Company.objects.all()

    # Apply search filter if provided
    if search_query:
        companies_queryset = companies_queryset.filter(
            Q(company__icontains=search_query) | Q(address__icontains=search_query)
        )

    # Order by company name
    companies_queryset = companies_queryset.order_by("company")

    # Pagination - 30 companies per page
    paginator = Paginator(companies_queryset, 30)  # Show 30 companies per page
    page = request.GET.get("page")

    try:
        companies = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page
        companies = paginator.page(1)
    except EmptyPage:
        # If page is out of range, deliver last page of results
        companies = paginator.page(paginator.num_pages)

    context = {
        "segment": "company_list",
        "companies": companies,
        "search_query": search_query,
    }

    return render(request, "wfdash/company_list.html", context)


@login_required
def company_edit(request, pk):
    company = get_object_or_404(Company, pk=pk)

    if request.method == "POST":
        form = CompanyForm(request.POST, instance=company)
        if form.is_valid():
            form.save()

            # Check if it's an AJAX request
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"success": True})

            messages.success(request, "Company updated successfully!")
            return redirect("wfdash:company_list")
        else:
            # Handle form errors for AJAX
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": False,
                        "errors": {
                            field: errors for field, errors in form.errors.items()
                        },
                    },
                    status=400,
                )
    else:
        form = CompanyForm(instance=company)

    return render(request, "wfdash/company_edit.html", {"form": form})


@login_required
@require_http_methods(["POST"])
def company_delete(request, pk):
    try:
        company = get_object_or_404(Company, pk=pk)
        company.delete()
        return JsonResponse({"status": "success"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})


@login_required
def company_search(request):
    """API endpoint for searching companies via Select2"""
    # Accept both query parameter formats (q from Select2, search from other interfaces)
    query = request.GET.get("q", "") or request.GET.get("search", "")
    query = query.strip()

    # Return empty results for very short queries to avoid heavy DB load
    if not query or len(query) < 2:
        return JsonResponse({"results": []})

    # Search in both company name and address fields
    companies = Company.objects.filter(
        Q(
            company__icontains=query
        )  # Using actual field name "company" instead of "name"
        | Q(address__icontains=query)  # Using "address" instead of "code"
    ).values("id", "company", "address")[:20]

    # Format results in Select2 compatible format
    results = [
        {
            "id": c["id"],
            "text": c["company"],  # Use "company" as primary text
            "address": c["address"],  # Include address as additional data
        }
        for c in companies
    ]

    # Return in format Select2 expects with 'results' key or direct array
    if "q" in request.GET:
        return JsonResponse({"results": results})
    else:
        return JsonResponse(results, safe=False)


@login_required
def get_company_address(request, company_id):
    """API endpoint to get a company's address by ID"""
    try:
        company = Company.objects.get(id=company_id)
        return JsonResponse({"success": True, "address": company.address})
    except Company.DoesNotExist:
        return JsonResponse(
            {"success": False, "error": "Company not found"}, status=404
        )


@login_required
def universal_search(request):
    query = request.GET.get("q", "")
    results = {"quotes": [], "orders": [], "collections": [], "stock": []}

    if query:
        # Search Quotes
        quotes = QuoteRequest.objects.filter(
            Q(quote_number__icontains=query)
            | Q(customer__company__icontains=query)
            | Q(items__description__icontains=query)
            | Q(items__selling_price__icontains=query)
        ).distinct()[:5]

        # Search Orders
        orders = Order.objects.filter(
            Q(order_number__icontains=query)
            | Q(company__company__icontains=query)
            | Q(items__description__icontains=query)
        ).distinct()[:5]

        # Search Collections
        collections = Collection.objects.filter(
            Q(order_item__order__order_number__icontains=query)
            | Q(supplier__suppliername__icontains=query)
            | Q(order_item__description__icontains=query)
        ).distinct()[:5]

        # Search Stock
        stock = StockItem.objects.filter(
            Q(order_item__order__order_number__icontains=query)
            | Q(external_invoice_number__icontains=query)
            | Q(order_item__description__icontains=query)
        ).distinct()[:5]

        results = {
            "quotes": quotes,
            "orders": orders,
            "collections": collections,
            "stock": stock,
            "query": query,
        }

    return render(request, "search_results.html", results)


from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required


@login_required
def index(request):
    # Check if the user is in the Drivers group
    if request.user.groups.filter(name="Drivers").exists():
        return redirect("driver_list:assigned_collections")

    # For other users, show the regular dashboard
    return render(request, "dashboard/index.html")
