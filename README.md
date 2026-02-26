# AwasBot - AI-Powered Scam Detection & Family Protection System

A comprehensive anti-scam platform combining AI threat detection, family guardian alerts, and browser protection to safeguard users from phishing, malware, deepfakes, and financial fraud.

## 🎯 Project Overview

**AwasBot** is a multi-layered security ecosystem designed for Southeast Asian users that detects and blocks scams in real-time through:

- **Telegram Bot** - Multi-modal threat scanning (images, audio, video, documents, URLs)
- **Chrome Extension** - Browser-level phishing/malware blocking with guardian alerts
- **Bank Portal** - Secure transaction verification with AI risk scoring
- **Guardian System** - Family member approval workflow for high-risk transfers

### Key Features

✅ **AI-Powered Threat Detection** (Google Gemini 3.5 Flash)  
✅ **Multi-Layer Security** (Google Web Risk + VirusTotal + Forensic Analysis)  
✅ **Real-Time Guardian Alerts** (Telegram SOS notifications)  
✅ **Deepfake Detection** (Audio & Video forensics)  
✅ **APK Malware Analysis** (Banking trojan detection)  
✅ **3-Language Support** (English, Bahasa Melayu, 中文)  
✅ **Browser Interception** (Chrome extension URL blocking)  
✅ **Firestore Evidence Vault** (Incident logging & analytics)

---

## 📁 Project Structure

```
awasbot-complete-system/
├── index.html                      # Bank Portal (Frontend)
├── chrome-extension/
│   ├── background.js              # URL interception & magic link handler
│   ├── content.js                 # Screen sharing detection
│   ├── warning.html               # Scam blocking page
│   ├── warning.js                 # Warning page logic
│   ├── success.html               # Device linking confirmation
│   └── manifest.json              # Chrome extension config
├── awasbot-project/
│   ├── main.py                    # Cloud Run backend (Flask Functions)
│   ├── Dockerfile                 # Container image spec
│   ├── requirements.txt           # Python dependencies
│   └── .env (create manually)     # API keys & secrets
├── .gitignore
└── README.md
```

---

## 🚀 Quick Start

### Prerequisites

- **Google Cloud Account** (Cloud Run, Firestore, reCAPTCHA Enterprise)
- **Python 3.10+**
- **Docker** (for deployment)
- **Telegram Bot Tokens** (2: Main Bot + Guardian Bot)
- **API Keys**: 
  - Google Gemini API
  - Google Web Risk API
  - VirusTotal API
  - reCAPTCHA Enterprise

### 1. Clone & Setup Python Backend

```bash
cd awasbot-project
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create `.env` in awasbot-project:

```env
# Telegram Bots
TELEGRAM_TOKEN=your_main_bot_token_here
TELEGRAM_TOKEN_GUARDIAN=your_guardian_bot_token_here

# AI & Security APIs
GEMINI_API_KEY=your_google_gemini_key
VT_API_KEY=your_virustotal_key
WR_API_KEY=your_google_web_risk_key

# Google Cloud
BANK_PROJECT_ID=your_gcp_project_id
BANK_API_KEY=your_recaptcha_api_key
BANK_SITE_KEY=your_recaptcha_site_key

# Firestore (uses Application Default Credentials)
# Run: gcloud auth application-default login
```

### 3. Deploy to Google Cloud Run

```bash
cd awasbot-project

# Build & deploy
gcloud run deploy awasbot-service \
  --source . \
  --platform managed \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --memory=2Gi \
  --timeout=3600
```

**Set environment variables in Cloud Run console or via `--set-env-vars`:**

```bash
gcloud run deploy awasbot-service \
  --update-env-vars TELEGRAM_TOKEN=xxx,VT_API_KEY=xxx,GEMINI_API_KEY=xxx...
```

### 4. Configure Telegram Webhooks

Set the webhook URL for both bots:

```bash
# Main Bot
curl https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook \
  -d url="https://your-cloud-run-url/mainbot" \
  -d allowed_updates='["message","callback_query"]'

