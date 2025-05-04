// Order Processing Functionality

// Initialize when document is ready
document.addEventListener('DOMContentLoaded', function() {
    console.log("Order process script loaded");
    
    // Get CSRF token and order ID
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    const orderId = document.querySelector('#order-id')?.value;
    
    // Wait for jQuery and Select2 to be fully loaded
    initializeWhenReady();
    
    // Item initialization
    initializePODescriptions();
    
    // Add event listeners for save buttons
    document.querySelectorAll('.save-item-btn').forEach(button => {
        button.addEventListener('click', function() {
            const itemId = this.getAttribute('data-item-id');
            saveOrderItem(itemId);
        });
    });
    
    // Add listeners for form submission
    setupFormSubmission();
});

// Wait for jQuery to be fully loaded before initializing Select2
function initializeWhenReady() {
    // Check if jQuery is loaded
    if (typeof jQuery === 'undefined' || typeof $.fn.select2 === 'undefined') {
        console.log("jQuery or Select2 not loaded yet, waiting...");
        setTimeout(initializeWhenReady, 100);
        return;
    }
    
    // jQuery and Select2 are loaded, initialize everything
    jQuery(document).ready(function($) {
        console.log("Select2 initialization starting");
        
        // Initialize Select2 for supplier dropdowns
        $('.supplier-select-searchable').select2({
            placeholder: "Search for a supplier...",
            allowClear: true,
            width: '100%',
            minimumInputLength: 2,
            ajax: {
                url: '/wfdash/api/supplier-search/',
                dataType: 'json',
                delay: 250,
                data: function(params) {
                    return {
                        search: params.term,
                        page: params.page || 1
                    };
                },
                processResults: function(data) {
                    // Transform supplier data to Select2 format
                    return {
                        results: data.map(function(supplier) {
                            return {
                                id: supplier.id,
                                text: supplier.text || supplier.suppliername
                            };
                        })
                    };
                },
                cache: true,
                error: function(jqXHR, textStatus, errorThrown) {
                    console.error('Select2 AJAX error:', textStatus, errorThrown);
                    if (typeof toastr !== 'undefined') {
                        toastr.error('Error loading suppliers. Please try again.');
                    }
                }
            }
        });

        // Test the API endpoint
        $.ajax({
            url: '/wfdash/api/supplier-search/',
            data: { search: 'a' },
            success: function(data) {
                console.log('Test supplier API response:', data);
            },
            error: function(err) {
                console.error('Test supplier API error:', err);
            }
        });

        // Pre-populate existing selections
        document.querySelectorAll('.supplier-select-searchable').forEach(select => {
            const selectedId = select.value;
            const selectedText = select.options[select.selectedIndex]?.text || '';
            
            if (selectedId && selectedText) {
                // Create the option element
                const option = new Option(selectedText, selectedId, true, true);
                
                // Append it to the select
                $(select).append(option).trigger('change');
            }
        });
        
        // Setup PO modal
        setupPOModal();
        
        // Run refresh on page load
        refreshPOSection();
    });
    
    // Real-time markup calculation
    document.querySelectorAll('.cost-price-input').forEach(input => {
        input.addEventListener('input', function() {
            const itemId = this.dataset.itemId;
            updateMarkupDisplay(itemId);
        });
        
        // Also trigger calculation on blur for good measure
        input.addEventListener('blur', function() {
            // Trigger the input event to recalculate when focus leaves the field
            this.dispatchEvent(new Event('input'));
        });
    });
}

// Update markup display based on cost price change
function updateMarkupDisplay(itemId) {
    const row = document.querySelector(`#item-row-${itemId}`);
    
    if (!row) return;
    
    // Make sure this matches the actual column position
    const sellingPriceText = row.querySelector('td:nth-child(5)').textContent.trim();
    const sellingPrice = parseFloat(sellingPriceText.replace('R', '').trim());
    const costPriceInput = row.querySelector('.cost-price-input');
    const costPrice = parseFloat(costPriceInput.value);
    
    console.log(`Updating markup for item ${itemId}. Selling: ${sellingPrice}, Cost: ${costPrice}`);
    
    if (!isNaN(sellingPrice) && !isNaN(costPrice) && costPrice > 0) {
        // Calculate markup
        const markup = ((sellingPrice - costPrice) / costPrice) * 100;
        
        // Update markup display
        const markupSpan = row.querySelector(`#markup-${itemId}`);
        if (markupSpan) {
            if (markup < 0) {
                markupSpan.classList.add('text-danger');
                markupSpan.innerHTML = `<i class="feather icon-alert-triangle"></i> ${Math.abs(markup).toFixed(2)}%`;
            } else {
                markupSpan.classList.remove('text-danger');
                markupSpan.textContent = `${markup.toFixed(2)}%`;
            }
        }
    }
}

