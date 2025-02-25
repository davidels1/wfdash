from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from quotes.models import QuoteRequest
from orders.models import Order
from driver_list.models import Collection

class Command(BaseCommand):
    help = 'Creates default user groups and permissions'

    def handle(self, *args, **kwargs):
        # Create Buyer group
        buyer_group, created = Group.objects.get_or_create(name='Buyer')
        
        # Define required permissions for Buyer
        buyer_permissions = [
            (QuoteRequest, ['view_quoterequest']),
            (Order, ['view_order']),
            (Collection, ['view_collection']),
        ]

        # Assign permissions to Buyer group
        for model, codenames in buyer_permissions:
            content_type = ContentType.objects.get_for_model(model)
            for codename in codenames:
                permission = Permission.objects.get(
                    content_type=content_type,
                    codename=codename,
                )
                buyer_group.permissions.add(permission)

        self.stdout.write(self.style.SUCCESS('Successfully set up groups and permissions'))