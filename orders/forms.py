from django import forms
from django.forms import modelformset_factory, BaseModelFormSet
from .models import Order, OrderItem
from wfdash.models import Company, Suppliers

class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['order_number', 'company', 'notes']
        widgets = {
            'order_number': forms.TextInput(attrs={'class': 'form-control'}),
            'company': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class OrderItemForm(forms.ModelForm):
    supplier = forms.ModelChoiceField(
        queryset=Suppliers.objects.all().order_by('suppliername'),
        empty_label="Select Supplier",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    def clean(self):
        cleaned_data = super().clean()
        cost_price = cleaned_data.get('cost_price')
        selling_price = cleaned_data.get('selling_price')
        
        if cost_price and selling_price:
            if cost_price > selling_price:
                raise forms.ValidationError(
                    "Cost price cannot be greater than selling price"
                )
        
        return cleaned_data
    
    class Meta:
        model = OrderItem
        fields = ['description', 'quantity', 'selling_price', 'notes']
        widgets = {
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

class OrderItemProcessForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ['supplier', 'cost_price']

class BaseOrderItemFormSet(BaseModelFormSet):
    def clean(self):
        if any(self.errors):
            return
        
        descriptions = []
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            
            description = form.cleaned_data.get('description')
            if description in descriptions:
                raise forms.ValidationError("Items must have unique descriptions.")
            descriptions.append(description)

OrderItemFormSet = modelformset_factory(
    OrderItem,
    form=OrderItemForm,
    formset=BaseOrderItemFormSet,
    extra=1,
    can_delete=True
)