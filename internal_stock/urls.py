# filepath: c:\###PYTHONANY_WORKING\WFDASH\internal_stock\urls.py
from django.urls import path
from . import views

app_name = "internal_stock"

urlpatterns = [
    # AJAX search used by quotes page
    path("search/", views.search_internal_stock, name="search_internal_stock"),
    # User-facing CRUD views
    path("", views.internal_stock_list, name="list"),  # List view at the app's root
    path("create/", views.create_internal_stock_item, name="create"),
    path(
        "edit/<int:item_id>/",
        views.edit_internal_stock_item,
        name="edit_stock_item",
    ),
    path(
        "delete/<int:item_id>/",
        views.delete_internal_stock_item,
        name="delete_stock_item",
    ),
    # New URLs for supplier price lists
    path("price-lists/", views.price_list_index, name="price_list_index"),
    path("price-lists/create/", views.create_price_list, name="create_price_list"),
    path("price-lists/<int:pk>/", views.price_list_detail, name="price_list_detail"),
    path("price-lists/<int:pk>/edit/", views.edit_price_list, name="edit_price_list"),
    path(
        "price-lists/<int:price_list_id>/add-item/",
        views.add_price_list_item,
        name="add_price_list_item",
    ),
    path(
        "price-lists/items/<int:item_id>/edit/",
        views.edit_price_list_item,
        name="edit_price_list_item",
    ),
    path(
        "price-lists/items/<int:item_id>/delete/",
        views.delete_price_list_item,
        name="delete_price_list_item",
    ),
    path(
        "price-lists/<int:price_list_id>/bulk-upload/",
        views.bulk_upload_items,
        name="bulk_upload_items",
    ),
]
