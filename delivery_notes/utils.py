from django.utils import timezone

# You might need to adjust this import based on where DeliveryNote is defined
# If models.py is in the same directory (delivery_notes), this is correct:
from .models import DeliveryNote


def check_delivery_ready_status(delivery):
    """Check if delivery note is ready to be processed based on signature and prices"""
    # Must have a signature
    has_signature = bool(delivery.digital_signature) or bool(
        delivery.signed_document
    )  # Check both signature types

    if not has_signature:
        # If status is already 'signed' or beyond, don't revert it
        if delivery.status not in ["draft", "delivered"]:
            return False  # Status is already advanced, no change needed
        # If no signature and status is draft/delivered, it's not ready
        return False

    # All items must have prices > 0
    all_items_have_prices = True
    items = delivery.items.all()

    if not items.exists():  # Check if there are any items at all
        # If status is already 'signed' or beyond, don't revert it
        if delivery.status not in ["draft", "delivered"]:
            return False  # Status is already advanced, no change needed
        # If no items, it's technically not ready for pricing check
        return False

    for item in items:
        if item.price is None or item.price <= 0:
            all_items_have_prices = False
            break

    # If conditions are met (has signature AND all items priced)
    # and status is currently draft or delivered, update to signed.
    if (
        has_signature
        and all_items_have_prices
        and delivery.status in ["draft", "delivered"]
    ):
        delivery.status = "signed"
        delivery.save(update_fields=["status", "updated_at"])
        return True  # Status was updated

    # If conditions are met but status is already 'signed' or beyond, no change needed.
    elif has_signature and all_items_have_prices:
        return False  # Already in correct or later state

    # If conditions are not met, it's not ready.
    else:
        # If status is already 'signed' or beyond, don't revert it
        if delivery.status not in ["draft", "delivered"]:
            return False  # Status is already advanced, no change needed
        # Otherwise, it remains in draft/delivered state
        return False


# Add any other utility functions for the delivery_notes app here
