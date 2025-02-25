from django.urls import path
from . import views

app_name = 'stock_management'

urlpatterns = [
    path('verify/', views.stock_verification, name='stock_verification'),
    path('verify/<int:collection_id>/', views.verify_stock, name='verify_stock'),
    path('stock/', views.stock_list, name='stock_list'),
    path('update-invoice/<int:stock_id>/', views.update_invoice, name='update_invoice'),
    path('ready-delivery/', views.ready_for_delivery, name='ready_for_delivery'),
    path('ready-to-pick/', views.ready_to_pick, name='ready_to_pick'),
    path('mark-picked/<int:item_id>/', views.mark_picked, name='mark_picked'),
    path('save-picking-progress/', views.save_picking_progress, name='save_picking_progress'),
    path('picking-slip-pdf/<str:invoice_number>/', views.generate_picking_slip_pdf, name='picking_slip_pdf'),
    path('office-stock/', views.office_stock, name='office_stock'),
    path('delivery-pick-list/', views.delivery_pick_list, name='delivery_pick_list'),
    path('mark-loaded/<int:item_id>/', views.mark_loaded, name='mark_loaded'),
    path('mark-group-delivered/', views.mark_group_delivered, name='mark_group_delivered'),
]