// Handle order form submission
function setupFormSubmission() {
    const orderForm = document.querySelector('form');
    if (orderForm) {
        orderForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Count processed vs. unprocessed items
            const totalItems = document.querySelectorAll('tbody tr[id^="item-row-"]').length;
            const unprocessedRows = document.querySelectorAll('tr:not(.table-info):not(.table-success)').length;
            
            // Notify user about unprocessed items
            if (unprocessedRows > 0) {
                if (totalItems === 1) {
                    toastr.info('Item not processed yet. You can process it later.', 'Processing Order');
                } else {
                    toastr.info(`${unprocessedRows} of ${totalItems} items not processed. You can process them later.`, 'Processing Order');
                }
            } else {
                toastr.success('All items have been processed', 'Processing Order');
            }
            
            // Enable disabled fields for form submission
            const disabledFields = document.querySelectorAll('input:disabled, select:disabled');
            disabledFields.forEach(field => {
                field.dataset.wasDisabled = 'true';
                field.disabled = false;
            });
            
            // Submit form via AJAX
            const formData = new FormData(this);
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            
            fetch(window.location.href, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    toastr.success('Order processed successfully', 'Success');
                    
                    // Check for PO items
                    if (data.has_po_items) {
                        refreshPOSection();
                    }
                } else {
                    toastr.error(data.message || 'Error processing order', 'Error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                toastr.error('Error processing order', 'Error');
            })
            .finally(() => {
                // Re-disable fields that were disabled
                disabledFields.forEach(field => {
                    if (field.dataset.wasDisabled === 'true') {
                        field.disabled = true;
                    }
                });
            });
        });
    }
}

// Function to save an order item
function saveOrderItem(itemId) {
    const row = document.querySelector(`#item-row-${itemId}`);
    if (!row) return;
    
    // Get button and save original state
    const saveButton = row.querySelector('.save-item-btn');
    if (saveButton) {
        saveButton.disabled = true;
        saveButton.innerHTML = '<i class="feather icon-loader"></i> Saving...';
    }
    
    // Get all required input fields
    const supplierSelect = row.querySelector('.supplier-select-searchable');
    const costPriceInput = row.querySelector('.cost-price-input');
    const orderQtyInput = row.querySelector('.order-qty-input');
    const poDescriptionInput = row.querySelector('.po-description-input'); // Add this line
    
    // Validate required fields
    if (!supplierSelect.value || !costPriceInput.value) {
        toastr.error('Please select a supplier and enter a cost price', 'Error');
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.innerHTML = 'Save Item';
        }
        return;
    }
    
    // Prepare data for server
    const data = {
        supplier_id: supplierSelect.value,
        cost_price: costPriceInput.value,
        quantity: orderQtyInput.value,
        po_description: poDescriptionInput.value // Add this line
    };
    
    // Get CSRF token
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
    
    // Send the data to the server
    fetch(`/orders/save-item/${itemId}/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(result => {
        console.log("Save response:", result);
        
        if (result.status === 'success') {
            toastr.success('Item saved successfully');
            
            // Update markup display
            const markupSpan = document.querySelector(`#markup-${itemId}`);
            if (markupSpan) {
                markupSpan.textContent = `${result.data.markup.toFixed(2)}%`;
            }
            
            // Update saved state visual indicators
            row.classList.add('table-info');
            const badge = row.querySelector('.badge');
            if (badge) {
                badge.className = 'badge bg-info';
                badge.textContent = 'Processed';
            }
            
            // Update button
            if (saveButton) {
                saveButton.innerHTML = '<i class="feather icon-check"></i> Processed';
                saveButton.classList.remove('btn-primary');
                saveButton.classList.add('btn-success');
            }
            
            // Refresh PO section
            setTimeout(refreshPOSection, 500);
        } else {
            toastr.error(result.message || 'Error saving item');
            
            // Reset button
            if (saveButton) {
                saveButton.disabled = false;
                saveButton.innerHTML = 'Save Item';
            }
        }
    })
    .catch(error => {
        console.error('Error saving item:', error);
        toastr.error('Failed to save item');
        
        // Reset button
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.innerHTML = 'Save Item';
        }
    });
}

// Setup PO modal
function setupPOModal() {
    const poModal = document.getElementById('poModal');
    if (poModal) {
        poModal.addEventListener('show.bs.modal', function() {
            const modalBody = document.getElementById('poModalBody');
            const orderId = document.querySelector('#order-id')?.value;
            
            if (modalBody && orderId) {
                // Show loading spinner
                modalBody.innerHTML = `
                    <div class="text-center">
                        <div class="spinner-border text-primary" role="status">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                        <p class="mt-2">Loading suppliers and items...</p>
                    </div>
                `;
                
                // Fetch PO data
                fetch(`/orders/api/check-po-items/${orderId}/`, {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.has_po_items && data.suppliers_items.length > 0) {
                        let content = '';
                        
                        data.suppliers_items.forEach(supplierData => {
                            const supplier = supplierData.supplier;
                            const items = supplierData.items;
                            
                            content += `
                                <div class="mb-3">
                                    <h6>${supplier.suppliername}</h6>
                                    <ul class="list-unstyled">
                            `;
                            
                            items.forEach(item => {
                                content += `<li>${item.description} (Order Qty: ${item.order_qty})</li>`;
                            });
                            
                            content += `
                                    </ul>
                                    <a href="/orders/generate-po/${orderId}/${supplier.id}/" 
                                       class="btn btn-primary btn-sm">
                                        Generate PO
                                    </a>
                                </div>
                            `;
                        });
                        
                        modalBody.innerHTML = content;
                    } else {
                        modalBody.innerHTML = `
                            <div class="alert alert-info">
                                No items are ready for PO generation. Process items first.
                            </div>
                        `;
                    }
                })
                .catch(error => {
                    console.error('Error loading PO data:', error);
                    modalBody.innerHTML = `
                        <div class="alert alert-danger">
                            Error loading data. Please try again.
                        </div>
                    `;
                });
            }
        });
    }
}

