from django import forms
from .models import Customers, Suppliers, Company



# ====================================================================================
# ================================        CUSTOMERS        ===========================
# ====================================================================================


class CustomersForm(forms.ModelForm):
    company = forms.ModelChoiceField(
        queryset=Company.objects.all(),
        widget=forms.Select(attrs={
            'class': 'form-control select2',
            'data-placeholder': 'Select a company'
        })
    )
    address = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'readonly': True,  # Make it readonly since it's auto-populated
            'rows': 3
        }),
        required=False
    )

    class Meta:
        model = Customers
        fields = ['customer', 'email', 'number', 'company', 'address']
        widgets = {
            'customer': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Customer Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'}),
            'number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
        }
        
        
# ====================================================================================
# ================================        SUPPLIERS        ===========================
# ====================================================================================        


class SuppliersForm(forms.ModelForm):
    class Meta:
        model = Suppliers
        fields = ['suppliername', 'suppliernumber', 'supplieraddress', 'coordinates', 'closingtime' , 'supply_tags']
        widgets = {
            'suppliername': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Supplier Name'}),
            'suppliernumber': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contact Number'}),
            'supplieraddress': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address'}),
            'coordinates': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Location Coordinates'}),
            'closingtime': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Closing Time'}),
            'supply_tags': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter tags (e.g., bolts, nuts, paint)','data-role': 'tagsinput' }),
        }
        
        
# ====================================================================================
# ================================        COMPANY        =============================
# ====================================================================================  


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['company', 'address']
        widgets = {
            'company': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'})
        }
        
def company_search(request):
    search = request.GET.get('search', '')
    companies = Company.objects.filter(company__icontains=search)[:10]
    data = [{'id': c.id, 'company': c.company} for c in companies]
    return JsonResponse(data, safe=False)