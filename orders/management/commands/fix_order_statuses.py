from django.core.management.base import BaseCommand
from orders.models import Order, OrderItem

class Command(BaseCommand):
    help = 'Fixes order statuses based on their items\' statuses'

    def handle(self, *args, **options):
        # Get all orders
        orders = Order.objects.all()
        fixed_count = 0
        
        self.stdout.write(f"Processing {orders.count()} orders...")
        
        for order in orders:
            items = order.items.all()
            
            # Skip empty orders
            if not items.exists():
                continue
                
            # Determine correct status
            if all(item.item_status == 'delivered' for item in items):
                correct_status = 'completed'
            elif any(item.item_status != 'pending' for item in items):
                correct_status = 'processing'
            elif all(item.item_status == 'pending' for item in items):
                correct_status = 'new'
            else:
                correct_status = order.status  # No change needed
            
            # Update if needed
            if order.status != correct_status:
                old_status = order.status
                order.status = correct_status
                order.save(update_fields=['status'])
                fixed_count += 1
                
                self.stdout.write(f"Fixed Order #{order.order_number}: {old_status} → {correct_status}")
        
        if fixed_count > 0:
            self.stdout.write(self.style.SUCCESS(f"Fixed {fixed_count} orders with incorrect status"))
        else:
            self.stdout.write(self.style.SUCCESS("All orders have correct status"))