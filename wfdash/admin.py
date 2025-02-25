from django.contrib import admin
from .models import Suppliers, Customers, CompanyDetails

@admin.register(CompanyDetails)
class CompanyDetailsAdmin(admin.ModelAdmin):
    list_display = ['company_name', 'email', 'phone']  # Changed 'name' to 'company_name'
    search_fields = ['company_name', 'email']