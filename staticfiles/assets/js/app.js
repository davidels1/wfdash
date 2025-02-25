// Single instance of deferredPrompt
let deferredPrompt;

// PWA installation handling
window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    showInstallPrompt();
});

function showInstallPrompt() {
    if (!deferredPrompt) return;
    
    const promptDiv = document.createElement('div');
    promptDiv.className = 'install-prompt';
    promptDiv.innerHTML = `
        <div class="alert alert-info alert-dismissible fade show" role="alert">
            <strong>Install App!</strong> Install WF Sales for better experience
            <button id="installBtn" class="btn btn-primary btn-sm ms-3">Install</button>
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    document.body.appendChild(promptDiv);

    document.getElementById('installBtn').addEventListener('click', async () => {
        deferredPrompt.prompt();
        const { outcome } = await deferredPrompt.userChoice;
        console.log(`User response to install prompt: ${outcome}`);
        deferredPrompt = null;
        promptDiv.remove();
    });
}