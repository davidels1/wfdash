from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('', views.order_list, name='order_list'),
    path('create/', views.order_create, name='order_create'),
    path('<int:pk>/', views.order_detail, name='order_detail'),
    path('<int:pk>/edit/', views.order_edit, name='order_edit'),
    path('<int:pk>/delete/', views.order_delete, name='order_delete'),
    path('<int:pk>/process/', views.process_order, name='process_order'),
    path('purchase-orders/', views.purchase_order_list, name='purchase_order_list'),
    path('purchase-orders/<int:po_id>/download/', views.download_purchase_order, name='download_po'),
    path('generate-po/<int:order_id>/<int:supplier_id>/', 
         views.generate_purchase_order, 
         name='generate_po'),
    path('save-item/<int:item_id>/', views.save_order_item, name='save_order_item'),
    path('purchase-orders/preview/<int:po_id>/', views.preview_purchase_order, name='preview_po'),
    path('purchase-orders/<int:po_id>/email/', views.email_purchase_order, name='email_po'),
]