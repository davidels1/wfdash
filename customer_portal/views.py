import os
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.forms import formset_factory
from django.utils.crypto import get_random_string
from django.db import transaction
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail
from django.views.decorators.cache import cache_control

from .forms import CustomerQuoteForm, CustomerOrderForm, ItemForm, PortalQuoteForm, PortalQuoteItemFormSet
from .models import CustomerSubmission
from quotes.models import QuoteRequest, QuoteItem, QuoteAttachment
from orders.models import Order, OrderItem
from wfdash.models import Customers, Company
from quotes.utils import generate_unique_quote_number

# Create ItemFormSet from ItemForm
ItemFormSet = formset_factory(ItemForm, extra=1)

def home(request):
    # No authentication check here
    return render(request, 'customer_portal/home.html')


import os


@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def serve_portal_serviceworker(request):
    """Serve the existing portal service worker with proper headers"""
    # Path to your service worker file - adjust if needed
    sw_path = os.path.join(settings.STATIC_ROOT, 'customer_portal', 'portal-serviceworker.js')
    
    # If file doesn't exist in STATIC_ROOT during development, use the local path
    if not os.path.exists(sw_path):
        sw_path = os.path.join(settings.BASE_DIR, 'customer_portal', 'static', 
                               'customer_portal', 'portal-serviceworker.js')
    
    # Read the service worker file
    with open(sw_path, 'r') as f:
        content = f.read()
    
    # Return the file with proper headers
    response = HttpResponse(content, content_type='application/javascript')
    # This header is what fixes the scope issue
    response['Service-Worker-Allowed'] = '/portal/'
    return response








def quote_request(request):
    if request.method == 'POST':
        print("POST request received")
        form = PortalQuoteForm(request.POST, request.FILES)  # Add request.FILES here
        formset = PortalQuoteItemFormSet(request.POST)
        
        # Clean empty forms from formset before validation
        if formset.is_valid():
            # Valid formset - use as is
            valid_formset = formset
        else:
            # Check if we just have empty forms causing validation errors
            has_data = False
            for form_data in formset.cleaned_data:
                if form_data and not form_data.get('DELETE', False):
                    has_data = True
                    break
            
            if not has_data and len(formset.forms) > 1:
                # All forms are empty or marked for deletion except the first required one
                valid_formset = False
                form.add_error(None, "Please add at least one item to your quote request.")
            else:
                # There are actual validation errors
                valid_formset = False
        
        if form.is_valid() and valid_formset is not False:
            print("Both form and formset are valid")
            # Get default user
            default_user = User.objects.filter(is_superuser=True).first() or User.objects.first()
            
            try:
                print("Creating quote...")
                # Get or create a customer
                customer, created = Customers.objects.get_or_create(
                    email=form.cleaned_data['email'],
                    defaults={
                        'customer': form.cleaned_data['name'],
                        'company': form.cleaned_data.get('company', ''),
                        'number': form.cleaned_data['phone']
                    }
                )
                
                # Create quote with the proper field names
                quote = QuoteRequest(
                    user=default_user,
                    rep=default_user,
                    quote_number=generate_unique_quote_number(),
                    customer=customer,
                    description=form.cleaned_data['description'],
                    status='new',
                    has_attachments=bool(request.FILES.getlist('attachments[]'))  # Set has_attachments flag
                )
                quote.save()
                
                # Process formset items
                items = []
                for item_form in valid_formset:
                    # Only process forms with data
                    if item_form.has_changed() and item_form.cleaned_data and 'description' in item_form.cleaned_data:
                        item = QuoteItem.objects.create(
                            quote=quote,
                            description=item_form.cleaned_data['description'],
                            quantity=item_form.cleaned_data['quantity']
                        )
                        items.append(item)
                
                # Handle file attachments
                attachment_files = request.FILES.getlist('attachments[]')
                for uploaded_file in attachment_files:
                    attachment = QuoteAttachment(
                        quote=quote,
                        file=uploaded_file,
                        filename=uploaded_file.name
                    )
                    attachment.save()
                
                # Send email notification with attachment info
                send_quote_notification_email(quote, items, request)
                
                # Success redirect
                print(f"Quote created successfully with ID: {quote.id}")
                return redirect('customer_portal:success', type='quote', reference=quote.quote_number)
                
            except Exception as e:
                print(f"Error creating quote: {str(e)}")
                import traceback
                traceback.print_exc()
                form.add_error(None, f"Error: {str(e)}")
        else:
            print("Form or formset invalid")
            if not form.is_valid():
                print(f"Form errors: {form.errors}")
            if valid_formset is False:
                print(f"Formset errors: {formset.errors}")
    else:
        form = PortalQuoteForm()
        formset = PortalQuoteItemFormSet()
    
    return render(request, 'customer_portal/quote_form.html', {
        'form': form,
        'formset': formset
    })

