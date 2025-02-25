let orderProcessHandler = {
    init() {
        this.setupEventListeners();
    },

    setupEventListeners() {
        document.querySelectorAll('.save-item-btn').forEach(button => {
            button.addEventListener('click', (e) => this.handleSaveItem(e));
        });
    },

    async handleSaveItem(e) {
        const button = e.currentTarget;
        const itemId = button.dataset.itemId;
        const row = document.getElementById(`item-row-${itemId}`);
        
        try {
            const data = this.getFormData(row);
            if (!this.validateData(data)) return;
            
            const response = await this.saveItem(itemId, data);
            this.handleResponse(response, row);
        } catch (error) {
            console.error('Error saving item:', error);
            alert('Error saving item. Please try again.');
        }
    },

    getFormData(row) {
        return {
            supplier_id: row.querySelector('.supplier-select').value,
            cost_price: row.querySelector('.cost-price-input').value,
            order_qty: row.querySelector('.order-qty-input').value
        };
    },

    validateData(data) {
        if (!data.supplier_id || !data.cost_price) {
            alert('Please select a supplier and enter a cost price');
            return false;
        }
        return true;
    },

    async saveItem(itemId, data) {
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
        
        const response = await fetch(`/orders/save-item/${itemId}/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(data)
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        return await response.json();
    },

    handleResponse(data, row) {
        if (data.status === 'success') {
            this.updateUI(data, row);
            if (data.show_po_buttons) {
                location.reload();
            }
        } else {
            alert(data.message || 'Error saving item');
        }
    },

    updateUI(data, row) {
        // Update markup display
        const markupCell = row.querySelector('.markup');
        if (markupCell) {
            markupCell.textContent = `${data.markup}%`;
        }
        
        // Update row styling
        row.className = 'table-info';
        
        // Update status badge
        const statusBadge = row.querySelector('.badge');
        if (statusBadge) {
            statusBadge.className = 'badge bg-info';
            statusBadge.textContent = data.item_status;
        }
        
        alert('Item saved successfully');
    }
};