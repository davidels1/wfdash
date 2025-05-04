from django.urls import path
from . import views

app_name = "orders"

urlpatterns = [
    path("", views.order_list, name="order_list"),
    path("create/", views.order_create, name="order_create"),
    path("<int:pk>/", views.order_detail, name="order_detail"),
    path("<int:pk>/edit/", views.order_edit, name="order_edit"),
    path("<int:pk>/delete/", views.order_delete, name="order_delete"),
    path("<int:pk>/process/", views.process_order, name="process_order"),
    path("purchase-orders/", views.purchase_order_list, name="purchase_order_list"),
    path(
        "purchase-orders/<int:po_id>/download/",
        views.download_purchase_order,
        name="download_po",
    ),
    path(
        "generate-po/<int:order_id>/<int:supplier_id>/",
        views.generate_purchase_order,
        name="generate_po",
    ),
    path("save-item/<int:item_id>/", views.save_order_item, name="save_order_item"),
    path(
        "purchase-orders/preview/<int:po_id>/",
        views.preview_purchase_order,
        name="preview_po",
    ),
    path(
        "purchase-orders/<int:po_id>/email/",
        views.email_purchase_order,
        name="email_po",
    ),
    path("split-item/<int:item_id>/", views.split_order_item, name="split_order_item"),
    path("create/{mailto_url}", views.handle_mailto_error, name="handle_mailto_error"),
    path("create/{mailto_url}", views.handle_mailto_error, name="mailto_error"),
    path("create/<path:path>", views.handle_mailto_error, name="catchall_error"),
    path(
        "api/check-po-items/<int:order_id>/",
        views.check_po_items,
        name="check_po_items",
    ),
    path("check-order-number/", views.check_order_number, name="check_order_number"),
    path(
        "find-matching-quotes/<int:pk>/",
        views.find_matching_quotes,
        name="find_matching_quotes",
    ),
    path(
        "link-quote/<int:order_id>/<int:quote_id>/", views.link_quote, name="link_quote"
    ),
    path("unlink-quote/<int:order_id>/", views.unlink_quote, name="unlink_quote"),
    path("batch-match-quotes/", views.batch_match_quotes, name="batch_match_quotes"),
    path("reset-matching/", views.reset_matching, name="reset_matching"),
    path(
        "reset-selected-matching/",
        views.reset_selected_matching,
        name="reset_selected_matching",
    ),
    path("check-duplicates/", views.check_duplicates, name="check_duplicates"),
    path(
        "reset-order-matching/<int:pk>/",
        views.reset_order_matching,
        name="reset_order_matching",
    ),
    path(
        "reset-order-matching/<int:pk>/",
        views.reset_order_matching,
        name="reset_order_matching",
    ),
    path("items/", views.order_item_list, name="order_item_list"),
    path("optimized/", views.order_list_optimized, name="order_list_optimized"),
]
