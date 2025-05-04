// Add this new script to fix the delete functionality
document.addEventListener('DOMContentLoaded', function() {
    // Fix for delete item functionality
    document.querySelectorAll('.remove-item').forEach(button => {
        button.addEventListener('click', function(event) {
            event.preventDefault();
            const itemId = this.getAttribute('data-item-id');
            
            if (confirm('Are you sure you want to delete this item?')) {
                // Get CSRF token
                const csrftoken = getCookie('csrftoken');
                
                // Send the delete request
                fetch(`/quotes/delete-item/${itemId}/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrftoken
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        // Find both the item row and any associated notes row
                        const itemRow = document.querySelector(`tr[data-item-id="${itemId}"]`);
                        const notesRow = document.getElementById(`notes-row-${itemId}`);
                        
                        // Remove both rows if they exist
                        if (itemRow) itemRow.remove();
                        if (notesRow) notesRow.remove();
                        
                        // Show success message
                        alert('Item deleted successfully!');
                        
                        // Optionally reload the page to ensure everything is updated
                        // location.reload();
                    } else {
                        alert(`Error: ${data.message}`);
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    alert('An error occurred while deleting the item.');
                });
            }
        });
    });
    
    // Helper function to get CSRF token
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
});

// Enhanced quote process functionality
document.addEventListener('DOMContentLoaded', function() {
    console.log('Quote process enhanced script loaded');
    
    // Flash saved rows with animation
    document.querySelectorAll('.save-item-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const itemId = this.getAttribute('data-item-id');
            const row = document.querySelector(`tr[data-item-id="${itemId}"]`);
            
            // After saving (in callback), add animation
            setTimeout(() => {
                if (row) {
                    row.classList.add('row-saved');
                    setTimeout(() => row.classList.remove('row-saved'), 1000);
                }
            }, 200);
        });
    });
    
    // Any other enhanced functionality can go here
});