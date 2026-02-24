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

# --- DUPLICATE PREVENTION CACHE ---
# Keeps track of messages already being processed to prevent loops
processed_updates = set()

# CRITICAL WINDOWS FIX FOR PLAYWRIGHT 
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

# --- HELPERS ---
def get_api_url(is_guardian=False):
    token = TELEGRAM_TOKEN_GUARDIAN if is_guardian else TELEGRAM_TOKEN_MAIN
    return f"https://api.telegram.org/bot{token}"

def send_reply(chat_id, text, is_guardian=False, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        session.post(f"{get_api_url(is_guardian)}/sendMessage", json=payload)
    except Exception as e:
        print(f"Error sending message: {e}")

def get_user_data(chat_id):
    doc = db.collection('users').document(str(chat_id)).get()
    return doc.to_dict() if doc.exists else {}

# ==========================================
# 🚀 ENTRY POINT: THE TRAFFIC CONTROLLER
# ==========================================
@functions_framework.http
def telegram_webhook(request):
    # Handle CORS for the Bank Website
    if request.method == 'OPTIONS':
        return ('', 204, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type'
        })

    data = request.get_json(silent=True)
    if not data:
        return (jsonify({'status': 'no data'}), 200)

    # 🛑 THE LOOP KILLER: Check if this Update ID was already seen
    update_id = data.get("update_id")
    if update_id:
        if update_id in processed_updates:
            print(f"Skipping duplicate update: {update_id}")
            return (jsonify({'status': 'duplicate ignored'}), 200)
        processed_updates.add(update_id)
        # Keep cache small (last 100 updates)
        if len(processed_updates) > 100:
            processed_updates.remove(next(iter(processed_updates)))

    path = request.path
    headers = {'Access-Control-Allow-Origin': '*'}

    # 1. Bank Website Requests (Always immediate)
    if path == "/bank_webhook":
        return handle_bank_webhook(data, headers)

    # 2. Telegram Bot Requests (Start Thread + Return 200 OK immediately)
    if path == "/guardianbot" or "callback_query" in data:
        target_func = process_guardian_logic
    else:
        target_func = process_main_bot_logic

    # START BACKGROUND THREAD
    threading.Thread(target=target_func, args=(data,)).start()

    # RETURN IMMEDIATELY SO TELEGRAM DOESN'T RETRY
    return (jsonify({'status': 'acknowledged'}), 200, headers)

# ==========================================
# 🛡️ GUARDIAN BOT LOGIC (In Thread)
# ==========================================
def process_guardian_logic(data):
    # Handle Button Clicks (Approve/Block)
    if "callback_query" in data:
        cb = data["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        action_data = cb["data"] # e.g., "approve_012345"
        
        status = "✅ APPROVED" if "approve" in action_data else "🛑 BLOCKED"
        new_text = f"**Decision Logged:** {status}\n━━━━━━━━━━━━━━━━━━━━━\nAction taken by Digital Sahabat."
        
        # Edit the message to show the result
        session.post(f"{get_api_url(True)}/editMessageText", json={
            "chat_id": chat_id, "message_id": msg_id, "text": new_text, "parse_mode": "Markdown"
        })
        return

    # Handle /start
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    if msg.get("text") == "/start":
        send_reply(chat_id, f"🛡️ **Guardian Active**\nYour ID: `{chat_id}`\nGive this to the person you are protecting.", is_guardian=True)

# ==========================================
# 🔍 MAIN BOT LOGIC (In Thread)
# ==========================================
def process_main_bot_logic(data):
    msg = data.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id: return

    text = msg.get("text", "")

    # Registration Flow
    if text == "/start":
        db.collection('users').document(str(chat_id)).set({"state": "START"}, merge=True)
        send_reply(chat_id, "Welcome to **AwasBot**. \nWhat is your name?")
        return

    # Heavy AI Analysis (Example: URL Scan)
    if "http" in text:
        send_reply(chat_id, "🔍 *Triple-Layer Scan in progress...*")
        # Simulate heavy work
        time.sleep(2) 
        send_reply(chat_id, "✅ URL Scan Complete: **Low Risk**")

# ==========================================
# 🏦 BANK WEBHOOK (Direct response)
# ==========================================
def handle_bank_webhook(data, headers):
    search_phone = data.get("user_phone", "").replace(" ", "").replace("+60", "0")
    
    # Find the linked Guardian in Firestore
    query = db.collection('users').where('phone', '==', search_phone).stream()
    
    found = False
    for doc in query:
        found = True
        u = doc.to_dict()
        g_id = u.get("guardian_id")
        if g_id:
            msg = f"🚨 **SOS: BANK FRAUD DETECTED**\n━━━━━━━━━━━━━━━━━━━━━\n**User:** {u.get('name')}\n**Phone:** {search_phone}\n**Status:** Frozen\n\nApprove this transfer?"
            markup = {"inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve_{search_phone}"},
                {"text": "❌ Block", "callback_data": f"block_{search_phone}"}
            ]]}
            send_reply(g_id, msg, is_guardian=True, reply_markup=markup)
    
    return (jsonify({"sent": found}), 200, headers)