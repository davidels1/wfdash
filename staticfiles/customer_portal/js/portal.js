// IndexedDB setup for offline form storage
const dbPromise = idb.openDB('wf-portal-db', 1, {
    upgrade(db) {
        if (!db.objectStoreNames.contains('pending-forms')) {
            db.createObjectStore('pending-forms', { keyPath: 'id', autoIncrement: true });
        }
    },
});

// Form submission handler with offline support
async function submitForm(formEl, formType) {
    const formData = new FormData(formEl);
    const formObject = {};
    
    formData.forEach((value, key) => {
        formObject[key] = value;
    });
    
    formObject.formType = formType; // 'quote' or 'order'
    formObject.timestamp = new Date().toISOString();
    
    try {
        // Try to submit online
        const response = await fetch(formEl.action, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            // Redirect to success page
            window.location.href = `/portal/success/${formType}/${data.reference}/`;
        } else {
            throw new Error('Server error');
        }
    } catch (error) {
        // Offline or server error, store the form data
        const db = await dbPromise;
        await db.add('pending-forms', formObject);
        
        // Register for background sync if supported
        if ('serviceWorker' in navigator && 'SyncManager' in window) {
            const registration = await navigator.serviceWorker.ready;
            await registration.sync.register('submit-form');
            
            // Show offline success message
            showOfflineMessage();
        } else {
            // Fallback for browsers without background sync
            showOfflineMessage();
        }
    }
    
    return false; // Prevent default form submission
}

// Show offline submission message
function showOfflineMessage() {
    const offlineMsg = document.createElement('div');
    offlineMsg.className = 'offline-message';
    offlineMsg.innerHTML = `
        <div class="offline-icon">📱</div>
        <h2>Form Saved Offline</h2>
        <p>Your submission has been saved and will be sent when you're back online.</p>
        <button class="btn btn-primary" onclick="this.parentNode.remove()">OK</button>
    `;
    document.body.appendChild(offlineMsg);
}

// Check for pending forms when coming back online
window.addEventListener('online', async () => {
    if ('serviceWorker' in navigator && 'SyncManager' in window) {
        const registration = await navigator.serviceWorker.ready;
        await registration.sync.register('submit-form');
    } else {
        // Manual submission for browsers without background sync
        submitPendingForms();
    }
});

// Manually submit pending forms
async function submitPendingForms() {
    const db = await dbPromise;
    const pendingForms = await db.getAll('pending-forms');
    
    for (const form of pendingForms) {
        try {
            const formData = new FormData();
            
            // Convert object back to FormData
            for (const [key, value] of Object.entries(form)) {
                if (key !== 'id' && key !== 'formType' && key !== 'timestamp') {
                    formData.append(key, value);
                }
            }
            
            // Submit to the appropriate endpoint
            const url = form.formType === 'quote' 
                ? '/portal/quote-request/' 
                : '/portal/order-request/';
                
            const response = await fetch(url, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            if (response.ok) {
                // Remove from IndexedDB if successful
                await db.delete('pending-forms', form.id);
            }
        } catch (error) {
            console.error('Error submitting pending form:', error);
        }
    }
}