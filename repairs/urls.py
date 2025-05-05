from django.urls import path
from . import views

app_name = 'repairs'

urlpatterns = [
    path('', views.repair_list, name='repair_list'),
    path('dashboard/', views.repair_dashboard, name='repair_dashboard'),
    path('create/', views.repair_create, name='repair_create'),
    path('<int:repair_id>/', views.repair_detail, name='repair_detail'),
    path('<int:repair_id>/update/', views.repair_update, name='repair_update'),
    path('<int:repair_id>/delete/', views.repair_delete, name='repair_delete'),
    path('<int:repair_id>/upload-photo/', views.upload_photo, name='upload_photo'),
    path('<int:repair_id>/create-quote/', views.create_quote, name='create_quote'),
    path('<int:repair_id>/approve-quote/<int:quote_id>/', views.approve_quote, name='approve_quote'),
    path('<int:repair_id>/create-order/', views.create_order, name='create_order'),
    path('<int:repair_id>/update-status/', views.update_status, name='update_status'),
]