// filepath: c:\###PYTHONANY_WORKING\WFDASH\static\js\company_dashboard_toggle.js
// Make sure this runs AFTER the DOM is loaded
document.addEventListener('DOMContentLoaded', function () {
    console.log("Toggle script loaded and DOM ready."); // Check if script runs

    const toggleOrdersBtn = document.getElementById('toggle-orders');
    const toggleCustomersBtn = document.getElementById('toggle-customers');
    const ordersTableDiv = document.getElementById('orders-table');
    const customersTableDiv = document.getElementById('customers-table');

    // Check if elements were found
    console.log("Toggle Orders Button:", toggleOrdersBtn);
    console.log("Toggle Customers Button:", toggleCustomersBtn);
    console.log("Orders Table Div:", ordersTableDiv);
    console.log("Customers Table Div:", customersTableDiv);

    if (toggleOrdersBtn && ordersTableDiv) {
        toggleOrdersBtn.addEventListener('click', function () {
            console.log("Toggle Orders button clicked!"); // Check if listener fires
            ordersTableDiv.classList.toggle('d-none');
            // Optionally hide the other table if needed
            if (customersTableDiv && !ordersTableDiv.classList.contains('d-none')) {
                 console.log("Showing Orders, hiding Customers");
                 customersTableDiv.classList.add('d-none');
            }
        });
    } else {
        console.error("Could not find Orders toggle button or table div!");
    }

    if (toggleCustomersBtn && customersTableDiv) {
        toggleCustomersBtn.addEventListener('click', function () {
            console.log("Toggle Customers button clicked!"); // Check if listener fires
            customersTableDiv.classList.toggle('d-none');
             // Optionally hide the other table if needed
            if (ordersTableDiv && !customersTableDiv.classList.contains('d-none')) {
                console.log("Showing Customers, hiding Orders");
                ordersTableDiv.classList.add('d-none');
            }
        });
    } else {
        console.error("Could not find Customers toggle button or table div!");
    }

    // Optional: Ensure one table is visible initially if both start hidden
    // if (ordersTableDiv && customersTableDiv && ordersTableDiv.classList.contains('d-none') && customersTableDiv.classList.contains('d-none')) {
    //    console.log("Both tables hidden initially, showing Orders.");
    //    ordersTableDiv.classList.remove('d-none');
    // }

    document.querySelectorAll('.toggle-items').forEach(button => {
        button.addEventListener('click', function() {
            const targetId = this.getAttribute('data-target');
            const targetRow = document.querySelector(targetId);
            const icon = this.querySelector('i');

            if (targetRow) {
                if (targetRow.style.display === 'none') {
                    targetRow.style.display = 'table-row';
                    if(icon) icon.classList.replace('icon-plus', 'icon-minus');
                } else {
                    targetRow.style.display = 'none';
                    if(icon) icon.classList.replace('icon-minus', 'icon-plus');
                }
            } else {
                console.warn('Toggle target row not found:', targetId);
            }
        });
    });
});