# Guardian Bot
curl https://api.telegram.org/bot{TELEGRAM_TOKEN_GUARDIAN}/setWebhook \
  -d url="https://your-cloud-run-url/guardianbot" \
  -d allowed_updates='["message","callback_query"]'
```

### 5. Setup Chrome Extension

1. Open `chrome://extensions/`
2. Enable **Developer Mode** (top right)
3. Click **Load unpacked**
4. Select chrome-extension folder
5. Update the API endpoint in background.js (line 1):
   ```javascript
   const API_ENDPOINT = "https://YOUR-CLOUD-RUN-URL/check-url";
   ```

### 6. Update Bank Portal

In index.html, update the Cloud Run URL (line ~240):

```javascript
fetch('https://YOUR-CLOUD-RUN-URL/bank_webhook', ...)
```

And the status check (line ~355):

```javascript
fetch('https://YOUR-CLOUD-RUN-URL/check_status', ...)
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  USER TOUCHPOINTS                        │
├──────────────────┬──────────────────┬──────────────────┐
│  Telegram Bot    │  Chrome Extension │  Bank Portal    │
│  (Scan Media)    │  (URL Blocking)   │ (Transfers)     │
└────────┬─────────┴──────────┬────────┴────────┬────────┘
         │                    │                 │
         └────────────────────┼─────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Cloud Run (main.py)│
                    │   Flask Functions   │
                    └──┬────────┬────┬────┘
         ┌──────────────┘ │      │    │
         │        ┌───────┘      │    │
    ┌────▼──┐   ┌─▼──────┐  ┌───▼┐  │
    │Gemini │   │Firestore  │VT/WR  │
    │(AI)   │   │(Database)   │ │
    └───────┘   └────────┘  └────┘
         │             │
    ┌────┴─────────────┴───────┐
    │   Guardian Bot (Approval) │
    │  (Telegram SOS Alerts)    │
    └──────────────────────────┘
```

---

## 📱 How It Works

### Scenario 1: User Scans a Phishing Image via Telegram

1. User sends image to main bot
2. **Layer 1**: Gemini AI analyzes image for forgery
3. If high-risk → **Send SOS to Guardian** via Guardian Bot
4. Guardian receives alert with evidence
5. System logs threat to Firestore Evidence Vault

### Scenario 2: Browser Detects Scam URL (Chrome Extension)

This scenario prioritizes **speed** so the user's web browsing is never interrupted unless there is a real threat.

1. User clicks or visits a suspicious URL in Chrome.
2. **Instant Scan**: The Chrome Extension instantly queries the Google Web Risk Database (Layer 1).
3. If BLOCKED → The browser immediately stops the page from loading and redirects to `warning.html`.
4. **SOS Alert to Guardian**: The Cloud Backend silently fires a message to the Guardian: *"🚨 LAPTOP SHIELD ALERT: We just blocked your linked user from visiting a dangerous scam website: {url_to_check}"*.

### Scenario 3: User Sends Suspicious Link to Telegram Bot

This scenario prioritizes **deep forensic analysis** when a user actively wants to investigate a link they received in an SMS or WhatsApp message.

1. User pastes a suspicious link directly into the AwasBot Telegram chat.
2. **Layer 1**: Quick check against Google Web Risk (Blacklist check).
3. **Layer 2**: Secondary check against VirusTotal (Crowdsourced engine check).
4. **Layer 3**: System deploys a Playwright Headless Browser to silently visit the site, capture the redirect chain, take a screenshot, and feed the evidence to Gemini AI.
5. **Result**: The bot replies with a comprehensive "AwasBot-AI Forensic Report," including the risk score, a summary of the site's true intentions, and the captured screenshot.

### Scenario 4: High-Risk Bank Transfer

