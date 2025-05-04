from django.urls import path
from django.views.generic.base import RedirectView
from django.urls import reverse_lazy
from . import views

app_name = "delivery_notes"

urlpatterns = [
    # Class-based views
    path("", views.delivery_list, name="list"),
    path("<int:pk>/", views.delivery_detail, name="detail"),
    # Core functionality
    path("create/", views.create_delivery_note, name="create"),
    path("create-from-stock/", views.create_from_stock, name="create_from_stock"),
    path("<int:pk>/edit/", views.edit_delivery_note, name="edit"),
    path("<int:pk>/delete/", views.delete_delivery_note, name="delete"),
    # Signature handling
    path(
        "<int:pk>/sign/", views.delivery_detail, name="sign"
    ),  # Changed to existing view
    path("<int:pk>/save-signature/", views.save_signature, name="save_signature"),
    path("<int:pk>/upload-signed/", views.upload_signed_document, name="upload_signed"),
    path(
        "<int:pk>/extract-signature/",
        views.extract_signature_from_document,
        name="extract_signature",
    ),
    path(
        "delivery/<int:delivery_id>/ajax-upload-signed/",
        views.upload_signed,
        name="ajax_upload_signed",
    ),
    # PDF handling
    path("<int:pk>/pdf/", views.generate_delivery_pdf, name="generate_pdf"),
    path("<int:pk>/view-pdf/", views.view_delivery_pdf, name="view_pdf"),
    path("<int:pk>/download-pdf/", views.download_delivery_pdf, name="download_pdf"),
    path(
        "<int:pk>/regenerate-pdf/",
        views.regenerate_pdf_with_signature,
        name="regenerate_pdf",
    ),
    # Other functionality
    path("<int:pk>/convert-to-quote/", views.convert_to_quote, name="convert_to_quote"),
    path("<int:pk>/generate-quote/", views.generate_quote, name="generate_quote"),
    path("<int:pk>/record-invoice/", views.record_invoice, name="record_invoice"),
    path("item-search/", views.item_search, name="item_search"),
    path(
        "item/<int:item_id>/update-price/",
        views.update_item_pricing,
        name="update_item_pricing",
    ),
    path(
        "<int:pk>/mobile-actions/", views.mobile_delivery_actions, name="mobile_actions"
    ),
    path(
        "<int:pk>/return-from-quote/",
        views.return_from_quote_generation,
        name="return_from_quote",
    ),
    path("<int:pk>/items/json/", views.get_delivery_items_json, name="get_items_json"),
    path(
        "<int:pk>/update-status/",
        views.update_delivery_status,
        name="update_delivery_status",
    ),
    path("<int:pk>/request-order/", views.request_order_number, name="request_order"),
    path("<int:pk>/info/", views.get_delivery_info, name="get_delivery_info"),
    path("<int:pk>/regenerate-quote/", views.regenerate_quote, name="regenerate_quote"),
    # Admin redirect
    path(
        "admin/",
        RedirectView.as_view(
            url=reverse_lazy("admin:delivery_notes_deliverynote_changelist")
        ),
        name="admin_delivery_notes",
    ),
    # Ajax price search
    path(
        "ajax/price-search/",
        views.item_search,
        name="ajax_price_search",
    ),
    path(
        "ajax/save-item-price/",
        views.update_item_pricing,
        name="ajax_save_item_pricing",
    ),
    path(
        "ajax/save-bulk-price/",
        views.ajax_save_bulk_pricing_view,
        name="ajax_save_bulk_pricing",
    ),
]
