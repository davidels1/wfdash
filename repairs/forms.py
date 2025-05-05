from django import forms
from .models import Repair, RepairPhoto, RepairQuote, RepairOrder

class RepairForm(forms.ModelForm):
    class Meta:
        model = Repair
        fields = ['repair_number', 'customer', 'supplier', 'item_description', 
                 'serial_number', 'problem_description', 'status', 'notes']
        widgets = {
            'repair_number': forms.TextInput(attrs={
                'class': 'form-control',
                'style': 'max-width: 100%;'
            }),
            'customer': forms.Select(attrs={
                'class': 'form-select select2',
                'style': 'max-width: 100%;'
            }),
            'supplier': forms.Select(attrs={
                'class': 'form-select select2',
                'style': 'max-width: 100%;'
            }),
            'item_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'style': 'min-height: 100px;'
            }),
            'serial_number': forms.TextInput(attrs={
                'class': 'form-control',
                'style': 'max-width: 100%;'
            }),
            'problem_description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'style': 'min-height: 100px;'
            }),
            'status': forms.Select(attrs={
                'class': 'form-select select2',
                'style': 'max-width: 100%;'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'style': 'min-height: 100px;'
            }),
        }


class RepairPhotoForm(forms.ModelForm):
    class Meta:
        model = RepairPhoto
        fields = ['photo', 'description']


class RepairQuoteForm(forms.ModelForm):
    class Meta:
        model = RepairQuote
        fields = ['quote_number', 'quote_date', 'supplier_quote_amount',
                 'customer_quote_amount', 'markup_percentage', 'pdf_file']
        widgets = {
            'quote_date': forms.DateInput(attrs={'type': 'date'}),
        }


class RepairOrderForm(forms.ModelForm):
    class Meta:
        model = RepairOrder
        fields = ['order_number', 'supplier', 'status', 
                 'expected_completion_date', 'amount', 'notes']
        widgets = {
            'expected_completion_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


class RepairStatusForm(forms.ModelForm):
    class Meta:
        model = Repair
        fields = ['status']