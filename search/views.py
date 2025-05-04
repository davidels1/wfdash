from django.shortcuts import render
from django.http import JsonResponse
from django.urls import reverse, NoReverseMatch
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model

# Adjust model imports based on your project structure
from quotes.models import QuoteRequest
from orders.models import (
    Order,
    OrderItem,
)  # Make sure OrderItem is imported if needed elsewhere
from stock_management.models import StockItem
from wfdash.models import Suppliers, Customers, Company  # Add Company

# ... import other models ...

User = get_user_model()  # Get the User model


# @login_required
def ajax_universal_search(request):
    query = request.GET.get("q", "").strip()
    results_data = []
    limit_per_model = 5

    if len(query) >= 2:
        # --- Search Quotes (QuoteRequest) ---
        try:
            quote_request_results = (
                QuoteRequest.objects.filter(
                    Q(quote_number__icontains=query)
                    | Q(customer__customer__icontains=query)  # Correct: Customer name
                    | Q(customer__company__icontains=query)  # Correct: Customer company
                    | Q(description__icontains=query)  # Correct: Quote description
                )
                .select_related("customer")
                .distinct()[:limit_per_model]
            )

            for quote_req in quote_request_results:
                try:
                    # Corrected URL name based on quotes/urls.py
                    url = reverse("quotes:quote_detail", args=[quote_req.pk])
                    customer_display = (
                        f"{quote_req.customer.customer}"
                        if quote_req.customer
                        else "N/A"
                    )
                    results_data.append(
                        {
                            "type": "Quote",
                            "display": f"{quote_req.quote_number} ({customer_display})",
                            "url": url,
                        }
                    )
                except NoReverseMatch:
                    print(
                        f"Error: No reverse match for QuoteRequest {quote_req.pk}. Check 'quotes:quote_detail' URL."
                    )
                except Exception as e:
                    print(f"Error processing QuoteRequest {quote_req.pk}: {e}")
        except Exception as e:
            print(f"Error searching QuoteRequests: {e}")

        # --- Search Orders ---
        try:
            order_results = (
                Order.objects.filter(
                    Q(order_number__icontains=query)
                    | Q(
                        company__company__icontains=query
                    )  # Search Company name via Order.company FK
                    | Q(quote__quote_number__icontains=query)
                    | Q(
                        customer__customer__icontains=query
                    )  # Also search Customer name via Order.customer FK
                )
                .select_related("company", "quote", "customer")  # Added customer
                .distinct()[:limit_per_model]
            )
            # --- DEBUG PRINT ---
            print(f"DEBUG: Found {order_results.count()} orders matching '{query}'")
            # --- END DEBUG ---
            for order in order_results:
                # --- DEBUG PRINT ---
                print(
                    f"DEBUG: Processing Order PK {order.pk}, Number {order.order_number}"
                )
                # --- END DEBUG ---
                try:
                    url = reverse("orders:order_detail", args=[order.pk])
                    # Display company or customer if company is missing
                    display_related = (
                        order.company.company
                        if order.company
                        else (order.customer.customer if order.customer else "N/A")
                    )
                    results_data.append(
                        {
                            "type": "Order",
                            "display": f"{order.order_number} ({display_related})",
                            "url": url,
                        }
                    )
                except NoReverseMatch:
                    print(
                        f"Error: No reverse match for Order {order.pk}. Check 'orders:order_detail' URL."
                    )
                except Exception as e:
                    print(f"Error processing Order {order.pk}: {e}")
        except Exception as e:
            print(f"Error searching Orders: {e}")

        # --- Search Stock (StockItem) ---
        try:
            stock_results = (
                StockItem.objects.filter(
                    Q(
                        order_item__description__icontains=query
                    )  # Corrected: Search description on related OrderItem
                    | Q(
                        collection__supplier__suppliername__icontains=query
                    )  # Corrected: Search supplier name via Collection -> Supplier
                )
                .select_related(
                    "order_item", "collection__supplier"
                )  # Corrected select_related for nested relations
                .distinct()[:limit_per_model]
            )

            for item in stock_results:
                try:
                    # Corrected URL name based on stock_management/urls.py (linking to list view)
                    url = reverse("stock_management:stock_list")
                    supplier_display = (
                        f"{item.collection.supplier.suppliername}"
                        if item.collection and item.collection.supplier
                        else "N/A"
                    )  # Corrected access via collection
                    item_description = (
                        f"{item.order_item.description}"
                        if item.order_item
                        else "Stock Item"
                    )  # Corrected access via order_item
                    results_data.append(
                        {
                            "type": "Stock",
                            "display": f"{item_description} (Supp: {supplier_display})",  # Corrected display string
                            "url": url,
                        }
                    )
                except NoReverseMatch:
                    print(
                        f"Error: No reverse match for StockItem {item.pk}. Check 'stock_management:stock_list' URL."
                    )
                except Exception as e:
                    print(f"Error processing StockItem {item.pk}: {e}")
        except Exception as e:
            print(f"Error searching StockItems: {e}")

        # --- Search Suppliers ---
        try:
            supplier_results = Suppliers.objects.filter(
                Q(suppliername__icontains=query)
                | Q(suppliernumber__icontains=query)
                | Q(supplieraddress__icontains=query)  # Correct
            ).distinct()[:limit_per_model]

            for supplier in supplier_results:
                try:
                    # Point to the new supplier dashboard view
                    url = reverse("dashboard:supplier_dashboard", args=[supplier.pk])
                    results_data.append(
                        {
                            "type": "Supplier",
                            "display": f"{supplier.suppliername}",
                            "url": url,
                        }
                    )
                except NoReverseMatch:
                    print(
                        f"Error: No reverse match for Supplier {supplier.pk}. Check 'dashboard:supplier_dashboard' URL."
                    )
                except Exception as e:
                    print(f"Error processing Supplier {supplier.pk}: {e}")
        except Exception as e:
            print(f"Error searching Suppliers: {e}")

        # --- Search Customers ---
        try:
            customer_results = Customers.objects.filter(
                Q(customer__icontains=query)
                | Q(company__icontains=query)
                | Q(email__icontains=query)
                | Q(number__icontains=query)
                | Q(rep__icontains=query)  # Correct
            ).distinct()[:limit_per_model]

            for customer in customer_results:
                try:
                    # Point to the new customer dashboard view
                    url = reverse("dashboard:customer_dashboard", args=[customer.pk])
                    results_data.append(
                        {
                            "type": "Customer",
                            "display": f"{customer.customer} ({customer.company})",
                            "url": url,
                        }
                    )
                except NoReverseMatch:
                    print(
                        f"Error: No reverse match for Customer {customer.pk}. Check 'dashboard:customer_dashboard' URL."
                    )
                except Exception as e:
                    print(f"Error processing Customer {customer.pk}: {e}")
        except Exception as e:
            print(f"Error searching Customers: {e}")

        # --- USER SEARCH SECTION ---
        try:
            user_results = (
                User.objects.filter(
                    Q(username__icontains=query)
                    | Q(first_name__icontains=query)
                    | Q(last_name__icontains=query)
                    | Q(email__icontains=query)
                )
                .filter(is_active=True)
                .distinct()[:limit_per_model]
            )

            for user_obj in user_results:
                display_name = f"{user_obj.first_name or ''} {user_obj.last_name or ''} ({user_obj.username})".strip()  # Handle potential None for names
                user_type = "User"
                url = "#"  # Default to a placeholder URL

                try:
                    if user_obj.groups.filter(name="REP").exists():
                        user_type = "Rep"
                        try:
                            # Use the new URL pattern that accepts a user_id
                            url = reverse(
                                "dashboard:rep_dashboard_user_detail",
                                args=[user_obj.pk],
                            )
                        except NoReverseMatch:
                            print(
                                f"Error: No reverse match for Rep user detail URL for User {user_obj.pk}."
                            )
                            url = "#"  # Fallback URL if reverse fails

                    results_data.append(
                        {
                            "type": user_type,
                            "display": display_name,
                            "url": url,
                        }
                    )

                except Exception as e:
                    print(f"Error processing User {user_obj.pk}: {e}")

        except Exception as e:
            print(f"Error searching Users: {e}")
        # --- END USER SEARCH SECTION ---

        # --- COMPANY SEARCH SECTION ---
        try:
            company_results = Company.objects.filter(
                Q(company__icontains=query)  # CHANGED 'name' to 'company'
                | Q(address__icontains=query)  # Added address search
            ).distinct()[:limit_per_model]
            # --- DEBUG PRINT ---
            print(
                f"DEBUG: Found {company_results.count()} companies matching '{query}'"
            )
            # --- END DEBUG ---
            for company_obj in company_results:
                # --- DEBUG PRINT ---
                print(
                    f"DEBUG: Processing Company PK {company_obj.pk}, Name {company_obj.company}"
                )
                # --- END DEBUG ---
                try:
                    url = reverse("dashboard:company_dashboard", args=[company_obj.pk])
                    results_data.append(
                        {
                            "type": "Company",
                            "display": f"{company_obj.company}",  # CHANGED 'name' to 'company'
                            "url": url,
                        }
                    )
                except NoReverseMatch:
                    print(
                        f"Error: No reverse match for Company {company_obj.pk}. Check 'dashboard:company_dashboard' URL."
                    )
                except Exception as e:
                    print(f"Error processing Company {company_obj.pk}: {e}")
        except Exception as e:
            print(f"Error searching Companies: {e}")
        # --- END COMPANY SEARCH SECTION ---

        # --- DELIVERY NOTE SEARCH SECTION ---
        # Assuming you have a DeliveryNote model, import it first
        # from delivery_notes.models import DeliveryNote # Adjust import path

        # try:
        #     # Adjust fields based on your DeliveryNote model
        #     delivery_note_results = DeliveryNote.objects.filter(
        #         Q(delivery_note_number__icontains=query) # Example field
        #         | Q(order__order_number__icontains=query)
        #         | Q(order__company__company__icontains=query)
        #         | Q(order__customer__customer__icontains=query)
        #     ).select_related('order__company', 'order__customer').distinct()[:limit_per_model]
        #
        #     print(f"DEBUG: Found {delivery_note_results.count()} delivery notes matching '{query}'") # DEBUG
        #
        #     for dn in delivery_note_results:
        #         print(f"DEBUG: Processing DeliveryNote PK {dn.pk}") # DEBUG
        #         try:
        #             # Replace 'delivery_notes:detail' with your actual URL name
        #             url = reverse("delivery_notes:detail", args=[dn.pk])
        #             display_related = (dn.order.company.company if dn.order and dn.order.company else
        #                                (dn.order.customer.customer if dn.order and dn.order.customer else "N/A"))
        #             results_data.append(
        #                 {
        #                     "type": "Delivery Note",
        #                     "display": f"{dn.delivery_note_number or 'DN '+str(dn.pk)} ({display_related})", # Adjust display
        #                     "url": url,
        #                 }
        #             )
        #         except NoReverseMatch:
        #             print(f"Error: No reverse match for DeliveryNote {dn.pk}. Check URL name.")
        #         except Exception as e:
        #             print(f"Error processing DeliveryNote {dn.pk}: {e}")
        # except NameError:
        #      print("DEBUG: DeliveryNote model not found or imported.") # Handle if model doesn't exist yet
        # except Exception as e:
        #     print(f"Error searching DeliveryNotes: {e}")
        # --- END DELIVERY NOTE SEARCH SECTION ---

        # Sort results alphabetically by display string (optional)
        results_data.sort(key=lambda x: x["display"])

    return JsonResponse({"results": results_data})
