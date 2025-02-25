from django.urls import path
from . import views

app_name = 'quotes'

urlpatterns = [
    path('list/', views.quote_list, name='quote_list'),
    path('create/', views.quote_create, name='quote_create'),
    path('<int:pk>/', views.quote_detail, name='quote_detail'),
    path('<int:pk>/edit/', views.quote_edit, name='quote_edit'),
    path('<int:pk>/delete/', views.quote_delete, name='quote_delete'),
    path('<int:pk>/claim/', views.quote_claim, name='quote_claim'),
    path('add-item/', views.add_quote_item, name='add_quote_item'),
    path('<int:pk>/process/', views.quote_process, name='quote_process'),
    path('quote/<int:quote_id>/pdf/', views.generate_quote_pdf, name='generate_quote_pdf'),
    path('generated/', views.generated_quotes, name='generated_quotes'),
]