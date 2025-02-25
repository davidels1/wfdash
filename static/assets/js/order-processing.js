document.addEventListener('DOMContentLoaded', function() {
    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;

    document.querySelectorAll('.save-item-btn').forEach(button => {
        button.addEventListener('click', async function(e) {
            e.preventDefault();
            const itemId = this.dataset.itemId;
            const row = document.querySelector(`#item-row-${itemId}`);
            
            // Get and validate form data
            const supplierSelect = row.querySelector('.supplier-select');
            const costPriceInput = row.querySelector('.cost-price-input');
            const quantityInput = row.querySelector('.quantity-input');

            if (!supplierSelect.value) {
                alert('Please select a supplier');
                supplierSelect.focus();
                return;
            }

            if (!costPriceInput.value || parseFloat(costPriceInput.value) <= 0) {
                alert('Please enter a valid cost price');
                costPriceInput.focus();
                return;
            }

            const data = {
                supplier_id: supplierSelect.value,
                cost_price: parseFloat(costPriceInput.value).toFixed(2),
                quantity: parseInt(quantityInput.value) || 1
            };

            try {
                const response = await fetch(`/orders/save-item/${itemId}/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify(data)
                });

                const result = await response.json();

                if (response.ok) {
                    // Update UI
                    row.classList.add('table-success');
                    const badge = row.querySelector('.status-badge');
                    badge.className = 'badge bg-success';
                    badge.textContent = 'Processed';
                    
                    // Disable inputs
                    supplierSelect.disabled = true;
                    costPriceInput.disabled = true;
                    quantityInput.disabled = true;
                    this.disabled = true;

                    alert('Item saved successfully!');
                } else {
                    throw new Error(result.message || 'Error saving item');
                }
            } catch (error) {
                console.error('Error:', error);
                alert('Error saving item. Please try again.');
            }
        });
    });
});