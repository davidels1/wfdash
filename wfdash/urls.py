from django.urls import path
from . import views

app_name = 'wfdash'

urlpatterns = [
    # Customer URLs
    path('customers/', views.customers, name='customers'),
    path('customers/list/', views.customers_list, name='customers_list'),
    path('customers/edit/<int:pk>/', views.customer_edit, name='customer_edit'),
    path('customers/delete/<int:pk>/', views.customer_delete, name='customer_delete'),
    
    # Supplier URLs
    path('suppliers/', views.suppliers, name='suppliers'),
    path('suppliers/list/', views.suppliers_list, name='suppliers_list'),
    path('supplier/edit/<int:pk>/', views.supplier_edit, name='supplier_edit'),
    path('supplier/delete/<int:pk>/', views.supplier_delete, name='supplier_delete'),
    
    # Company URLs
    path('company/', views.company, name='company'),
    path('company/list/', views.company_list, name='company_list'),
    path('company/edit/<int:pk>/', views.company_edit, name='company_edit'),
    path('company/delete/<int:pk>/', views.company_delete, name='company_delete'),
    
    # API endpoints
    path('api/company/search/', views.company_search, name='api_company_search'),
    path('api/company-search/', views.company_search, name='api_company_search'),
    path('api/supplier-search/', views.supplier_search, name='supplier_search'),

    # Universal search
    path('search/', views.universal_search, name='universal_search'),
]