1. User initiates transfer via index.html
2. Google reCAPTCHA Enterprise scores risk
3. If score ≤ 0.3 (CRITICAL):
   - Block transaction immediately
   - Send approval request to Guardian
   - Guardian can **Approve** or **Block** decision
4. User sees real-time status update on portal

### Scenario 5: Device Linking (Magic Link)

1. User receives magic link: `awasbot.com/pair?phone={phone_number}`
2. background.js intercepts the URL
3. Extracts phone number and saves to Chrome storage
4. Redirects to success.html
5. Future URL checks include user's phone number for Guardian alerts

---

## 🔑 Core Functions

### Main Bot (main.py)

| Function | Purpose |
|----------|---------|
| `handle_text_main()` | Route user messages (registration, scanning) |
| `handle_photo()` | Deepfake/forgery detection in images |
| `handle_audio()` | Macau scam + deepfake voice detection |
| `handle_video()` | Video deepfake forensics |
| `check_web_risk()` | Multi-layer URL verification (Layer 1-3) |
| `check_apk()` | Banking malware detection in APK files |
| `check_pdf()` | Phishing document analysis |
| `send_sos()` | Route alerts to linked guardian |

### Guardian Bot

| Function | Purpose |
|----------|---------|
| `process_guardian_bot()` | Handle guardian registrations |
| `handle_guardian_callback()` | Process approve/block decisions |

### Bank Backend

| Function | Purpose |
|----------|---------|
| `handle_bank_webhook()` | Process reCAPTCHA risk scores & send guardian approval requests |
| `handle_check_status()` | Real-time transfer status query |

### Chrome Extension

| Function | Source |
|----------|--------|
| `checkUrlSafety()` | background.js |
| Magic link interceptor | background.js |

---

## 🛡️ Security Architecture

### Multi-Layer Detection Strategy

**URL Verification (3 Layers):**
```
Layer 1: Google Web Risk API (instant block for known malware/phishing)
         ↓
Layer 2: VirusTotal (40+ antivirus engines) if Layer 1 clean
         ↓
Layer 3: Playwright Headless Browser (redirect chains, SSL certs, content)
```

**Media Forensics:**
```
Images:       Digital forgery detection + AI-generated content
Audio:        Deepfake acoustics + Macau scam script detection
Video:        Morphing artifacts + unnatural movements + audio-sync
Documents:    APK permissions + PDF malware + content analysis
```

### Risk Scoring Logic

```
score ≤ 0.3  → 🔴 CRITICAL (Block + Guardian Alert)
0.3 < score ≤ 0.7  → 🟡 SUSPICIOUS (Warn user)
score > 0.7  → 🟢 CLEAN (Allow)
```

---

## 🗄️ Database Schema (Firestore)

### `users` Collection

```json
{
  "chat_id": "123456789",
  "name": "Ahmad Ali",
  "phone": "0123456789",
  "language": "ms",
  "guardian_id": "987654321",
  "state": "MAIN_MENU",
  "transaction_status": "PENDING|APPROVED|BLOCKED"
}
```

