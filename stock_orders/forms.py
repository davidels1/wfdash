from django import forms
from .models import StockOrder, StockOrderItem
from wfdash.models import Suppliers  # Import the existing Suppliers model
from django.utils import timezone  # Add this import

class SupplierForm(forms.ModelForm):
    class Meta:
        model = Suppliers  # Changed from Supplier to Suppliers
        fields = ['suppliername', 'suppliernumber', 'supplieraddress', 'supply_tags']
        widgets = {
            'supplieraddress': forms.Textarea(attrs={'rows': 3}),
        }

class StockOrderForm(forms.ModelForm):
    class Meta:
        model = StockOrder
        fields = ['order_number', 'supplier', 'notes', 'expected_delivery_date']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'expected_delivery_date': forms.DateInput(attrs={'type': 'date'}),
            'supplier': forms.Select(attrs={'class': 'form-control select2-supplier'}),
        }

class StockOrderItemForm(forms.ModelForm):
    class Meta:
        model = StockOrderItem
        fields = ['description', 'sku', 'quantity', 'unit_price', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

# For inline formsets
StockOrderItemFormSet = forms.inlineformset_factory(
    StockOrder, 
    StockOrderItem,
    form=StockOrderItemForm,
    extra=1,
    can_delete=True
)

class StockOrderProcessForm(forms.ModelForm):
    class Meta:
        model = StockOrder
        fields = ['po_number']

class AssignDriverForm(forms.ModelForm):
    planned_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=timezone.now().date(),
        required=True
    )
    
    class Meta:
        model = StockOrder
        fields = ['driver']