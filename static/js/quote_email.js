/**
 * Simple Email Quote Feature
 */

document.addEventListener('DOMContentLoaded', function() {
    console.log('Email Quote: Initializing...');
    // Only execute if we're on a quote process page with quote buttons
    const quoteButtons = document.querySelectorAll('.generate-quote-btn');
    if (quoteButtons.length > 0) {
        console.log('Email Quote: Found quote buttons');
        setupQuoteButtons();
    }
    
    function setupQuoteButtons() {
        // Get CSRF token for AJAX requests
        function getCookie(name) {
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        }
        
        // Get the current quote ID from the page
        function getQuoteId() {
            const container = document.getElementById('items-container');
            if (container && container.dataset.quoteId) {
                return container.dataset.quoteId;
            }
            
            // Try to extract from URL
            const pathParts = window.location.pathname.split('/');
            const processIndex = pathParts.indexOf('process');
            if (processIndex > 0 && processIndex > 0) {
                return pathParts[processIndex - 1];
            }
            
            return null;
        }
        
        // Get selected items for the quote
        function getSelectedItems() {
            const selectedItems = [];
            document.querySelectorAll('input[name^="include_in_quote_"]:checked').forEach(checkbox => {
                const itemId = checkbox.name.split('_').pop();
                selectedItems.push(itemId);
            });
            return selectedItems.join(',');
        }
        
        // Process each quote button
        quoteButtons.forEach(button => {
            const letterhead = button.getAttribute('data-letterhead');
            const quoteId = getQuoteId();
            
            if (!quoteId) {
                console.error('Email Quote: Could not determine quote ID');
                return;
            }
            
            console.log(`Email Quote: Processing ${letterhead} button`);
            
            // Clone the button to remove all previous event handlers
            const newButton = button.cloneNode(true);
            button.parentNode.replaceChild(newButton, button);
            
            // Directly execute the original action without showing dropdown
            newButton.addEventListener('click', function(e) {
                // Prevent the default action
                e.preventDefault();
                
                // Execute original behavior directly
                const selectedItems = getSelectedItems();
                let url;
                
                if (letterhead === 'CNL') {
                    url = `/quotes/generate_cnl_quote_pdf/${quoteId}/`;
                } else {
                    url = `/quotes/generate_isherwood_quote_pdf/${quoteId}/`;
                }
                
                if (selectedItems) {
                    url += `?items=${selectedItems}`;
                }
                
                // Navigate to the URL
                console.log(`Email Quote: Navigating to ${url}`);
                window.location.href = url;
            });
        });
    }
});

// Add a helper method for text matching in elements
if (!HTMLElement.prototype.contains) {
    HTMLElement.prototype.contains = function(text) {
        return this.textContent.indexOf(text) !== -1;
    };
}