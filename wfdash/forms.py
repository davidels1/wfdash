from django import forms
from .models import Customers, Suppliers, Company
from django.core.exceptions import ValidationError


# ====================================================================================
# ================================        CUSTOMERS        ===========================
# ====================================================================================


class CustomersForm(forms.ModelForm):
    company = forms.ModelChoiceField(
        queryset=Company.objects.all(),
        widget=forms.Select(
            attrs={
                "class": "form-control select2",
                "data-placeholder": "Select a company",
            }
        ),
    )
    address = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "readonly": True,
                "rows": 3,
            }
        ),
        required=False,
    )

    class Meta:
        model = Customers
        fields = ["customer", "email", "number", "company", "address"]
        widgets = {
            "customer": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Customer Name"}
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "Email"}
            ),
            "number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Phone Number"}
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        customer_name = cleaned_data.get("customer")
        company = cleaned_data.get("company")

        # Get current instance ID (if editing existing customer)
        instance_id = self.instance.id if self.instance and self.instance.pk else None

        if company and customer_name:
            # Check for exact duplicate customer name within the same company
            existing_customers = Customers.objects.filter(
                customer=customer_name,  # Exact match
                company=company,  # Use the company directly
            )

            # Exclude current customer if editing
            if instance_id:
                existing_customers = existing_customers.exclude(id=instance_id)

            if existing_customers.exists():
                duplicate = existing_customers.first()
                error_msg = (
                    f"Duplicate customer found: '{duplicate.customer}' already exists "
                    f"for company '{company}' (ID: {duplicate.id})"
                )
                self.add_error("customer", error_msg)

        return cleaned_data


# ====================================================================================
# ================================        SUPPLIERS        ===========================
# ====================================================================================


class SuppliersForm(forms.ModelForm):
    class Meta:
        model = Suppliers
        fields = [
            "suppliername",
            "suppliernumber",
            "supplieraddress",
            "coordinates",
            "closingtime",
            "supply_tags",
        ]
        widgets = {
            "suppliername": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Supplier Name"}
            ),
            "suppliernumber": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Contact Number"}
            ),
            "supplieraddress": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Address"}
            ),
            "coordinates": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Location Coordinates"}
            ),
            "closingtime": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Closing Time"}
            ),
            "supply_tags": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter tags (e.g., bolts, nuts, paint)",
                    "data-role": "tagsinput",
                }
            ),
        }


# ====================================================================================
# ================================        COMPANY        =============================
# ====================================================================================


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ["company", "address", "vendor"]  # Add 'vendor' to the list
        widgets = {
            "company": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Company Name"}
            ),
            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Company Address",
                }
            ),
            "vendor": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Vendor Number (optional)",
                }
            ),
        }


def company_search(request):
    search = request.GET.get("search", "")
    companies = Company.objects.filter(company__icontains=search)[:10]
    data = [{"id": c.id, "company": c.company} for c in companies]
    return JsonResponse(data, safe=False)