### `evidence_vault` Collection

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "reporter_id": "123456789",
  "threat_type": "IMAGE_DEEPFAKE|URL_PHISHING|VOICE_SCAM|APK_MALWARE|PDF_MALWARE|BANK_FRAUD",
  "target": "URL/filename/phone",
  "risk_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "reason": "Detailed threat description"
}
```

---

## 🌐 API Endpoints

### POST `/bank_webhook`

**Request:**
```json
{
  "type": "BANK_WEBHOOK",
  "token": "recaptcha_token",
  "user_phone": "0123456789"
}
```

**Response:**
```json
{
  "status": "received",
  "risk_score": 0.25
}
```

### POST `/check_status`

**Request:**
```json
{
  "phone": "0123456789"
}
```

**Response:**
```json
{
  "status": "PENDING|APPROVED|BLOCKED"
}
```

### POST `/check-url` (Chrome Extension)

**Request:**
```json
{
  "url": "https://malicious-site.com",
  "user_phone": "0123456789"
}
```

**Response:**
```json
{
  "verdict": "BLOCK|ALLOW",
  "is_scam": true
}
```

---

## 📊 Features in Detail

### 🎤 Voice Threat Detection

Detects two attack vectors:

1. **AI Deepfakes** - Unnatural speech patterns, robotic cadence, breath irregularities
2. **Macau Scams** - Impersonations of PDRM (Police), LHDN (Tax), Bank Negara

**Safety**: Defaults to 🟢 CLEAN to avoid false positives on standard Telegram compression.

### 📸 Image Forensics

Identifies:
- Digital forgery & AI-generated images
- Phishing templates (fake bank notifications)
- Forged government IDs

**Safety**: Defaults to 🟢 CLEAN for student IDs, QR codes, natural camera blur.

### 🎥 Video Deepfake Detection

Flags:
- Morphing artifacts
- Unusual facial movements
- Audio-sync mismatches

**Note**: Telegram compression is NOT considered a deepfake signature.

### 📄 Document Scanning

- **APK Files**: Extracts permissions, flags banking trojans (SMS read permissions = red flag)
- **PDF Files**: Detects phishing content, malicious links
- **Other Docs**: VirusTotal scan first, then Gemini analysis

### 🌐 URL Multi-Layer Verification

**Layer 1:** Google Web Risk (instant, trusted sources)  
**Layer 2:** VirusTotal (crowdsourced, 40+ engines)  
**Layer 3:** Playwright forensics (redirects, SSL validity, content analysis)

### 🔗 Browser Device Linking

**Magic Link Flow:**
```
User receives: awasbot.com/pair?phone=0123456789
         ↓
Chrome intercepts in background.js
         ↓
Extracts & saves phone to Chrome storage
         ↓
Shows success.html confirmation
         ↓
All future URL checks now include phone number
         ↓
Guardian gets alerts tied to this device
```

---

## 🔐 Privacy & Compliance

✅ **No personal data transmission** (phone numbers used for linking only)  
✅ **Firestore encryption** at rest   
✅ **Evidence vault** for legal compliance & incident review  
✅ **Guardian consent** required before linking  

---

## 🚨 Threat Examples Detected

| Threat | Detection | File |
|--------|-----------|------|
| Fake Maybank login | URL forensics + content | main.py - `check_web_risk()` |
| DHL phishing SMS link | Google Web Risk + VirusTotal | main.py - `check_web_risk()` |
| Macau police scam voice | Audio deepfake + script detection | main.py - `handle_audio()` |
| Banking trojan APK | Permission scanner + VirusTotal | main.py - `check_apk()` |
| Forged government letter | Image forensics + AI analysis | main.py - `handle_photo()` |
| Deepfake video | Artifact detection + morphing check | main.py - `handle_video()` |
| High-risk bank transfer | reCAPTCHA Enterprise scoring | index.html - `executeTransfer()` |
| Malicious website | Browser URL interception | background.js - `checkUrlSafety()` |

---

## 🛠️ Development & Testing

### Chrome Extension Testing

1. Open `chrome://extensions/`
2. Enable **Developer Mode**
3. Click **Load unpacked** → select chrome-extension folder
4. Visit a test URL to verify blocking works
5. Check URLs in warning.html warning

### Manual API Testing

```bash
# Test bank webhook
curl -X POST https://your-cloud-run-url/bank_webhook \
  -H "Content-Type: application/json" \
  -d '{
    "type": "BANK_WEBHOOK",
    "token": "test_token",
    "user_phone": "0123456789"
  }'

# Test URL check
curl -X POST https://your-cloud-run-url/check-url \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "user_phone": "0123456789"
  }'
```

---

## 📈 Deployment Checklist

### Before Production

