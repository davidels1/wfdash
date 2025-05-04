from django.urls import path
from . import views

app_name = "rep_portal"

urlpatterns = [
    path("", views.home, name="home"),
    path("quote/", views.quote_request, name="quote_request"),
    path("order/", views.order_submit, name="order_submit"),
    path("delivery/", views.delivery_create, name="delivery_create"),
    path("tasks/", views.tasks, name="tasks"),  # Add this line
    path("success/<str:type>/<str:reference>/", views.success, name="success"),
    path(
        "success/<str:type>/<str:reference>/<int:delivery_id>/",
        views.success,
        name="success_with_id",
    ),
    path("offline/", views.offline, name="offline"),
    path("serviceworker.js", views.serve_portal_serviceworker, name="serviceworker"),
    path(
        "api/customers/<int:customer_id>/",
        views.get_customer_details,
        name="get_customer_details",
    ),
    # Add API endpoints for the tasks functionality
    path(
        "api/approve-quote/<int:quote_id>/",
        views.approve_quote,
        name="approve_quote",
    ),
    path(
        "api/reject-quote/<int:quote_id>/",
        views.reject_quote,
        name="reject_quote",
    ),
    path(
        "api/delivery-items/<int:delivery_id>/",
        views.get_delivery_items,
        name="get_delivery_items",
    ),
    path(
        "api/update-prices/<int:delivery_id>/",
        views.update_prices,
        name="update_prices",
    ),
    path(
        "api/quote-details/<int:quote_id>/",
        views.get_quote_details,
        name="get_quote_details",
    ),
    path("api/items/", views.rep_item_search_api, name="rep_item_search_api"),
]
