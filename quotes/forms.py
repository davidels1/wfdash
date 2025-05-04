from django import forms
from wfdash.models import Customers
from .models import QuoteRequest, QuoteItem

# Create a custom field that shows customer name and company
class CustomerChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # Show customer name and company, or just company if customer name is empty
        if obj.customer:
            return f"{obj.customer} - {obj.company}"
        return obj.company

class QuoteRequestForm(forms.ModelForm):
    # Use the custom field
    customer = CustomerChoiceField(
        queryset=Customers.objects.all().order_by('company'),
        widget=forms.Select(attrs={'class': 'form-control select2'})
    )

    class Meta:
        model = QuoteRequest
        fields = ['customer', 'description', 'notes']  # Keep your existing fields
        widgets = {
            'photo': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('customer'):
            raise forms.ValidationError("Customer is required")
        return cleaned_data

class QuoteItemForm(forms.ModelForm):
    class Meta:
        model = QuoteItem
        fields = ['description', 'quantity', 'notes']
        widgets = {
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Item description'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'value': '1'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Item notes'
            })
        }

QuoteItemFormSet = forms.inlineformset_factory(
    QuoteRequest,
    QuoteItem,
    form=QuoteItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
    max_num=10
)