// Function to refresh PO generation section
function refreshPOSection() {
    const orderId = document.querySelector('#order-id')?.value;
    if (!orderId) return;
    
    fetch(`/orders/api/check-po-items/${orderId}/`, {
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
        }
    })
    .then(response => response.json())
    .then(data => {
        console.log('PO section data:', data);
        
        if (data.has_po_items) {
            // Show PO generation section
            let poSection = document.querySelector('.po-generation-section');
            
            if (!poSection) {
                // Create the section if it doesn't exist
                poSection = document.createElement('div');
                poSection.className = 'po-generation-section mt-4';
                
                const card = document.createElement('div');
                card.className = 'card';
                
                const cardHeader = document.createElement('div');
                cardHeader.className = 'card-header';
                cardHeader.innerHTML = '<h5>Generate Purchase Orders</h5>';
                
                const cardBody = document.createElement('div');
                cardBody.className = 'card-body';
                cardBody.id = 'poGenerationContent';
                
                card.appendChild(cardHeader);
                card.appendChild(cardBody);
                poSection.appendChild(card);
                
                // Add after the order form
                const orderForm = document.querySelector('form');
                if (orderForm && orderForm.parentNode) {
                    orderForm.parentNode.insertBefore(poSection, orderForm.nextSibling);
                }
            } else {
                poSection.classList.remove('d-none');
                poSection.style.display = '';
            }
            
            // Update content
            const poContent = document.getElementById('poGenerationContent');
            if (poContent) {
                poContent.innerHTML = '';
                
                data.suppliers_items.forEach(supplierData => {
                    const supplier = supplierData.supplier;
                    const items = supplierData.items;
                    
                    const supplierDiv = document.createElement('div');
                    supplierDiv.className = 'mb-3 pb-3 border-bottom';
                    
                    // Add supplier heading
                    const heading = document.createElement('h6');
                    heading.textContent = supplier.suppliername;
                    supplierDiv.appendChild(heading);
                    
                    // Add item list
                    const itemList = document.createElement('ul');
                    itemList.className = 'list-unstyled ps-3 mb-2';
                    
                    items.forEach(item => {
                        const listItem = document.createElement('li');
                        listItem.textContent = `${item.description} (Qty: ${item.order_qty})`;
                        itemList.appendChild(listItem);
                    });
                    
                    supplierDiv.appendChild(itemList);
                    
                    // Add PO generation button
                    const poButton = document.createElement('a');
                    poButton.href = `/orders/generate-po/${orderId}/${supplier.id}/`;
                    poButton.className = 'btn btn-success btn-sm';
                    poButton.innerHTML = '<i class="feather icon-file-text me-1"></i> Generate PO';
                    supplierDiv.appendChild(poButton);
                    
                    poContent.appendChild(supplierDiv);
                });
            }
            
            // Update header button
            const headerButton = document.querySelector('.card-header button[data-bs-target="#poModal"]');
            if (!headerButton) {
                const headerDiv = document.querySelector('.card-header .d-flex');
                if (headerDiv) {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'btn btn-success';
                    button.dataset.bsToggle = 'modal';
                    button.dataset.bsTarget = '#poModal';
                    button.innerHTML = '<i class="feather icon-file-text me-1"></i> Generate PO';
                    headerDiv.appendChild(button);
                }
            }
        } else {
            // Hide PO section
            const poSection = document.querySelector('.po-generation-section');
            if (poSection) {
                poSection.style.display = 'none';
            }
            
            // Hide header button
            const headerButton = document.querySelector('.card-header button[data-bs-target="#poModal"]');
            if (headerButton) {
                headerButton.style.display = 'none';
            }
        }
    })
    .catch(error => {
        console.error('Error checking for PO items:', error);
    });
}

// Initialize PO descriptions if they're empty
function initializePODescriptions() {
    document.querySelectorAll('.po-description-input').forEach(input => {
        if (!input.value) {
            const itemId = input.dataset.itemId;
            const row = document.querySelector(`#item-row-${itemId}`);
            if (row) {
                const description = row.cells[0].textContent.trim();
                input.value = description;
                console.log(`Initialized PO description for item ${itemId} with: ${description}`);
            }
        }
    });
}

// Export functions for global use
window.saveOrderItem = saveOrderItem;
window.refreshPOSection = refreshPOSection;
window.updateMarkupDisplay = updateMarkupDisplay;
window.initializePODescriptions = initializePODescriptions;