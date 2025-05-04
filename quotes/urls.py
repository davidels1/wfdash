from django.urls import path
from . import views, views_email  # Import the new views_email module

app_name = "quotes"

urlpatterns = [
    path("list/", views.quote_list, name="quote_list"),
    path("create/", views.quote_create, name="quote_create"),
    path("<int:pk>/", views.quote_detail, name="quote_detail"),
    path("<int:pk>/edit/", views.quote_edit, name="quote_edit"),
    path("<int:pk>/delete/", views.quote_delete, name="quote_delete"),
    path("<int:pk>/claim/", views.quote_claim, name="quote_claim"),
    # path('add-item/', views.add_quote_item, name='add_quote_item'),
    path(
        "delete-item/<int:item_id>/", views.delete_quote_item, name="delete_quote_item"
    ),
    path("<int:pk>/process/", views.quote_process, name="quote_process"),
    path(
        "quote/<int:quote_id>/pdf/", views.generate_quote_pdf, name="generate_quote_pdf"
    ),
    path("generated/", views.generated_quotes, name="generated_quotes"),
    path("save-item/<int:item_id>/", views.save_quote_item, name="save_quote_item"),
    # New dedicated letterhead URLs
    path(
        "quote/<int:quote_id>/cnl-pdf/",
        views.generate_cnl_quote_pdf,
        name="cnl_quote_pdf",
    ),
    path(
        "quote/<int:quote_id>/isherwood-pdf/",
        views.generate_isherwood_quote_pdf,
        name="isherwood_quote_pdf",
    ),
    # Add the new email quote endpoint
    path("email_quote/<int:quote_id>/", views_email.email_quote, name="email_quote"),
    # Add status update endpoint
    path("update_status/<int:quote_id>/", views.update_status, name="update_status"),
    # Additional patterns to make the email feature more robust
    path(
        "quote/<int:quote_id>/cnl-pdf/",
        views.generate_cnl_quote_pdf,
        name="cnl_quote_pdf_alt",
    ),
    path(
        "quote/<int:quote_id>/isherwood-pdf/",
        views.generate_isherwood_quote_pdf,
        name="isherwood_quote_pdf_alt",
    ),
    # Add the email info URL
    path(
        "email_quote_info/<int:quote_id>/",
        views_email.email_quote_info,
        name="email_quote_info",
    ),
    # These are your current PDF generation views
    path(
        "generate_cnl_quote_pdf/<int:quote_id>/",
        views.generate_cnl_quote_pdf,
        name="generate_cnl_quote_pdf",
    ),
    path(
        "generate_isherwood_quote_pdf/<int:quote_id>/",
        views.generate_isherwood_quote_pdf,
        name="generate_isherwood_quote_pdf",
    ),
    # Add the new delete quote endpoint
    path("quotes/<int:pk>/delete/", views.quote_delete, name="quote_delete"),
    # Add the new delete attachment endpoint
    path(
        "delete-attachment/<int:pk>/", views.delete_attachment, name="delete_attachment"
    ),
    # Add the new clone quote endpoint
    path("quote/<int:pk>/clone/", views.clone_quote, name="clone_quote"),
    # Add the new split quote endpoint
    path("quote/<int:pk>/split/", views.split_quote, name="split_quote"),
    # URL for adding item to quote
    path("add_item_to_quote/", views.add_item_to_quote, name="add_item_to_quote"),
    # Add these to your urlpatterns
    path("pending-approvals/", views.pending_approvals, name="pending_approvals"),
    path("approve-quote/<int:quote_id>/", views.approve_quote, name="approve_quote"),
    path("reject-quote/<int:quote_id>/", views.reject_quote, name="reject_quote"),
    # Add these URL patterns
    # Email tracking views
    path(
        "email-tracking/",
        views_email.email_tracking_dashboard,
        name="email_tracking_dashboard",
    ),
    path(
        "email-tracking/<int:quote_id>/",
        views_email.email_tracking_detail,
        name="email_tracking_detail",
    ),
    # Email tracking URLs
    path(
        "track_email/<str:tracking_id>/",
        views_email.track_email_open,
        name="track_email_open",
    ),
    path(
        "track_click/<str:tracking_id>/",
        views_email.track_email_click,
        name="track_email_click",
    ),
    # Add direct access to the approval form
    path("approve_quote/<int:quote_id>/", views.approve_quote, name="approve_quote"),
    # Add separate email form path
    path("email_form/<int:quote_id>/", views_email.email_form, name="email_form"),
    # Add/check these URL patterns
    path(
        "quote/<int:quote_id>/cnl-pdf/",
        views.generate_cnl_quote_pdf,
        name="generate_cnl_quote_pdf",
    ),
    path(
        "quote/<int:quote_id>/ish-pdf/",
        views.generate_isherwood_quote_pdf,
        name="generate_isherwood_quote_pdf",
    ),
    # Add these to your urlpatterns in urls.py
    path(
        "preview_cnl_quote_pdf/<int:quote_id>/",
        views.preview_cnl_quote_pdf,
        name="preview_cnl_quote_pdf",
    ),
    path(
        "preview_isherwood_quote_pdf/<int:quote_id>/",
        views.preview_isherwood_quote_pdf,
        name="preview_isherwood_quote_pdf",
    ),
    # Add this to your urlpatterns in quotes/urls.py
    path(
        "upload-attachments/<int:quote_id>/",
        views.upload_attachments,
        name="upload_attachments",
    ),
    # Add this to your urlpatterns in quotes/urls.py
    path(
        "update-customer/<int:quote_id>/", views.update_customer, name="update_customer"
    ),
    # Add this new URL pattern
    path(
        "<int:quote_id>/generate-ish-quote/",
        views.generate_isherwood_quote_pdf,
        name="generate_ish_quote",
    ),
    path(
        "<int:quote_id>/generate-cnl-quote/",
        views.generate_cnl_quote_pdf,
        name="generate_cnl_quote",
    ),
    # Add this line with your other URL patterns
    path("archived/", views.archived_quotes, name="archived_quotes"),
    # Add this to your urlpatterns list
    path(
        "update-item-pricing/<int:item_id>/",
        views.update_item_pricing,
        name="update_item_pricing",
    ),
]
