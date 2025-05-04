from django import forms
from .models import InternalStockItem, SupplierPriceList, PriceListItem
from wfdash.models import Suppliers
import datetime  # Add this import at the top of your file


class InternalStockItemForm(forms.ModelForm):
    class Meta:
        model = InternalStockItem
        fields = [
            "part_number",
            "brand",
            "description",
            "supplier",
            "cost_price",
            "markup",
            "selling_price",
            "notes",  # Add notes field
        ]
        widgets = {
            "part_number": forms.TextInput(attrs={"class": "form-control"}),
            "brand": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "cost_price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "markup": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "selling_price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Add internal notes (not visible in quotes)",
                }
            ),
        }
        help_texts = {
            "selling_price": "Leave blank to auto-calculate from cost and markup.",
            "markup": "Leave blank to auto-calculate from cost and selling price.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Optional: Order suppliers alphabetically in the dropdown
        self.fields["supplier"].queryset = Suppliers.objects.order_by("suppliername")
        # Optional: Add placeholder for supplier selection
        self.fields["supplier"].empty_label = "Select a Supplier (Optional)"

    def clean(self):
        cleaned_data = super().clean()
        cost = cleaned_data.get("cost_price")
        markup = cleaned_data.get("markup")
        selling = cleaned_data.get("selling_price")

        # Basic validation: Ensure at least cost is provided if others are for calculation
        if (markup is not None or selling is not None) and cost is None:
            self.add_error(
                "cost_price",
                "Cost price is required if markup or selling price is provided.",
            )

        return cleaned_data


class SupplierPriceListForm(forms.ModelForm):
    """Form for creating and editing supplier price lists"""

    class Meta:
        model = SupplierPriceList
        fields = [
            "supplier",
            "name",
            "year",
            "valid_from",
            "valid_until",
            "default_markup",
            "notes",
        ]
        widgets = {
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "year": forms.NumberInput(
                attrs={"class": "form-control", "min": "2000", "max": "2100"}
            ),
            "valid_from": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "valid_until": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "default_markup": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Optional: Order suppliers alphabetically in the dropdown
        self.fields["supplier"].queryset = Suppliers.objects.order_by("suppliername")
        self.fields["supplier"].empty_label = "Select a Supplier"
        # Set current year as default
        if not self.instance.pk:
            self.fields["year"].initial = datetime.date.today().year


class PriceListItemForm(forms.ModelForm):
    """Form for creating and editing price list items"""

    class Meta:
        model = PriceListItem
        fields = [
            "part_number",
            "description",
            "brand",
            "cost_price",
            "markup",
            "selling_price",
            "notes",
        ]
        widgets = {
            "part_number": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "brand": forms.TextInput(attrs={"class": "form-control"}),
            "cost_price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "markup": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "selling_price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def clean(self):
        cleaned_data = super().clean()
        cost = cleaned_data.get("cost_price")
        markup = cleaned_data.get("markup")
        selling = cleaned_data.get("selling_price")

        # Basic validation: Ensure at least cost is provided
        if not cost:
            self.add_error("cost_price", "Cost price is required.")

        # Ensure at least one of markup or selling price is provided
        if markup is None and selling is None:
            self.add_error("markup", "Either markup or selling price must be provided.")

        return cleaned_data


# Form for bulk upload of items (optional)
class BulkItemUploadForm(forms.Form):
    """Form for uploading multiple items at once (e.g., from CSV)"""

    file = forms.FileField(
        widget=forms.FileInput(attrs={"class": "form-control"}),
        help_text="Upload CSV file with columns: part_number,description,brand,cost_price,markup,selling_price,notes",
    )
