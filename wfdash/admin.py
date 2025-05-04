from django.contrib import admin
from .models import Suppliers, Customers, CompanyDetails, Company


@admin.register(CompanyDetails)
class CompanyDetailsAdmin(admin.ModelAdmin):
    list_display = ["company_name", "email", "number"]
    search_fields = ["company_name", "email"]


@admin.register(Customers)
class CustomersAdmin(admin.ModelAdmin):
    list_display = ("customer", "company", "email", "number", "dateadded")
    search_fields = ("customer", "company", "email", "number")
    list_filter = ("company", "dateadded")


@admin.register(Suppliers)
class SuppliersAdmin(admin.ModelAdmin):
    list_display = (
        "suppliername",
        "suppliernumber",
        "supplieraddress",
    )  # Adjust fields as needed
    search_fields = ("suppliername", "suppliernumber")
    # Add other admin options as needed


# @admin.register(Company)
# class CompanyAdmin(admin.ModelAdmin):
#     list_display = ('company', 'address', 'vendor')
#     search_fields = ('company',)
