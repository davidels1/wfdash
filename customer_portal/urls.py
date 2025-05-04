from django.urls import path
from . import views

app_name = 'customer_portal'

urlpatterns = [
    path('', views.home, name='home'),
    path('quote/', views.quote_request, name='quote_request'),
    path('order/', views.order_submit, name='order_submit'),
    path('offline/', views.offline, name='offline'),
    path('success/<str:type>/<str:reference>/', views.success, name='success'),
    path('test-email/', views.test_email, name='test_email'),
    path('portal-serviceworker.js', views.serve_portal_serviceworker, name='portal_serviceworker'),
]