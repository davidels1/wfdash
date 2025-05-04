from django.contrib import admin
from .models import QuoteRequest, QuoteItem, QuoteAttachment, VoiceNote, EmailClickTracker

class QuoteItemInline(admin.TabularInline):
    model = QuoteItem
    extra = 0
    fields = ['description', 'quantity', 'notes', 'is_processed', 'selling_price', 'supplier']

class QuoteAttachmentInline(admin.TabularInline):
    model = QuoteAttachment
    extra = 0
    readonly_fields = ['file_preview']
    
    def file_preview(self, obj):
        if obj.file:
            return f'<a href="{obj.file.url}" target="_blank">View File</a>'
        return '-'
    file_preview.allow_tags = True
    file_preview.short_description = 'Preview'

class EmailClickTrackerInline(admin.TabularInline):
    model = EmailClickTracker
    extra = 0
    readonly_fields = ('clicked_url', 'clicked_at', 'user_agent', 'ip_address')
    
    def has_add_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(QuoteRequest)
class QuoteRequestAdmin(admin.ModelAdmin):
    list_display = ['quote_number', 'customer', 'status', 'created_at', 'item_count', 'total_value', 'email_status']
    list_filter = ['status', 'created_at', 'customer', 'email_opened', 'email_delivered']
    search_fields = ['quote_number', 'customer__company', 'description']
    readonly_fields = ['quote_number', 'created_at', 'updated_at', 'email_tracking_id', 'email_delivered', 'email_delivered_at', 'email_opened', 'email_opened_at']
    inlines = [QuoteItemInline, QuoteAttachmentInline, EmailClickTrackerInline]
    date_hierarchy = 'created_at'
    
    def item_count(self, obj):
        return obj.items.count()
    item_count.short_description = 'Items'
    
    def total_value(self, obj):
        total = sum(item.selling_price * item.quantity for item in obj.items.all() if item.selling_price)
        return f"R{total:.2f}" if total else "-"
    total_value.short_description = 'Total Value'

    def email_status(self, obj):
        if obj.email_opened:
            return "Opened"
        elif obj.email_delivered:
            return "Delivered"
        elif obj.status == 'emailed':
            return "Sent"
        return "-"
    
    email_status.short_description = "Email Status"

    def get_queryset(self, request):
        # Override to ensure ALL quotes are shown with no default filtering
        # First, use the model's base manager to ensure we get all records
        qs = QuoteRequest.objects.all()
        
        # Ensure we're not affected by the default manager's filters
        if hasattr(qs.model, '_default_manager'):
            qs = qs.model._default_manager.get_queryset()
        
        # Debugging information
        print(f"Total quote requests in database: {qs.count()}")
        
        # Order by the primary key to maintain a stable order
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

@admin.register(QuoteItem)
class QuoteItemAdmin(admin.ModelAdmin):
    list_display = ['quote', 'description', 'quantity', 'selling_price', 'is_processed', 'created_at']
    list_filter = ['is_processed', 'created_at']
    search_fields = ['description', 'quote__quote_number']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(QuoteAttachment)
class QuoteAttachmentAdmin(admin.ModelAdmin):
    list_display = ['quote', 'filename', 'uploaded_at']
    list_filter = ['uploaded_at']
    search_fields = ['quote__quote_number', 'filename']

# Register Voice Note model if you have it
# First let's inspect what fields are available in the VoiceNote model
from django.db import models
try:
    # Get all fields from VoiceNote model
    voice_note_fields = [field.name for field in VoiceNote._meta.get_fields()]
    
    @admin.register(VoiceNote)
    class VoiceNoteAdmin(admin.ModelAdmin):
        # Use fields that actually exist in the model
        list_display = ['quote_request', 'created_at'] if 'quote_request' in voice_note_fields else ['created_at']
        list_filter = ['created_at']
        search_fields = ['quote_request__quote_number'] if 'quote_request' in voice_note_fields else []
except (NameError, AttributeError):
    # VoiceNote model not defined or doesn't have the expected structure
    pass

admin.site.register(EmailClickTracker)