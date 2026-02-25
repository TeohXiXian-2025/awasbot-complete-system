const API_ENDPOINT = "https://awasbot-service-611405879605.asia-southeast1.run.app/check-url";

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    // Only check when the URL is fully loaded
    if (changeInfo.status === 'complete' && tab.url) {
        
        // ✨ THE MAGIC INTERCEPTOR ✨
        // If the URL contains our secret pairing phrase...
        if (tab.url.includes("awasbot.com/pair?phone=")) {
            const urlObj = new URL(tab.url);
            const userPhone = urlObj.searchParams.get("phone");

            if (userPhone) {
                // Save the phone number into Chrome's memory
                chrome.storage.local.set({ 'saved_phone': userPhone }, () => {
                    console.log("Magic Link Successful! Phone saved:", userPhone);
                    
                    // Redirect them to our beautiful local success page!
                    const successUrl = chrome.runtime.getURL("success.html");
                    chrome.tabs.update(tabId, { url: successUrl });
                });
            }
            return; // Stop running the rest of the code for this tab
        }

        // Otherwise, run the normal security scan for regular websites
        if (tab.url.startsWith('http')) {
            checkUrlSafety(tab.url, tabId);
        }
    }
});

async function checkUrlSafety(url, tabId) {
    try {
        // ✨ DYNAMIC PHONE NUMBER ✨
        // Grab the phone number from Chrome's memory first!
        const storageResult = await chrome.storage.local.get(['saved_phone']);
        const dynamicPhone = storageResult.saved_phone || "UNKNOWN"; // Fallback if not linked

        const response = await fetch(API_ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                url: url,
                user_phone: dynamicPhone // <-- Now it uses the real saved number!
            })
        });

        const data = await response.json();
        console.log("AwasBot API Response:", data);

        // MATCHING YOUR BACKEND LOGIC: 
        // Your index.js returns verdict: "BLOCK" for red alerts
        if (data.verdict === 'BLOCK' || data.is_scam === true) {
            console.warn("AwasBot: Malicious site detected!", url);
            
            // Log the event for the local Impact Dashboard
            chrome.storage.local.get(['scamsBlocked'], (result) => {
                let count = result.scamsBlocked || 0;
                chrome.storage.local.set({ scamsBlocked: count + 1 });
            });

            // Redirect to the local warning page
            const warningUrl = chrome.runtime.getURL("warning.html") + "?url=" + encodeURIComponent(url);
            chrome.tabs.update(tabId, { url: warningUrl });
        }
    } catch (error) {
        console.error("AwasBot Error (Failed to fetch):", error);
    }
}