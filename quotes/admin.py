from django.contrib import admin
from .models import QuoteRequest, QuoteItem, QuoteAttachment

@admin.register(QuoteItem)
class QuoteItemAdmin(admin.ModelAdmin):
    list_display = ['quote', 'description', 'quantity', 'is_processed', 'created_at']
    list_filter = ['is_processed', 'created_at']
    search_fields = ['description', 'quote__quote_number']
    readonly_fields = ['created_at', 'updated_at']

class QuoteItemInline(admin.TabularInline):
    model = QuoteItem
    extra = 0

@admin.register(QuoteRequest)
class QuoteRequestAdmin(admin.ModelAdmin):
    list_display = ['quote_number', 'customer', 'status', 'email_sender', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['quote_number', 'email_sender', 'email_subject']
    readonly_fields = ['email_sender', 'email_subject', 'email_body', 'has_attachments']
    inlines = [QuoteItemInline]

@admin.register(QuoteAttachment)
class QuoteAttachmentAdmin(admin.ModelAdmin):
    list_display = ['quote', 'filename', 'uploaded_at']
    list_filter = ['uploaded_at']
    search_fields = ['quote__quote_number', 'filename']