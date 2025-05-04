from django.urls import include, path, re_path
from django.conf import settings
from . import views

app_name = "stock_management"

urlpatterns = [
    path("verify/", views.stock_verification, name="stock_verification"),
    path("verify/<int:collection_id>/", views.verify_stock, name="verify_stock"),
    path("stock/", views.stock_list, name="stock_list"),
    path("update-invoice/<int:stock_id>/", views.update_invoice, name="update_invoice"),
    path("ready-delivery/", views.ready_for_delivery, name="ready_for_delivery"),
    path("ready-to-pick/", views.ready_to_pick, name="ready_to_pick"),
    path("mark-picked/<int:item_id>/", views.mark_picked, name="mark_picked"),
    path(
        "save-picking-progress/",
        views.save_picking_progress,
        name="save_picking_progress",
    ),
    re_path(
        r"^picking-slip-pdf/(?P<invoice_number>.*?)/$",
        views.generate_picking_slip_pdf,
        name="picking_slip_pdf",
    ),
    path("office-stock/", views.office_stock, name="office_stock"),
    path("delivery-pick-list/", views.delivery_pick_list, name="delivery_pick_list"),
    path("mark-loaded/<int:item_id>/", views.mark_loaded, name="mark_loaded"),
    path(
        "mark-group-delivered/", views.mark_group_delivered, name="mark_group_delivered"
    ),
    path("get-items-details/", views.get_items_details, name="get_items_details"),
    path("bulk-update-invoice/", views.bulk_update_invoice, name="bulk_update_invoice"),
    path("stock/bulk-verify/", views.bulk_verify_stock, name="bulk_verify_stock"),
    path("bulk-verify/", views.bulk_verify_stock, name="bulk_verify_stock"),
    path(
        "create-delivery-note/<int:item_id>/",
        views.create_delivery_note_from_stock,
        name="create_delivery_note_from_stock",
    ),
    path(
        "create-bulk-delivery-note/",
        views.create_bulk_delivery_note,
        name="create_bulk_delivery_note",
    ),
    # Stock Admin URLs
    path("admin/dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin/inventory-audit/", views.inventory_audit, name="inventory_audit"),
    path("admin/adjustments/", views.stock_adjustments, name="stock_adjustments"),
    path("admin/reports/", views.stock_reports, name="stock_reports"),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [
        path("__debug__/", include(debug_toolbar.urls)),
    ] + urlpatterns
