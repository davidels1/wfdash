from django.urls import path
from . import views

app_name = 'stock_orders'  # This is critical for the namespace

urlpatterns = [
    # Stock Orders
    path('', views.stock_order_list, name='list'),
    path('create/', views.stock_order_create, name='create'),
    path('<int:pk>/', views.stock_order_detail, name='detail'),
    path('<int:pk>/process/', views.stock_order_process, name='process'),
    path('<int:pk>/assign-driver/', views.assign_driver, name='assign_driver'),
    path('<int:pk>/mark-collected/', views.mark_collected, name='mark_collected'),
    path('<int:pk>/cancel/', views.cancel_stock_order, name='cancel'),
    
    # API endpoints
    path('check-order-number/', views.check_order_number, name='check_order_number'),
    path('supplier-search/', views.supplier_search, name='supplier_search'),
    path('check-duplicates/', views.check_duplicates, name='check_duplicates'),
    
    # Suppliers
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),

    # Purchase Orders
    path('preview_po/<int:po_id>/', views.preview_stock_po, name='preview_po'),
    path('download_po/<int:po_id>/', views.download_stock_po, name='download_po'),
    path('email_po/<int:po_id>/', views.email_stock_po, name='email_po'),
    
    # Add this to your urlpatterns
    path('order/<int:pk>/download-po/', views.download_po, name='download_po'),
]