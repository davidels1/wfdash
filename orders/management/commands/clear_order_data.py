from django.core.management.base import BaseCommand
from django.db import transaction
from stock_management.models import StockItem
from driver_list.models import Collection
from orders.models import OrderItem, Order, PurchaseOrder

class Command(BaseCommand):
    help = 'Safely clears all order-related data'

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                # Clear data in correct order to respect foreign keys
                self.stdout.write('Clearing StockItems...')
                StockItem.objects.all().delete()
                
                self.stdout.write('Clearing Collections...')
                Collection.objects.all().delete()
                
                self.stdout.write('Clearing PurchaseOrders...')
                PurchaseOrder.objects.all().delete()
                
                self.stdout.write('Clearing OrderItems...')
                OrderItem.objects.all().delete()
                
                self.stdout.write('Clearing Orders...')
                Order.objects.all().delete()

                self.stdout.write(self.style.SUCCESS('Successfully cleared all order data'))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error clearing data: {str(e)}'))