// Simple check: If user is on a sensitive page, look for "risk" indicators
if (window.location.href.includes("bank") || window.location.href.includes("login")) {
    console.log("AwasBot: Monitoring sensitive transaction...");
    
    // Logic for Member 4: Detect if 'Screen Capture' is active (Simplified for Demo)
    navigator.mediaDevices.enumerateDevices().then(devices => {
        const isSharing = devices.some(device => device.kind === 'videoinput' && device.label.includes('Virtual'));
        if (isSharing) {
            alert("⚠️ AwasBot Alert: Screen sharing detected. Please stop sharing before logging into your bank!");
            document.body.style.filter = "blur(10px)"; // "Screen Overlay Guard"
        }
    });
}