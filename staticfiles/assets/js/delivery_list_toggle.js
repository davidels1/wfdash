document.addEventListener('DOMContentLoaded', function () {
    console.log("Delivery list toggle script loaded.");

    const toggleButtons = document.querySelectorAll('.toggle-delivery-items');

    toggleButtons.forEach(button => {
        button.addEventListener('click', function () {
            const targetId = this.getAttribute('data-target');
            const targetRow = document.querySelector(targetId);
            const icon = this.querySelector('i');

            if (targetRow && icon) {
                const isVisible = targetRow.style.display !== 'none';

                if (isVisible) {
                    targetRow.style.display = 'none';
                    icon.classList.remove('icon-minus');
                    icon.classList.add('icon-plus');
                    this.setAttribute('title', 'Show Items');
                } else {
                    targetRow.style.display = 'table-row'; // Use 'table-row' for table rows
                    icon.classList.remove('icon-plus');
                    icon.classList.add('icon-minus');
                    this.setAttribute('title', 'Hide Items');
                }
            } else {
                console.warn("Toggle target row or icon not found for button:", this);
            }
        });
    });
});