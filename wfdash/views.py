from django.shortcuts import render, redirect
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models import Q

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



@login_required(login_url='/accounts/login/')
def customers(request):
    if request.method == 'POST':
        form = CustomersForm(request.POST)
        if form.is_valid():
            customer = form.save()
            messages.success(request, f'Customer {customer.customer} added successfully!')
            return redirect('wfdash:customers')  # Stay on same page
    else:
        form = CustomersForm()
    
    customers_list = Customers.objects.all()
    context = {
        'segment': 'customers',
        'form': form,
        'customers': customers_list
    }
    return render(request, 'wfdash/customers.html', context)
 
 
@login_required(login_url='/accounts/login/')
def customers_list(request):
    customers_list = Customers.objects.all().order_by('-dateadded')
    context = {
        'segment': 'customers_list',
        'customers': customers_list
    }
    return render(request, 'wfdash/customers_list.html', context)

@login_required(login_url='/accounts/login/')
def customer_edit(request, pk):
    customer = get_object_or_404(Customers, pk=pk)
    if request.method == 'POST':
        form = CustomersForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, 'Customer updated successfully!')
            return redirect('wfdash:customers_list')
    else:
        form = CustomersForm(instance=customer)
    return render(request, 'wfdash/customers_edit.html', {'form': form})

@login_required(login_url='/accounts/login/')
def customer_delete(request, pk):
    customer = get_object_or_404(Customers, pk=pk)
    if request.method == 'POST':
        customer.delete()
        messages.success(request, 'Customer deleted successfully!')
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'})


@login_required
def customer_list(request):
    customers = Customers.objects.all().order_by('company')
    return render(request, 'wfdash/customer_list.html', {
        'customers': customers,
        'segment': 'customers'
    })


# ====================================================================================
# ================================        SUPPLIERS        ===========================
# ====================================================================================



@login_required(login_url='/accounts/login/')
def suppliers(request):
    if request.method == 'POST':
        form = SuppliersForm(request.POST)
        if form.is_valid():
            supplier = form.save()
            messages.success(request, f'Supplier {supplier.suppliername} added successfully!')
            return redirect('wfdash_suppliers')
    else:
        form = SuppliersForm()
    
    context = {
        'segment': 'suppliers',
        'form': form,
    }
    return render(request, 'wfdash/suppliers.html', context)

@login_required(login_url='/accounts/login/')
def suppliers_list(request):
    suppliers_list = Suppliers.objects.all()
    context = {
        'segment': 'suppliers_list',
        'suppliers': suppliers_list
    }
    return render(request, 'wfdash/suppliers_list.html', context)

@login_required(login_url='/accounts/login/')
def supplier_edit(request, pk):
    supplier = get_object_or_404(Suppliers, pk=pk)
    if request.method == 'POST':
        form = SuppliersForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, 'Supplier updated successfully!')
            return redirect('wfdash_suppliers_list')
    else:
        form = SuppliersForm(instance=supplier)
    return render(request, 'wfdash/suppliers_edit.html', {'form': form})

@login_required(login_url='/accounts/login/')
def supplier_delete(request, pk):
    supplier = get_object_or_404(Suppliers, pk=pk)
    if request.method == 'POST':
        supplier.delete()
        messages.success(request, 'Supplier deleted successfully!')
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'})


@login_required
def supplier_search(request):
    """API endpoint for searching suppliers"""
    search = request.GET.get('search', '')
    suppliers = Suppliers.objects.filter(
        suppliername__icontains=search
    ).values('id', 'suppliername')[:10]
    
    results = [{'id': s['id'], 'text': s['suppliername']} for s in suppliers]
    return JsonResponse(results, safe=False)


# ====================================================================================
# ================================        COMPANY          ===========================
# ====================================================================================



@login_required(login_url='/accounts/login/')
def company(request):
    if request.method == 'POST':
        form = CompanyForm(request.POST)
        if form.is_valid():
            company = form.save()
            messages.success(request, f'Company {company.company} added successfully!')
            return redirect('wfdash:company_list')  # Updated redirect
    else:
        form = CompanyForm()
    context = {
        'segment': 'company',
        'form': form
    }
    return render(request, 'wfdash/company.html', context)

@login_required(login_url='/accounts/login/')
def company_list(request):
    companies = Company.objects.all()
    context = {'segment': 'company_list', 'companies': companies}
    return render(request, 'wfdash/company_list.html', context)

@login_required(login_url='/accounts/login/')
def company_edit(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if request.method == 'POST':
        form = CompanyForm(request.POST, instance=company)
        if form.is_valid():
            form.save()
            messages.success(request, 'Company updated successfully!')
            return redirect('wfdash_company_list')
    else:
        form = CompanyForm(instance=company)
    return render(request, 'wfdash/company_edit.html', {'form': form})

@login_required(login_url='/accounts/login/')
def company_delete(request, pk):
    company = get_object_or_404(Company, pk=pk)
    if request.method == 'POST':
        company.delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'})


def company_search(request):
    search = request.GET.get('search', '')
    companies = Company.objects.filter(company__icontains=search)[:10]
    data = [{
        'id': c.id,
        'text': c.company,
        'address': c.address
    } for c in companies]
    return JsonResponse(data, safe=False)


@login_required
def universal_search(request):
    query = request.GET.get('q', '')
    results = {
        'quotes': [],
        'orders': [],
        'collections': [],
        'stock': []
    }
    
    if query:
        # Search Quotes
        quotes = QuoteRequest.objects.filter(
            Q(quote_number__icontains=query) |
            Q(customer__company__icontains=query) |
            Q(items__description__icontains=query) |
            Q(items__selling_price__icontains=query)
        ).distinct()[:5]
        
        # Search Orders
        orders = Order.objects.filter(
            Q(order_number__icontains=query) |
            Q(company__company__icontains=query) |
            Q(items__description__icontains=query)
        ).distinct()[:5]
        
        # Search Collections
        collections = Collection.objects.filter(
            Q(order_item__order__order_number__icontains=query) |
            Q(supplier__suppliername__icontains=query) |
            Q(order_item__description__icontains=query)
        ).distinct()[:5]
        
        # Search Stock
        stock = StockItem.objects.filter(
            Q(order_item__order__order_number__icontains=query) |
            Q(external_invoice_number__icontains=query) |
            Q(order_item__description__icontains=query)
        ).distinct()[:5]
        
        results = {
            'quotes': quotes,
            'orders': orders,
            'collections': collections,
            'stock': stock,
            'query': query
        }
    
    return render(request, 'search_results.html', results)
