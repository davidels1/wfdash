/**
 * Internal Stock Search Functionality
 * This file handles searching and populating quote items with internal stock items
 */

(function() {
    'use strict';
    
    // Wait for document and jQuery to be ready
    document.addEventListener('DOMContentLoaded', function() {
        if (window.jQuery) {
            console.log("jQuery found, checking for jQuery UI or loading it");
            ensureJQueryUI();
        } else {
            console.error("jQuery not available for internal stock search");
        }
    });
    
    // Make sure jQuery UI is available or load it
    function ensureJQueryUI() {
        if (window.jQuery.ui) {
            console.log("jQuery UI already loaded, initializing stock search");
            initializeStockSearch();
        } else {
            console.log("jQuery UI not found, dynamically loading it");
            
            // Create link element for jQuery UI CSS
            const cssLink = document.createElement('link');
            cssLink.rel = 'stylesheet';
            cssLink.href = 'https://code.jquery.com/ui/1.13.2/themes/base/jquery-ui.css';
            document.head.appendChild(cssLink);
            
            // Create script element for jQuery UI
            const script = document.createElement('script');
            script.src = 'https://code.jquery.com/ui/1.13.2/jquery-ui.min.js';
            script.onload = function() {
                console.log("jQuery UI loaded dynamically, initializing stock search");
                initializeStockSearch();
            };
            script.onerror = function() {
                console.error("Failed to load jQuery UI dynamically");
            };
            document.head.appendChild(script);
        }
    }
    
    // Initialize the stock search functionality
    function initializeStockSearch() {
        console.log("Setting up internal stock search");
        
        try {
            // Apply autocomplete to all quote reference fields
            jQuery('textarea[name^="quote_reference_"]').each(function() {
                setupAutocompleteOnField(jQuery(this));
            });
            
            // Listen for new items being added
            if (typeof document.addEventListener === 'function') {
                document.addEventListener('new-quote-item-added', function(e) {
                    console.log('New item detected, setting up stock search');
                    if (e.detail && e.detail.itemId) {
                        const newItemField = jQuery(`textarea[name="quote_reference_${e.detail.itemId}"]`);
                        if (newItemField.length) {
                            setupAutocompleteOnField(newItemField);
                        }
                    }
                });
            }
            
            console.log("Internal stock search setup complete");
        } catch (error) {
            console.error("Error setting up stock search:", error);
        }
    }
    
    // Set up autocomplete on a specific field
    function setupAutocompleteOnField(field) {
        if (!field || field.length === 0) return;
        
        try {
            // Get item ID from name attribute (format: quote_reference_123)
            const nameAttr = field.attr('name');
            const itemId = nameAttr.split('_').pop();
            
            console.log(`Setting up autocomplete for item ${itemId}`);
            
            field.autocomplete({
                minLength: 2,
                delay: 300,
                source: function(request, response) {
                    console.log(`Searching for: ${request.term}`);
                    
                    jQuery.ajax({
                        url: '/internal_stock/search/',
                        data: { term: request.term },
                        dataType: 'json',
                        success: function(data) {
                            console.log(`Found ${data.length} results`);
                            response(data);
                        },
                        error: function(xhr, status, error) {
                            console.error("Error searching stock items:", error);
                            response([]);
                        }
                    });
                },
                select: function(event, ui) {
                    // Populate the field with selected value
                    console.log(`Selected item: ${ui.item.part_number}`);
                    field.val(ui.item.description);
                    
                    // Populate detailed description
                    const descField = jQuery(`textarea[name="description_${itemId}"]`);
                    if (descField.length) {
                        descField.val(ui.item.description);
                    }
                    
                    // Set supplier if available
                    if (ui.item.supplier_id) {
                        const supplierSelect = jQuery(`select[name="supplier_${itemId}"]`);
                        if (supplierSelect.length) {
                            supplierSelect.val(ui.item.supplier_id).trigger('change');
                        }
                    }
                    
                    // Set pricing fields
                    if (ui.item.cost_price) {
                        jQuery(`input[name="cost_price_${itemId}"]`).val(ui.item.cost_price);
                    }
                    
                    if (ui.item.markup) {
                        jQuery(`input[name="markup_${itemId}"]`).val(ui.item.markup);
                    }
                    
                    if (ui.item.selling_price) {
                        jQuery(`input[name="selling_price_${itemId}"]`).val(ui.item.selling_price);
                    }
                    
                    // Update pricing display if available
                    try {
                        // Try the pricing display update
                        if (typeof updatePriceDisplay === 'function') {
                            updatePriceDisplay(itemId);
                        } else {
                            // Update the display directly
                            const displayElem = jQuery(`.pricing-display-${itemId}`);
                            if (displayElem.length && ui.item.cost_price && ui.item.markup && ui.item.selling_price) {
                                displayElem.html(`
                                    <span class="badge bg-light text-dark">Cost: R${ui.item.cost_price}</span>
                                    <span class="badge bg-light text-dark">Markup: ${ui.item.markup}%</span>
                                    <span class="badge bg-light text-dark">Selling: R${ui.item.selling_price}</span>
                                `);
                            }
                        }
                    } catch (e) {
                        console.error("Error updating price display:", e);
                    }
                    
                    // Add visual indicator
                    if (!field.parent().find('.stock-badge').length) {
                        field.after('<span class="stock-badge badge bg-success ms-2">Stock Item</span>');
                    }
                    
                    return false;
                }
            }).autocomplete("instance")._renderItem = function(ul, item) {
                return jQuery("<li>")
                    .append("<div><strong>" + item.part_number + "</strong> - " + item.description + 
                            "<br><small>Brand: " + item.brand + 
                            (item.selling_price ? " | Price: R" + item.selling_price : "") + 
                            "</small></div>")
                    .appendTo(ul);
            };
            
            console.log(`Autocomplete set up successfully for item ${itemId}`);
        } catch (error) {
            console.error(`Error setting up autocomplete for field:`, error);
        }
    }
})();