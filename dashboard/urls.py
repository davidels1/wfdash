from django.urls import path
from . import views
from .views import test_notifications_view, send_test_notification

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("rep/", views.rep_dashboard_detail, name="rep_dashboard"),
    path(
        "rep/detail/<int:user_id>/",
        views.rep_dashboard_detail,
        name="rep_dashboard_user_detail",
    ),
    path("rep/detail/", views.rep_dashboard_detail, name="rep_dashboard_detail"),
    path(
        "customer/<int:customer_id>/",
        views.customer_dashboard,
        name="customer_dashboard",
    ),
    path(
        "supplier/<int:supplier_id>/",
        views.supplier_dashboard,
        name="supplier_dashboard",
    ),
    path(
        "company/<int:company_id>/",
        views.company_dashboard,
        name="company_dashboard",
    ),
    path("test-notifications/", test_notifications_view, name="test_notifications"),
    path(
        "api/send-test-notification/",
        send_test_notification,
        name="send_test_notification",
    ),
    # ... other dashboard urls ...
]
