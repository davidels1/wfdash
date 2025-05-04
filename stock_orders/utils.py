from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
import uuid

def generate_stock_order_number():
    """Generate a unique stock order number"""
    prefix = "STOCK-"
    timestamp = timezone.now().strftime("%Y%m%d")
    # Generate a shorter unique identifier
    unique_id = str(uuid.uuid4().int)[:6]
    return f"{prefix}{timestamp}-{unique_id}"

def send_po_to_supplier(stock_order):
    """Send purchase order to supplier via email"""
    # Make sure the supplier has an email address
    if not stock_order.supplier.email:
        return False
    
    # Prepare the email context
    context = {
        'stock_order': stock_order,
        'items': stock_order.items.all(),
        'company_name': settings.COMPANY_NAME,
        'company_address': settings.COMPANY_ADDRESS,
        'company_phone': settings.COMPANY_PHONE,
    }
    
    # Render the email body
    html_content = render_to_string('stock_orders/email/purchase_order.html', context)
    
    # Send the email
    try:
        send_mail(
            subject=f"Purchase Order #{stock_order.po_number} - {settings.COMPANY_NAME}",
            message="Please see the attached purchase order.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[stock_order.supplier.email],
            html_message=html_content,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False