# Option 2: Update the send_quote_notification_email function
def send_quote_notification_email(quote, items, request):
    """Send notification email about new quote request"""
    try:
        subject = f"New Quote Request: {quote.quote_number}"
        
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'sales@wfsales.co.za')
        to_emails = ['david.els1@outlook.com']
        
        # Get the file attachments with full URLs
        attachments = []
        image_previews = []
        
        if quote.has_attachments:
            for attachment in quote.attachments.all():
                # Create an absolute URL to the file
                file_url = request.build_absolute_uri(attachment.file.url)
                
                # Determine if this is an image file
                file_ext = attachment.file.name.lower().split('.')[-1]
                is_image = file_ext in ['jpg', 'jpeg', 'png', 'gif']
                
                attachments.append({
                    'name': attachment.filename,
                    'url': file_url,
                    'is_image': is_image
                })
                
                if is_image:
                    image_previews.append(file_url)
        
        # Context for the email template
        context = {
            'quote': quote,
            'items': items,
            'customer': quote.customer,
            'date': timezone.now(),
            'admin_url': request.build_absolute_uri(f'/admin/quotes/quoterequest/{quote.id}/change/'),
            'has_attachments': quote.has_attachments,
            'attachment_count': len(attachments),
            'attachments': attachments,
            'image_previews': image_previews  # For embedding in HTML
        }
        
        html_content = render_to_string('customer_portal/emails/new_quote_notification.html', context)
        text_content = strip_tags(html_content)
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=to_emails,
            reply_to=[quote.customer.email]
        )
        
        email.attach_alternative(html_content, "text/html")
        
        # Attach files to the email (limit to first 5 files or 10MB total)
        if quote.has_attachments:
            total_size = 0
            max_size = 10 * 1024 * 1024  # 10MB limit
            max_files = 5
            
            for i, attachment in enumerate(quote.attachments.all()):
                if i >= max_files:
                    break
                    
                # Get file size
                file_size = attachment.file.size
                if total_size + file_size > max_size:
                    break
                    
                total_size += file_size
                
                # Attach the file
                try:
                    file_path = attachment.file.path
                    with open(file_path, 'rb') as f:
                        file_content = f.read()
                        email.attach(attachment.filename, file_content)
                except Exception as e:
                    print(f"Error attaching file {attachment.filename}: {e}")
        
        email.send()
        print(f"Email notification sent to {', '.join(to_emails)} for Quote {quote.quote_number}")
        return True
        
    except Exception as e:
        print(f"Failed to send email notification: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def order_submit(request):
    if request.method == 'POST':
        form = CustomerOrderForm(request.POST)
        formset = ItemFormSet(request.POST, prefix='items')
        
        if form.is_valid() and formset.is_valid():
            # Get default user (required for Order model)
            default_user = User.objects.filter(is_superuser=True).first() or User.objects.first()
            
            try:
                # Get or create a customer
                customer, created = Customers.objects.get_or_create(
                    email=form.cleaned_data['email'],
                    defaults={
                        'customer': form.cleaned_data['name'],
                        'company': form.cleaned_data.get('company', ''),
                        'number': form.cleaned_data['phone']
                    }
                )
                
                # Find or create company record
                company_name = form.cleaned_data.get('company', customer.customer)
                
                try:
                    company = Company.objects.get(company=company_name)
                except Company.DoesNotExist:
                    company = Company.objects.create(company=company_name)
                
                # Generate a truly unique order number
                # Use a timestamp with random string to ensure uniqueness
                timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
                random_suffix = get_random_string(length=4, allowed_chars='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
                order_number = f'WEB-{timestamp}-{random_suffix}'
                
                # Create order with the unique order number
                order = Order(
                    order_number=order_number,
                    company=company,
                    rep=default_user,
                    notes=form.cleaned_data.get('notes', ''),
                    status='new'
                )
                order.save()
                
                # Create order items
                items = []
                for item_form in formset:
                    if item_form.has_changed() and item_form.cleaned_data:
                        item = OrderItem.objects.create(
                            order=order,
                            description=item_form.cleaned_data['description'],
                            quantity=item_form.cleaned_data['quantity'],
                            notes=item_form.cleaned_data.get('notes', ''),
                            selling_price=0  # Placeholder - price will be set during processing
                        )
                        items.append(item)
                
                # Send email notification
                send_order_notification_email(order, items, request)
                
                # Redirect to success page
                return redirect('customer_portal:success', type='order', reference=order.order_number)
                
            except Exception as e:
                print(f"Error creating order: {str(e)}")
                import traceback
                traceback.print_exc()
                form.add_error(None, f"Error: {str(e)}")
        else:
            print("Form or formset invalid")
            if not form.is_valid():
                print(f"Form errors: {form.errors}")
            if not formset.is_valid():
                print(f"Formset errors: {formset.errors}")
    else:
        form = CustomerOrderForm()
        formset = ItemFormSet(prefix='items')
    
    return render(request, 'customer_portal/order_form.html', {
        'form': form,
        'formset': formset
    })

def send_order_notification_email(order, items, request):
    """Send notification email about new order submission"""
    try:
        subject = f"New Order Request: {order.order_number}"
        
        # Email sent to your personal email for testing
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'sales@wfsales.co.za')
        to_emails = ['david.els1@outlook.com']  # Your personal email for testing
        
        # Context for the email template
        context = {
            'order': order,
            'items': items,  # Use the items passed from the view
            'company': order.company,
            'date': timezone.now(),
            'admin_url': request.build_absolute_uri(f'/admin/orders/order/{order.id}/change/'),
        }
        
        # Render email content
        html_content = render_to_string('customer_portal/emails/new_order_notification.html', context)
        text_content = strip_tags(html_content)  # Plain text version
        
        # Create the email
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=to_emails,
            reply_to=[from_email]  # Just use the from_email for reply-to
        )
        
        # Attach HTML content
        email.attach_alternative(html_content, "text/html")
        
        # Send the email
        email.send(fail_silently=False)  # Don't suppress errors
        print(f"Email notification sent to {', '.join(to_emails)} for Order {order.order_number}")
        return True
        
    except Exception as e:
        print(f"Failed to send email notification: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def offline(request):
    """Render the offline page for the portal"""
    return render(request, 'customer_portal/offline.html')


def success(request, type, reference):
    """Display success page after form submission"""
    return render(request, 'customer_portal/success.html', {
        'type': type,
        'reference': reference
    })

def test_email(request):
    success = send_mail(
        'Test Email from WF Sales Portal',
        'This is a test email to verify SMTP settings.',
        'sales@wfsales.co.za',
        ['david.els1@outlook.com'],
        fail_silently=False,
    )
    return HttpResponse(f"Email sent: {success}")

@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def portal_serviceworker(request):
    """Serve service worker with proper headers"""
    sw_path = os.path.join(settings.STATIC_ROOT, 'customer_portal', 'portal-serviceworker.js')
    
    # Read the file content 
    with open(sw_path, 'r') as f:
        content = f.read()
    
    # Serve with correct content type and header allowing broader scope
    response = HttpResponse(content, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/portal/'
    return response