- [ ] All `.env` variables set in Cloud Run
- [ ] Firestore database created with `users` & `evidence_vault` collections
- [ ] Telegram webhooks configured & tested with `/start` command
- [ ] reCAPTCHA Enterprise keys verified in index.html
- [ ] Chrome extension API endpoint updated in background.js
- [ ] Bank portal Cloud Run URL updated in index.html
- [ ] Test end-to-end: Telegram registration → Image scan → Guardian SOS
- [ ] Test browser flow: Device linking via magic link → Guardian alerts
- [ ] Test bank portal: reCAPTCHA trigger → Guardian approval workflow
- [ ] Enable Cloud Logging for debugging
- [ ] Set up error alerting (Cloud Monitoring)

### Scaling Considerations

- **Firestore**: Auto-scales globally (no database maintenance needed).
- **Cloud Run**: Auto-scales based on concurrent requests; set `--memory=2Gi` minimum to support the Playwright headless browser.
- **Playwright**: Memory-intensive during deep forensic URL scans. If concurrent user URL scans increase, consider bumping Cloud Run memory to `--memory=4Gi`.
- **Gemini API**: The free tier handles 15 requests/minute and 1,500 requests/day. For a production rollout, a paid Google Cloud project is required to handle high-volume media processing.
- **VirusTotal**: The free public API is strictly limited to 4 requests/minute. A premium enterprise key is required for live production traffic.

---

## 📚 Documentation References

- [Google Gemini API Docs](https://ai.google.dev)
- [Google Web Risk API](https://cloud.google.com/web-risk/docs)
- [VirusTotal API](https://docs.virustotal.com/reference)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Playwright Python](https://playwright.dev/python)
- [Firebase Admin SDK](https://firebase.google.com/docs/admin/setup)
- [Google Cloud Run](https://cloud.google.com/run/docs)
- [reCAPTCHA Enterprise](https://cloud.google.com/recaptcha-enterprise/docs)

---

## 🎓 Learning Path

1. **Start Here**: Read this README
2. **Understand Backend**: Review `main.py` in this order:
   - Configuration & API Setup
   - Traffic controller logic
   - Guardian bot workflow
   - AI scanners (Gemini & Web Risk)
   - Bank webhooks & reCAPTCHA validation
3. **Understand Frontend**: Review `index.html` reCAPTCHA flow
4. **Understand Extension**: Review `background.js` interception logic
5. **Deploy to Cloud**: Set up `.env` and push code directly to Google Cloud Run
6. **Configure Clients**: Update bank portal API URLs + Chrome extension host permissions
7. **Go Live**: Enable Telegram webhooks and monitor Cloud Logs

---

## 🌟 Key Innovation

AwasBot's unique strength is the **Three-Layer Guardian System**:

**Layer 1: Real-Time Threat Interception**
```
User scans media/URL → AI detects threat → Block immediately
```

**Layer 2: Family Guardian SOS**
```
Threat detected → Guardian gets alert with evidence → Guardian reviews
```

**Layer 3: Financial Approval Workflow**
```
High-risk transfer → Block transaction → Guardian sees approval request → 
Guardian clicks Approve/Block → Decision stored in Firestore → 
User sees real-time status on portal
```

This human-in-the-loop approach prevents financial losses while respecting user autonomy. No automatic blocking—families stay connected and informed.

---

## 🚀 Future Roadmap 

While AwasBot currently provides a robust MVP, our vision for a full production rollout includes:

1. **📱 WhatsApp Integration**: Migrating the Telegram bot logic to the WhatsApp Business API, matching the primary communication channel for Southeast Asian senior citizens.
2. **🏦 Open Banking Integration**: Moving beyond the mock portal to integrate directly with real banking APIs (in compliance with Bank Negara Malaysia guidelines) for automated fund freezing.
3. **🍏 Mobile Safari Extension**: Porting the Chrome Extension logic to iOS Safari to protect elderly users who primarily browse the web on iPhones and iPads.
4. **📊 Guardian Dashboard**: Building a centralized web app where family members can view weekly analytics of threats blocked across all connected devices.

---

**Made with 🛡️ for Southeast Asian Financial Security**


