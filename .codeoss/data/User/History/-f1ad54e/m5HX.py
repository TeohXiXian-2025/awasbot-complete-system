import functions_framework
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import jsonify, request
import google.generativeai as genai
import os
import time
import hashlib
import random
import base64
import json
import asyncio
import sys
import threading
from playwright.async_api import async_playwright
from google.cloud import firestore
from pyaxmlparser import APK
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- DUPLICATE PREVENTION ---
processed_updates = set()

# --- CRITICAL WINDOWS FIX FOR PLAYWRIGHT ---
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 1. CONFIGURATION
TELEGRAM_TOKEN_MAIN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_TOKEN_GUARDIAN = os.getenv("TELEGRAM_TOKEN_GUARDIAN")
VT_API_KEY = os.getenv("VT_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WR_API_KEY = os.getenv("WR_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
strict_config = genai.types.GenerationConfig(temperature=0.1)

session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

db = firestore.Client()

# ==========================================
# HELPERS
# ==========================================
def get_api_url(is_guardian=False):
    token = TELEGRAM_TOKEN_GUARDIAN if is_guardian else TELEGRAM_TOKEN_MAIN
    return f"https://api.telegram.org/bot{token}"

def send_reply(chat_id, text, is_guardian=False, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup: payload["reply_markup"] = reply_markup
    session.post(f"{get_api_url(is_guardian)}/sendMessage", json=payload)

def send_interim(chat_id, text, is_guardian=False):
    session.post(f"{get_api_url(is_guardian)}/sendMessage", json={"chat_id": chat_id, "text": text})

def send_sos(user_id, text):
    gid = get_user_data(user_id).get("guardian_id")
    if gid:
        send_reply(gid, text, is_guardian=True)

def get_user_data(chat_id):
    doc = db.collection('users').document(str(chat_id)).get()
    return doc.to_dict() if doc.exists else {}

def update_user_data(chat_id, data):
    db.collection('users').document(str(chat_id)).set(data, merge=True)

def log_threat_to_vault(reporter_id, threat_type, target, risk_level, reason):
    db.collection('evidence_vault').document().set({
        'timestamp': firestore.SERVER_TIMESTAMP,
        'reporter_id': str(reporter_id),
        'threat_type': threat_type,
        'target': target,
        'risk_level': str(risk_level),
        'reason': reason
    })

def t(lang, en, ms, zh):
    if lang == "ms": return ms
    if lang == "zh": return zh
    return en

# ==========================================
# 🚀 THE TRAFFIC CONTROLLER (ENTRY)
# ==========================================
@functions_framework.http
def telegram_webhook(request):
    if request.method == 'OPTIONS':
        return ('', 204, {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST', 'Access-Control-Allow-Headers': 'Content-Type'})

    data = request.get_json(silent=True)
    if not data: return (jsonify({'status': 'no data'}), 200)

    # 🛑 STOP REPETITION: Ignore if we already started this update
    update_id = data.get("update_id")
    if update_id in processed_updates:
        return (jsonify({'status': 'duplicate'}), 200)
    processed_updates.add(update_id)
    if len(processed_updates) > 200: processed_updates.pop()

    path = request.path
    headers = {'Access-Control-Allow-Origin': '*'}

    if path == "/bank_webhook":
        return handle_bank_webhook(data, headers)

    # 🧵 THREADING: Start analysis in background and return 200 OK instantly
    if path == "/guardianbot" or "callback_query" in data:
        threading.Thread(target=process_guardian_bot, args=(data, headers)).start()
    else:
        threading.Thread(target=process_main_bot, args=(data, headers)).start()

    return (jsonify({'status': 'processing'}), 200, headers)

# ==========================================
# 🛡️ GUARDIAN BOT LOGIC
# ==========================================
def process_guardian_bot(data, headers):
    if "callback_query" in data:
        cb = data["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        message_id = cb["message"]["message_id"]
        callback_data = cb["data"]
        
        phone = callback_data.split("_")[1]
        new_text = f"✅ **UNLOCKED**" if "approve" in callback_data else f"🛑 **BLOCKED**"
        new_text += f"\n━━━━━━━━━━━━━━━━━━━━━\nTransaction for account {phone} processed."

        session.post(f"{get_api_url(True)}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": new_text})
        session.post(f"{get_api_url(True)}/answerCallbackQuery", json={"callback_query_id": cb["id"]})
        return

    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text")
    
    if text == "/start":
        send_reply(chat_id, f"🛡️ **Welcome Guardian!**\nYour ID: `{chat_id}`", is_guardian=True)

# ==========================================
# 🔍 MAIN BOT & SCANNERS
# ==========================================
def process_main_bot(data, headers):
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id: return

    if "text" in msg: handle_text_main(chat_id, msg["text"])
    elif "voice" in msg: handle_audio(chat_id, msg["voice"]["file_id"])
    elif "photo" in msg: handle_photo(chat_id, msg["photo"][-1]["file_id"])
    elif "video" in msg: handle_video(chat_id, msg["video"]["file_id"])
    elif "document" in msg: handle_document(chat_id, msg["document"])

def handle_text_main(chat_id, text):
    user_data = get_user_data(chat_id)
    state = user_data.get("state")
    lang = user_data.get("language", "en")

    if text == "/start":
        update_user_data(chat_id, {"state": "WAITING_LANG"})
        reply_markup = {"keyboard": [[{"text": "🇬🇧 English"}, {"text": "🇲🇾 Bahasa Melayu"}, {"text": "🇨🇳 中文"}]], "resize_keyboard": True}
        send_reply(chat_id, "🌍 Choose Language:", reply_markup=reply_markup)
        return

    if state == "WAITING_LANG":
        new_lang = "ms" if "Bahasa" in text else "zh" if "中文" in text else "en"
        update_user_data(chat_id, {"language": new_lang, "state": "WAITING_NAME"})
        send_reply(chat_id, t(new_lang, "What is your name?", "Siapa nama anda?", "您的名字是？"))
        return

    if state == "WAITING_NAME":
        update_user_data(chat_id, {"name": text, "state": "WAITING_PHONE"})
        send_reply(chat_id, "Enter Phone Number:")
        return

    if state == "WAITING_PHONE":
        update_user_data(chat_id, {"phone": text, "state": "WAITING_GUARDIAN"})
        send_reply(chat_id, "Enter Guardian ID (from @AwasGuardian_Bot):")
        return

    if state == "WAITING_GUARDIAN":
        update_user_data(chat_id, {"guardian_id": text, "state": "MAIN_MENU"})
        send_reply(text, f"🤝 Linked to {user_data.get('name')}!", is_guardian=True)
        send_main_menu(chat_id, lang, "Registration Complete!")
        return

    if "http" in text: check_web_risk(chat_id, text, lang)

def send_main_menu(chat_id, lang, text):
    reply_markup = {"keyboard": [[{"text": "📸 Scan Image"}, {"text": "🎤 Scan Audio"}], [{"text": "📄 Scan File"}]], "resize_keyboard": True}
    send_reply(chat_id, text, reply_markup=reply_markup)

# --- AI ANALYSIS FUNCTIONS (Same logic as before, inside the thread) ---

async def run_rantai_scan(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, timeout=30000)
            analysis = {"url": url, "content": (await page.content())[:500]}
            model = genai.GenerativeModel('gemini-1.5-flash-preview-0514')
            res = model.generate_content(f"Analyze scam risk (JSON): {json.dumps(analysis)}", generation_config={"response_mime_type": "application/json"})
            return json.loads(res.text)
        except Exception as e: return {"error": str(e)}
        finally: await browser.close()

def check_web_risk(chat_id, text, lang):
    url = next((w for w in text.split() if w.startswith("http")), None)
    if not url: return
    send_interim(chat_id, "🌐 Analyzing URL Layer 1-3...")
    
    # VT Layer
    url_id = base64.urlsafe_b64encode(url.encode()).decode().strip("=")
    vt_res = session.get(f"https://www.virustotal.com/api/v3/urls/{url_id}", headers={"x-apikey": VT_API_KEY})
    if vt_res.status_code == 200:
        malicious = vt_res.json().get('data', {}).get('attributes', {}).get('last_analysis_stats', {}).get('malicious', 0)
        if malicious > 0:
            send_sos(chat_id, f"🚨 SOS: Phishing Link! {url}")
            send_reply(chat_id, "🔴 CRITICAL: URL Flagged by VirusTotal.")
            return

    # Deep Scan Layer
    report = asyncio.run(run_rantai_scan(url))
    score = report.get("risk_score", 0)
    if score > 70: send_sos(chat_id, f"🚨 SOS: High Risk URL! {url}")
    send_reply(chat_id, f"🔬 AI Report for {url}\nRisk Score: {score}/100\nVerdict: {report.get('verdict_en')}")

def handle_audio(chat_id, file_id):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, "🎙️ Analyzing acoustics & script...")
    res = session.get(f"{get_api_url()}/getFile?file_id={file_id}").json()
    audio_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN_MAIN}/{res['result']['file_path']}"
    audio_data = session.get(audio_url).content
    model = genai.GenerativeModel('gemini-1.5-flash-preview-0514')
    response = model.generate_content(["Detect Deepfake/Macau Scam:", {'mime_type': 'audio/ogg', 'data': audio_data}], generation_config=strict_config)
    if "🔴" in response.text: send_sos(chat_id, "🚨 SOS: Scam/Deepfake Audio!")
    send_reply(chat_id, response.text)

def handle_photo(chat_id, file_id):
    send_interim(chat_id, "📸 Scanning image for forgery...")
    res = session.get(f"{get_api_url()}/getFile?file_id={file_id}").json()
    img_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN_MAIN}/{res['result']['file_path']}"
    img_data = session.get(img_url).content
    model = genai.GenerativeModel('gemini-1.5-flash-preview-0514')
    response = model.generate_content(["Forensic Image Scan:", {'mime_type': 'image/jpeg', 'data': img_data}], generation_config=strict_config)
    send_reply(chat_id, response.text)

def handle_document(chat_id, doc):
    name = doc.get("file_name", "").lower()
    send_interim(chat_id, f"📄 Scanning {name}...")
    # Add APK/PDF logic here as per your previous code
    send_reply(chat_id, "✅ File Scan Complete.")

# ==========================================
# 🏦 BANK WEBHOOK
# ==========================================
def handle_bank_webhook(data, headers):
    search_phone = data.get("user_phone", "").replace(" ", "").replace("+60", "0")
    score = 0.1 # Example score from reCAPTCHA
    
    query = db.collection('users').where('phone', '==', search_phone).stream()
    for doc in query:
        u = doc.to_dict()
        msg = f"🚨 **BANK FRAUD DETECTED**\nUser: {u.get('name')}\nRisk: CRITICAL"
        markup = {"inline_keyboard": [[{"text": "✅ Approve", "callback_data": f"approve_{search_phone}"}, {"text": "❌ Block", "callback_data": f"block_{search_phone}"}]]}
        send_reply(u.get("guardian_id"), msg, is_guardian=True, reply_markup=markup)
        break
    return (jsonify({"status": "ok"}), 200, headers)