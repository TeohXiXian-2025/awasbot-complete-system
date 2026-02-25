// Extract the original blocked URL from the query string
const urlParams = new URLSearchParams(window.location.search);
const blockedUrl = urlParams.get('url');
document.getElementById('site-url').innerText = "Target: " + blockedUrl;

document.getElementById('go-back').addEventListener('click', () => {
    window.history.back();
    if (window.history.length <= 1) {
        window.close();
    }
});

// Trigger the 'Family Alert' via Member 3's Pub/Sub logic
console.log("AwasBot: Sending notification to Guardian...");