from django import forms
from .models import DeliveryNote, DeliveryItem
from wfdash.models import Company
from django.forms import inlineformset_factory


class DeliveryNoteForm(forms.ModelForm):
    class Meta:
        model = DeliveryNote
        fields = [
            "company",
            "contact_person",
            "contact_email",
            "contact_phone",
            "delivery_date",
            "notes",
        ]
        widgets = {
            "company": forms.Select(
                attrs={
                    "class": "form-select",
                    "placeholder": "Company",
                }
            ),
            "contact_person": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Contact Person",
                }
            ),
            "contact_email": forms.EmailInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Email Address",
                }
            ),
            "contact_phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Phone Number",
                }
            ),
            "delivery_date": forms.DateInput(
                attrs={
                    "class": "form-control",
                    "type": "date",
                    "placeholder": "Delivery Date",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "Special Instructions",
                    "rows": 4,
                }
            ),
        }


class DeliveryItemForm(forms.ModelForm):
    class Meta:
        model = DeliveryItem
        fields = ["description", "quantity", "price", "notes"]
        widgets = {
            "description": forms.TextInput(
                attrs={
                    "class": "form-control",
                    # No placeholder here - it's set by JS
                }
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "1",
                    "value": "1",
                    # No placeholder for input groups
                }
            ),
            "price": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    # No placeholder for input groups
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    # No placeholder here - it's set by JS
                }
            ),
        }


DeliveryItemFormSet = inlineformset_factory(
    DeliveryNote, DeliveryItem, form=DeliveryItemForm, extra=1, can_delete=True
)


class SignatureForm(forms.ModelForm):
    """Form for capturing digital signatures"""

    digital_signature = forms.CharField(widget=forms.HiddenInput(), required=True)
    customer_order_number = forms.CharField(
        required=False,
        max_length=50,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Order/PO Number (optional)"}
        ),
    )

    class Meta:
        model = DeliveryNote
        fields = ["digital_signature", "signed_by", "customer_order_number"]
        widgets = {
            "signed_by": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Full Name"}
            )
        }


class UploadSignatureForm(forms.ModelForm):
    """Form for uploading a scanned signed delivery note"""

    signed_document = forms.FileField(
        label="Upload signed delivery note",
        help_text="Upload scanned copy of signed delivery note (PDF or image)",
    )
    signed_by = forms.CharField(
        max_length=100,
        required=False,
        label="Signed By",
        help_text="Name of person who signed the document",
    )
    customer_order_number = forms.CharField(
        max_length=50,
        required=False,
        label="Customer Order/PO Number",
        help_text="Customer's order or PO number (if provided)",
    )

    class Meta:
        model = DeliveryNote
        fields = ["signed_document", "signed_by", "customer_order_number"]
