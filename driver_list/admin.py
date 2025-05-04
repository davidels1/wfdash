from django.contrib import admin
from .models import Collection, Supplier
from django import forms
import requests

@admin.action(description="Geocode selected suppliers")
def geocode_suppliers(modeladmin, request, queryset):
    api_key = "YOUR_GOOGLE_MAPS_API_KEY"  # Replace with your API key
    success = 0
    for supplier in queryset:
        if not supplier.address:
            continue
        
        try:
            url = f"https://maps.googleapis.com/maps/api/geocode/json?address={supplier.address}&key={api_key}"
            response = requests.get(url)
            data = response.json()
            
            if data['status'] == 'OK':
                location = data['results'][0]['geometry']['location']
                supplier.latitude = location['lat']
                supplier.longitude = location['lng']
                supplier.save()
                success += 1
        except Exception as e:
            continue
    
    modeladmin.message_user(
        request, 
        f"Successfully geocoded {success} out of {queryset.count()} suppliers."
    )

class SupplierAdminForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = '__all__'
        widgets = {
            'latitude': forms.TextInput(attrs={'type': 'number', 'step': '0.0000001'}),
            'longitude': forms.TextInput(attrs={'type': 'number', 'step': '0.0000001'}),
        }

class SupplierAdmin(admin.ModelAdmin):
    form = SupplierAdminForm
    list_display = ['suppliername', 'has_coordinates']
    search_fields = ['suppliername', 'address']
    actions = [geocode_suppliers]
    
    def has_coordinates(self, obj):
        return bool(obj.latitude and obj.longitude)
    has_coordinates.boolean = True
    has_coordinates.short_description = 'Has Coordinates'

admin.site.register(Supplier, SupplierAdmin)

@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ['order_item', 'supplier', 'driver', 'status', 'created_at']
    list_filter = ['status', 'supplier', 'driver']
    search_fields = ['order_item__description', 'supplier__suppliername']
    raw_id_fields = ['order_item']
    autocomplete_fields = ['driver']
    readonly_fields = ['created_at', 'updated_at']