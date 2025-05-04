from django import forms
from django.forms import formset_factory
from quotes.models import QuoteRequest, QuoteItem
from orders.models import Order, OrderItem
from wfdash.models import Customers


class RepQuoteForm(forms.Form):
    # Add a customer selection field
    customer = forms.ModelChoiceField(
        queryset=Customers.objects.all(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # These fields will be populated from the selected customer
    name = forms.CharField(
        required=True,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Customer Name"}
        ),
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "Email Address"}
        ),
    )
    phone = forms.CharField(
        required=False,  # Changed from True to False
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Phone Number"}
        ),
    )
    company = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Company Name"}
        ),
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Additional information",
            }
        ),
    )


# Add this class that was missing
class RepQuoteItemForm(forms.Form):
    description = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Item description"}
        )
    )
    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )


# Add the missing formset
RepQuoteItemFormSet = formset_factory(RepQuoteItemForm, extra=1, can_delete=False)


class ItemForm(forms.Form):
    description = forms.CharField(
        max_length=200,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Item description"}
        ),
    )
    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "min": "1", "type": "number"}
        ),
    )
    notes = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "placeholder": "Special instructions for this item",
                "rows": "2",
            }
        ),
    )


# Create a formset factory
ItemFormSet = formset_factory(ItemForm, extra=1)


class RepOrderForm(forms.Form):
    # Add a customer selection field
    customer = forms.ModelChoiceField(
        queryset=Customers.objects.all().order_by("company", "customer"),
        empty_label="Select a customer",
        widget=forms.Select(attrs={"class": "form-control select2"}),
        required=False,  # Make it optional so manual entry works too
    )

    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Customer name"}
        ),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "Customer email"}
        )
    )
    phone = forms.CharField(
        max_length=20,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Customer phone"}
        ),
    )
    company = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Company name (optional)"}
        ),
    )
    purchase_order = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "PO number (optional)"}
        ),
    )
    notes = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "placeholder": "Any special instructions or notes",
                "rows": "3",
            }
        ),
    )


# Add this to your existing forms.py


class RepDeliveryForm(forms.Form):
    # Update this field definition
    customer = forms.ModelChoiceField(
        queryset=Customers.objects.exclude(customer__isnull=True)
        .exclude(customer__exact="")
        .order_by("company", "customer")
        .distinct(),
        required=False,
        widget=forms.Select(
            attrs={"class": "form-control select2", "placeholder": "Select customer"}
        ),
    )

    name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Customer Name"}
        ),
    )

    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "Email Address"}
        ),
    )

    phone = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Phone Number"}
        ),
    )

    order_number = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Order Number (if applicable)",
            }
        ),
    )

    notes = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "placeholder": "Additional Notes",
                "rows": 3,
            }
        ),
        required=False,
    )


# Fix the DeliveryItemForm definition in forms.py
class DeliveryItemForm(forms.Form):
    description = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Item Description"}
        ),
        required=True,
    )

    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
        required=True,
    )

    notes = forms.CharField(
        widget=forms.Textarea(
            attrs={"class": "form-control", "placeholder": "Item Notes", "rows": 2}
        ),
        required=False,
    )


# Then define the formset
DeliveryItemFormSet = forms.formset_factory(DeliveryItemForm, extra=1, can_delete=True)


# Keep these if needed for compatibility or remove if not used
class PortalQuoteForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Your name"}
        ),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": "form-control", "placeholder": "Your email"}
        )
    )
    phone = forms.CharField(
        max_length=20,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Your phone"}
        ),
    )
    company = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Company name (optional)"}
        ),
    )
    description = forms.CharField(
        max_length=500,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "placeholder": "Tell us what you need a quote for",
                "rows": "3",  # Smaller for mobile
            }
        ),
    )


class PortalQuoteItemForm(forms.Form):
    description = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Item description"}
        )
    )
    quantity = forms.IntegerField(
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )


PortalQuoteItemFormSet = formset_factory(PortalQuoteItemForm, extra=1, can_delete=False)
