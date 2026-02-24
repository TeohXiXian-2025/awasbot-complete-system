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
from playwright.async_api import async_playwright
from google.cloud import firestore
from pyaxmlparser import APK
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# CRITICAL WINDOWS FIX FOR PLAYWRIGHT 
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 1. CONFIGURATION 

# Keys pulled dynamically from the secure environment
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

# Initialize Permanent Database
db = firestore.Client()

# HELPER: DYNAMIC API URLS
def get_api_url(is_guardian=False):
    token = TELEGRAM_TOKEN_GUARDIAN if is_guardian else TELEGRAM_TOKEN_MAIN
    return f"https://api.telegram.org/bot{token}"

def send_reply(chat_id, text, is_guardian=False, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup: payload["reply_markup"] = reply_markup
    session.post(f"{get_api_url(is_guardian)}/sendMessage", json=payload)

def send_interim(chat_id, text, is_guardian=False):
    session.post(f"{get_api_url(is_guardian)}/sendMessage", json={"chat_id": chat_id, "text": text})

def send_sos(user_id, text, override_gid=None):
    # SOS ALERTS GO THROUGH GUARDIAN BOT!
    gid = override_gid or get_user_data(user_id).get("guardian_id")
    if gid:
        send_reply(gid, text, is_guardian=True)

# DATABASE & VAULT HELPERS 
def get_user_data(chat_id):
    doc = db.collection('users').document(str(chat_id)).get()
    return doc.to_dict() if doc.exists else {}

def update_user_data(chat_id, data):
    db.collection('users').document(str(chat_id)).set(data, merge=True)

def log_threat_to_vault(reporter_id, threat_type, target, risk_level, reason):
    try:
        doc_ref = db.collection('evidence_vault').document()
        doc_ref.set({
            'timestamp': firestore.SERVER_TIMESTAMP,
            'reporter_id': str(reporter_id),
            'threat_type': threat_type,
            'target': target,
            'risk_level': str(risk_level),
            'reason': reason
        })
    except Exception as e: print(f"⚠️ Vault Error: {e}")

def t(lang, en_text, ms_text, zh_text):
    if lang == "ms": return ms_text
    if lang == "zh": return zh_text
    return en_text

def get_lang_append(lang):
    if lang == "ms": return "\n\n(IMPORTANT: Translate your final response entirely to Bahasa Melayu, including the template headers.)"
    if lang == "zh": return "\n\n(IMPORTANT: Translate your final response entirely to Chinese, including the template headers.)"
    return ""

def get_disclaimer(lang):
    return t(lang, 
             "\n\n⚠️ *Reminder: AI can make mistakes. Please double-check and stay vigilant.*", 
             "\n\n⚠️ *Peringatan: AI mungkin melakukan kesilapan. Sila semak semula dan kekal berwaspada.*", 
             "\n\n⚠️ *提醒：AI 可能会出错。请务必再次核实并保持警惕。*")

#  THE TRAFFIC CONTROLLER (MAIN ENTRY)
@functions_framework.http
def telegram_webhook(request):
    # CORS for Bank
    if request.method == 'OPTIONS':
        headers = {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST', 'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '3600'}
        return ('', 204, headers)

    headers = {'Access-Control-Allow-Origin': '*'}
    data = request.get_json(silent=True)
    if not data: return (jsonify({'status': 'no data'}), 200, headers)

    # Traffic Routing based on the URL path
    path = request.path

    if path == "/bank_webhook" or data.get("type") == "BANK_WEBHOOK":
        return handle_bank_webhook(data, headers)

    elif path == "/guardianbot":
        return process_guardian_bot(data, headers)

    elif path == "/mainbot" or path == "/": # Default to main bot
        return process_main_bot(data, headers)

    return jsonify({'status': 'ok'}), 200

#  THE GUARDIAN BOT LOGIC
def process_guardian_bot(data, headers):
    if "callback_query" in data:
        return handle_guardian_callback(data["callback_query"], headers)
    
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"]
        
        if text == "/start":
            msg = (
                "🛡️ **Welcome to AwasGuardian!**\n\n"
                "You are now acting as a Digital Sahabat (Guardian).\n"
                "You will receive SOS alerts here if your linked user encounters high-risk scams or flagged bank transfers.\n\n"
                f"Your Guardian ID to give them is: `{chat_id}`"
            )
            
            # Simple Guardian Menu
            reply_markup = {"keyboard": [[{"text": "📊 View Protected Status"}]], "resize_keyboard": True}
            send_reply(chat_id, msg, is_guardian=True, reply_markup=reply_markup)
            
        elif text == "📊 View Protected Status":
            # Find users who have this person as a guardian
            users_ref = db.collection('users')
            query = users_ref.where('guardian_id', '==', str(chat_id)).stream()
            protected_users = [doc.to_dict().get('name', 'Unknown') for doc in query]
            
            if protected_users:
                send_reply(chat_id, f"✅ You are actively protecting: {', '.join(protected_users)}", is_guardian=True)
            else:
                send_reply(chat_id, f"ℹ️ You are not protecting anyone yet. Give them your ID: `{chat_id}`", is_guardian=True)

    return jsonify({'status': 'ok'}), 200

def handle_guardian_callback(callback_query, headers):
    cb_id = callback_query["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]
    callback_data = callback_query["data"]
    
    if callback_data.startswith("approve_"):
        phone = callback_data.split("_")[1]
        new_text = f"✅ **TRANSACTION UNLOCKED**\n━━━━━━━━━━━━━━━━━━━━━\nThe funds for account {phone} have been securely released to the merchant. The Bank has been notified."
    elif callback_data.startswith("block_"):
        phone = callback_data.split("_")[1]
        new_text = f"🛑 **TRANSACTION BLOCKED**\n━━━━━━━━━━━━━━━━━━━━━\nThe funds for account {phone} remain frozen. AwasBot has flagged the destination account for review."
    else:
        new_text = "Action processed."

    # Update original message and clear loading state using Guardian Token
    session.post(f"{get_api_url(is_guardian=True)}/editMessageText", json={"chat_id": chat_id, "message_id": message_id, "text": new_text})
    session.post(f"{get_api_url(is_guardian=True)}/answerCallbackQuery", json={"callback_query_id": cb_id})
    
    return (jsonify({'status': 'ok'}), 200, headers)

# 🔍 THE MAIN BOT LOGIC (SCANNERS)
def process_main_bot(data, headers):
    if "message" not in data: return (jsonify({'status': 'ok'}), 200, headers)
    
    chat_id = data["message"]["chat"]["id"]
    msg = data["message"]
    
    try:
        if "text" in msg: handle_text_main(chat_id, msg["text"])
        elif "voice" in msg: handle_audio(chat_id, msg["voice"]["file_id"])
        elif "photo" in msg: handle_photo(chat_id, msg["photo"][-1]["file_id"])
        elif "video" in msg: handle_video(chat_id, msg["video"]["file_id"])
        elif "document" in msg: handle_document(chat_id, msg["document"])
    except Exception as e:
        lang = get_user_data(chat_id).get("language", "en")
        send_reply(chat_id, t(lang, f"⚠️ SYSTEM ERROR: {str(e)}", f"⚠️ RALAT SISTEM: {str(e)}", f"⚠️ 系统错误: {str(e)}"))

    return jsonify({'status': 'ok'}), 200

def handle_text_main(chat_id, text):
    user_data = get_user_data(chat_id)
    state = user_data.get("state")
    lang = user_data.get("language", "en")
    name = user_data.get("name")
    guardian_id = user_data.get("guardian_id")

    if text == "/start" or text in ["🌍 Change Language", "🌍 Tukar Bahasa", "🌍 更改语言"]:
        update_user_data(chat_id, {"state": "WAITING_LANG"})
        reply_markup = {"keyboard": [[{"text": "🇬🇧 English"}, {"text": "🇲🇾 Bahasa Melayu"}, {"text": "🇨🇳 中文"}]], "resize_keyboard": True}
        send_reply(chat_id, "🌍 Please choose your language / Sila pilih bahasa anda / 请选择您的语言:", reply_markup=reply_markup)
        return

    if state == "WAITING_LANG":
        new_lang = "ms" if "Bahasa" in text else "zh" if "中文" in text else "en"
        update_user_data(chat_id, {"language": new_lang, "state": "WAITING_NAME"})
        send_reply(chat_id, t(new_lang, "🛡️ **Welcome to AwasBot!**\nWhat should I refer to you as?", "🛡️ **Selamat Datang ke AwasBot!**\nApakah nama panggilan anda?", "🛡️ **欢迎使用 AwasBot！**\n我该怎么称呼您？"))
        return

    if state == "WAITING_NAME":
        update_user_data(chat_id, {"name": text, "state": "WAITING_PHONE"})
        send_reply(chat_id, t(lang, 
            f"Nice to meet you, {text}! 👋\n\nNext, please enter your **Phone Number** (e.g., 0123456789).", 
            f"Selamat berkenalan, {text}! 👋\n\nSeterusnya, sila masukkan **Nombor Telefon** anda.", 
            f"很高兴认识您，{text}！👋\n\n接下来，请输入您的**手机号码**。"))
        return

    if state == "WAITING_PHONE":
        phone_clean = text.replace(" ", "").replace("+60", "0")
        update_user_data(chat_id, {"phone": phone_clean, "state": "WAITING_GUARDIAN"})
        send_reply(chat_id, t(lang, 
            f"✅ Phone linked: {phone_clean}.\n\nFinally, ask your Guardian to open **@AwasGuardian_Bot**, click Start, and send you their 9-digit Guardian ID.", 
            f"✅ Telefon dipautkan.\n\nAkhir sekali, minta Penjaga anda buka **@AwasGuardian_Bot**, tekan Start, dan hantar ID Penjaga mereka.", 
            f"✅ 手机已绑定。\n\n最后，请您的守护者打开 **@AwasGuardian_Bot**，点击开始，并将他们的 守护者 ID 发送给您。"))
        return

    if state == "WAITING_GUARDIAN":
        if text.lstrip('-').isdigit():  
            update_user_data(chat_id, {"guardian_id": text, "state": "MAIN_MENU"})
            # Alert the Guardian Bot!
            send_reply(text, f"🤝 **DIGITAL SAHABAT LINKED**: You are now the active guardian for {name}.", is_guardian=True)
            send_main_menu(chat_id, lang, t(lang, f"✅ Registration Complete, {name}!", f"✅ Pendaftaran Selesai, {name}!", f"✅ 注册完成, {name}！"))
        else:
            send_reply(chat_id, "⚠️ Invalid ID. Please enter a numeric Guardian ID.")
        return

    # Button Handlers
    if text in ["📸 Scan Image", "📸 Imbas Gambar", "📸 扫描图片"]:
        send_reply(chat_id, t(lang, "📸 Please upload the Image.", "📸 Sila muat naik Gambar.", "📸 请上传图片。"))
    elif text in ["🎤 Scan Audio", "🎤 Imbas Audio", "🎤 扫描语音"]:
        send_reply(chat_id, t(lang, "🎤 Please record Voice Note.", "🎤 Sila rakam Nota Suara.", "🎤 请录制语音。"))
    elif text in ["🎥 Scan Video", "🎥 Imbas Video", "🎥 扫描视频"]:
        send_reply(chat_id, t(lang, "🎥 Please upload Video.", "🎥 Sila muat naik Video.", "🎥 请上传视频。"))
    elif text in ["📄 Scan File", "📄 Imbas Fail", "📄 扫描文件"]:
        send_reply(chat_id, t(lang, "📄 Please upload the Document (PDF, APK).", "📄 Sila muat naik Dokumen (PDF, APK).", "📄 请上传文档 (PDF, APK)。"))
    elif "http" in text:
        check_web_risk(chat_id, text, lang)
    else:
        if name and guardian_id:
            send_main_menu(chat_id, lang, t(lang, "Please use the buttons below, or paste a link.", "Sila gunakan butang di bawah, atau tampal pautan.", "请使用下方按钮，或直接粘贴链接。"))

def send_main_menu(chat_id, lang, text_message):
    reply_markup = {
        "keyboard": [
            [{"text": t(lang, "📸 Scan Image", "📸 Imbas Gambar", "📸 扫描图片")}, {"text": t(lang, "🎤 Scan Audio", "🎤 Imbas Audio", "🎤 扫描语音")}],
            [{"text": t(lang, "🎥 Scan Video", "🎥 Imbas Video", "🎥 扫描视频")}, {"text": t(lang, "📄 Scan File", "📄 Imbas Fail", "📄 扫描文件")}],
            [{"text": t(lang, "🌍 Change Language", "🌍 Tukar Bahasa", "🌍 更改语言")}]
        ],
        "resize_keyboard": True
    }
    send_reply(chat_id, text_message, reply_markup=reply_markup)

# 3. AI SCANNERS

URL_SYSTEM_PROMPT = """
Act as a Senior Forensic Web Security Analyst. Detect scams mimicking brands like Maybank, DHL, or Shopee.
Analyze network DNA, redirects, and content. Respond strictly in JSON:
{
  "risk_score": (0-100),
  "summary": "Professional summary.",
  "captured_threats": ["List specifically identified red flags"],
  "verdict_en": "1-sentence final recommendation."
}
"""

async def run_rantai_headless_scan(url):
    print(f"🕵️‍♂️ Rantai-AI: Starting deep scan on: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        redirect_chain = []
        page.on("framenavigated", lambda frame: redirect_chain.append(frame.url))
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            security_info = await response.security_details() if response else None
            evidence_path = f"evidence_{int(time.time())}.png"
            await page.screenshot(path=evidence_path)
            analysis_payload = {"url": url, "redirects": redirect_chain, "issuer": security_info.get("issuer", "Unknown") if security_info else "Unknown", "content_snippet": (await page.content())[:500]}
            model = genai.GenerativeModel(model_name='gemini-3-flash-preview', system_instruction=URL_SYSTEM_PROMPT)
            gemini_result = model.generate_content(f"Judge this site behavior: {json.dumps(analysis_payload)}", generation_config=genai.types.GenerationConfig(temperature=0.1, response_mime_type="application/json"))
            raw_text = gemini_result.text.strip()
            if raw_text.startswith("```json"): raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif raw_text.startswith("```"): raw_text = raw_text.split("```")[1].split("```")[0].strip()
            return json.loads(raw_text), evidence_path
        except Exception as e: return {"error": str(e)}, None
        finally: await browser.close()


def get_telegram_file(file_id):
    """Helper to download files using the MAIN bot token"""
    res = session.get(f"{get_api_url(False)}/getFile?file_id={file_id}").json()
    return f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN_MAIN}/{res['result']['file_path']}"


def handle_audio(chat_id, file_id):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, t(lang, "🎙️ **[Analysis]** Analyzing acoustics for Deepfakes and scanning script for Macau Scams...", "🎙️ **[Analisis]** Menganalisis akustik untuk Deepfake dan menyemak skrip...", "🎙️ **[分析]** 正在分析深度伪造声学并扫描澳门骗局脚本..."))
    
    url = get_telegram_file(file_id)
    audio_data = session.get(url).content
    model = genai.GenerativeModel('gemini-3-flash-preview')
    prompt = (
        "You are a Dual-Threat Forensic Audio Analyst. Analyze this recording for BOTH AI Deepfake signatures AND Social Engineering/Macau Scam scripts.\n\n"
        "THREAT 1: AI DEEPFAKES (Acoustics)\n- Listen for unnatural breath patterns, robotic cadence.\n- Note: Telegram compresses audio. Do not flag standard digital 'crunchiness' as AI.\n\n"
        "THREAT 2: MACAU SCAMS (Content & Script)\n- Flag impersonations of authorities (e.g., PDRM/Police, LHDN/Tax, Customs, Bank Negara).\n- Flag pressure tactics, threats of arrest, or demands for money/TAC codes.\n\n"
        "DECISION LOGIC:\n- Output '🔴' (CRITICAL RISK) if it is an obvious AI Deepfake OR a clear scam script.\n- Output '🟡' (SUSPICIOUS) if audio is heavily distorted or conversation is highly unusual.\n- Output '🟢' (CLEAN) for normal conversations.\n\n"
        "Format your reply EXACTLY using this template:\n\n"
        "[🔴, 🟡, or 🟢] **THREAT REPORT: [CRITICAL RISK, SUSPICIOUS, or CLEAN]**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** Audio Recording\n**Status:** [AI Deepfake, Scam Script Detected, Suspicious, or Safe]\n**Reason:** [Brief explanation combining acoustic and content findings]\n**Action:** [Advice to the user]"
    )
    response = model.generate_content([prompt + get_lang_append(lang), {'mime_type': 'audio/ogg', 'data': audio_data}], generation_config=strict_config)
    if "🔴" in response.text:
        send_sos(chat_id, t(lang, "🚨 SOS: User received a Critical Voice Threat (Deepfake or Scam Script)!", "🚨 SOS: Pengguna menerima Ancaman Suara Kritikal!", "🚨 SOS: 用户收到严重语音威胁！"))
        log_threat_to_vault(chat_id, 'VOICE_SCAM', 'Audio Note', 'CRITICAL', 'AI Deepfake or Macau Scam script detected.')
    send_reply(chat_id, response.text.strip() + get_disclaimer(lang))

def handle_photo(chat_id, file_id):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, t(lang, "📸 **[Analysis]** Scanning image for scams and AI artifacts...", "📸 **[Analisis]** Mengimbas gambar untuk scam dan artifak AI...", "📸 **[分析]** 正在扫描图片中的诈骗和 AI 伪造痕迹..."))
    url = get_telegram_file(file_id)
    img_data = session.get(url).content
    model = genai.GenerativeModel('gemini-3-flash-preview')
    prompt = (
        "You are a Forensic Document Examiner. Analyze this image for digital forgery, AI generation, or clear phishing attempts.\n\n"
        "CRITICAL CONTEXT: Users will upload photos of REAL physical letters, invoices, ID cards. DO NOT flag an image just because it contains future dates, student IDs, or QR codes. DO NOT flag natural camera blur.\n\n"
        "Decision: You MUST default to '🟢'. If the image has strange lighting, output '🟡'. Only output '🔴' if you find undeniable proof of digital fakery or a known scam template.\n"
        "Format your reply EXACTLY using this template:\n\n"
        "[🔴, 🟡, or 🟢] **THREAT REPORT: [CRITICAL RISK, SUSPICIOUS, or CLEAN]**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** Uploaded Image\n**Status:** [Forgery Detected, Suspicious, or Authentic]\n**Reason:** [Brief explanation]\n**Action:** [Advice]"
    )
    response = model.generate_content([prompt + get_lang_append(lang), {'mime_type': 'image/jpeg', 'data': img_data}], generation_config=strict_config)
    if "🔴" in response.text:
        send_sos(chat_id, t(lang, "🚨 SOS: User scanned a suspected Scam/Deepfake Image!", "🚨 SOS: Pengguna mengimbas disyaki Gambar Scam/Palsu!", "🚨 SOS: 用户扫描了疑似诈骗/伪造图片！"))
        log_threat_to_vault(chat_id, 'PHOTO_SCAM', 'Image File', 'CRITICAL', 'Digital forgery or known scam template detected.')
    send_reply(chat_id, response.text.strip() + get_disclaimer(lang))

def handle_video(chat_id, file_id):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, t(lang, "🎥 **[Analysis]** Filtering video for Deepfakes...", "🎥 **[Analisis]** Menapis video untuk Deepfake...", "🎥 **[分析]** 正在过滤视频中的深度伪造..."))
    url = get_telegram_file(file_id)
    path = f"/tmp/{file_id}.mp4"
    with session.get(url, stream=True) as r:
        with open(path, 'wb') as f:
            for chunk in r.iter_content(8192): f.write(chunk)
    uploaded = genai.upload_file(path=path)
    while uploaded.state.name == 'PROCESSING': 
        time.sleep(2)
        uploaded = genai.get_file(uploaded.name)
    model = genai.GenerativeModel('gemini-3-flash-preview')
    prompt = (
        "You are an Expert Video Forensics Analyst. Analyze this video for AI-generated deepfakes.\n\n"
        "CRITICAL CONTEXT: This video is HEAVILY COMPRESSED. Compression causes blurry faces and slight audio-sync delays. DO NOT flag normal compression artifacts as a deepfake.\n\n"
        "Decision: Default to '🟢'. Output '🟡' if heavy artifacts make it hard to verify. Output '🔴' if you find glaring proof of AI generation (morphing, impossible physics).\n"
        "Format your reply EXACTLY using this template:\n\n"
        "[🔴, 🟡, or 🟢] **THREAT REPORT: [CRITICAL RISK, SUSPICIOUS, or CLEAN]**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** Video File\n**Status:** [Deepfake Detected, Suspicious, or Authentic]\n**Reason:** [Explanation]\n**Action:** [Advice]"
    )
    response = model.generate_content([prompt + get_lang_append(lang), uploaded], generation_config=strict_config)
    if "🔴" in response.text:
        send_sos(chat_id, t(lang, "🚨 SOS: Deepfake video detected!", "🚨 SOS: Video Deepfake dikesan!", "🚨 SOS: 检测到深度伪造视频！"))
        log_threat_to_vault(chat_id, 'VIDEO_SCAM', 'Video File', 'CRITICAL', 'AI-generated Deepfake Video Detected.')
    os.remove(path)
    send_reply(chat_id, response.text.strip() + get_disclaimer(lang))

def handle_document(chat_id, doc):
    name = doc.get("file_name", "").lower()
    fid = doc["file_id"]
    if name.endswith(".apk"): check_apk(chat_id, fid, name)
    elif name.endswith(".pdf"): check_pdf(chat_id, fid)
    else: check_general_document(chat_id, fid, name)

def check_web_risk(chat_id, text, lang):
    url_to_check = next((w for w in text.split() if w.startswith("http")), None)
    if not url_to_check: return
    send_interim(chat_id, t(lang, "🌐 **[Layer 1]** Querying Google Web Risk Database...", "🌐 **[Lapisan 1]** Menyemak Google Web Risk...", "🌐 **[第一层]** 正在查询 Google Web Risk..."))
    unique_url = url_to_check if "testsafebrowsing.appspot.com" in url_to_check.lower() else f"{url_to_check}&nocache={random.randint(1,999)}"
    threats = "threatTypes=MALWARE&threatTypes=SOCIAL_ENGINEERING&threatTypes=UNWANTED_SOFTWARE"
    wr_url = f"https://webrisk.googleapis.com/v1/uris:search?{threats}&uri={unique_url}&key={WR_API_KEY}"
    try:
        res = session.get(wr_url)
        if res.status_code == 200 and "threat" in res.json():
            send_sos(chat_id, t(lang, f"🚨 **SOS ALERT**: Blacklisted URL detected! {url_to_check}", f"🚨 **AMARAN SOS**: Pautan disenarai hitam! {url_to_check}", f"🚨 **SOS 警报**: 发现黑名单链接！{url_to_check}"))
            log_threat_to_vault(chat_id, 'URL_BLACKLIST', url_to_check, 'CRITICAL', 'Blocked by Google Web Risk.')
            block_msg = t(lang, f"🔴 **THREAT REPORT: CRITICAL RISK**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** {url_to_check}\n**Status:** 🚫 BLOCKED BY LAYER 1 (Google)\n**Action:** Do not click.", f"🔴 **LAPORAN ANCAMAN: RISIKO KRITIKAL**\n━━━━━━━━━━━━━━━━━━━━━\n**Sasaran:** {url_to_check}\n**Status:** 🚫 DIHALANG OLEH LAPISAN 1\n**Tindakan:** Jangan klik.", f"🔴 **威胁报告：极高风险**\n━━━━━━━━━━━━━━━━━━━━━\n**目标：** {url_to_check}\n**状态：** 🚫 已被第一层拦截\n**行动：** 请勿点击。")
            return send_reply(chat_id, block_msg + get_disclaimer(lang))

        send_interim(chat_id, t(lang, "🛡️ **[Layer 2]** Querying VirusTotal Consortium...", "🛡️ **[Lapisan 2]** Menyemak Konsortium VirusTotal...", "🛡️ **[第二层]** 正在查询 VirusTotal..."))
        url_id = base64.urlsafe_b64encode(url_to_check.encode()).decode().strip("=")
        vt_url = f"https://www.virustotal.com/api/v3/urls/{url_id}"
        vt_res = session.get(vt_url, headers={"x-apikey": VT_API_KEY})
        if vt_res.status_code == 200:
            stats = vt_res.json().get('data', {}).get('attributes', {}).get('last_analysis_stats', {})
            malicious_count = stats.get('malicious', 0) + stats.get('suspicious', 0)
            if malicious_count > 0:
                send_sos(chat_id, t(lang, f"🚨 **SOS ALERT**: Phishing/Malware link! {url_to_check}", f"🚨 **AMARAN SOS**: Pautan Pancingan Data! {url_to_check}", f"🚨 **SOS 警报**: 发现钓鱼/恶意链接！{url_to_check}"))
                log_threat_to_vault(chat_id, 'URL_VIRUSTOTAL', url_to_check, 'HIGH', f'Flagged by {malicious_count} Engines.')
                vt_block_msg = t(lang, f"🔴 **THREAT REPORT: HIGH RISK LINK**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** {url_to_check}\n**Status:** ☠️ BLOCKED BY LAYER 2\n**Reason:** Flagged by {malicious_count} Security Engines.\n**Action:** DO NOT CLICK.", f"🔴 **LAPORAN ANCAMAN: PAUTAN BERISIKO**\n━━━━━━━━━━━━━━━━━━━━━\n**Sasaran:** {url_to_check}\n**Status:** ☠️ DIHALANG OLEH LAPISAN 2\n**Sebab:** Ditanda oleh {malicious_count} Enjin.\n**Tindakan:** JANGAN KLIK.", f"🔴 **威胁报告：高风险链接**\n━━━━━━━━━━━━━━━━━━━━━\n**目标：** {url_to_check}\n**状态：** ☠️ 已被第二层拦截\n**原因：** 被 {malicious_count} 个安全引擎标记。\n**行动：** 请勿点击。")
                return send_reply(chat_id, vt_block_msg + get_disclaimer(lang))

        send_interim(chat_id, t(lang, "📸 **[Layer 3]** Deploying Headless Browser for Deep Scan...", "📸 **[Lapisan 3]** Menjalankan Pelayar Headless...", "📸 **[第三层]** 正在部署无头浏览器..."))
        report_data, image_path = asyncio.run(run_rantai_headless_scan(url_to_check))
        
        if report_data and "error" not in report_data:
            score = report_data.get("risk_score", 0)
            if int(score) > 70:
                send_sos(chat_id, t(lang, f"🚨 **SOS ALERT**: High Risk URL detected! {url_to_check}", f"🚨 **AMARAN SOS**: Pautan Berisiko Tinggi dikesan! {url_to_check}", f"🚨 **SOS 警报**: 发现高风险链接！{url_to_check}"))
                log_threat_to_vault(chat_id, 'URL_FORENSIC', url_to_check, score, report_data.get('summary'))

            caption = t(lang,
                f"🔬 **AwasBot-AI FORENSIC REPORT**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** {url_to_check}\n**Risk Score:** {score}/100\n\n**Summary:** {report_data.get('summary')}\n\n**Verdict:** {report_data.get('verdict_en')}",
                f"🔬 **LAPORAN FORENSIK AwasBot-AI**\n━━━━━━━━━━━━━━━━━━━━━\n**Sasaran:** {url_to_check}\n**Skor Risiko:** {score}/100\n\n**Ringkasan:** {report_data.get('summary')}\n\n**Keputusan:** {report_data.get('verdict_en')}",
                f"🔬 **AwasBot-AI 取证报告**\n━━━━━━━━━━━━━━━━━━━━━\n**目标：** {url_to_check}\n**风险评分：** {score}/100\n\n**摘要：** {report_data.get('summary')}\n\n**结论：** {report_data.get('verdict_en')}"
            )
            if image_path and os.path.exists(image_path):
                with open(image_path, 'rb') as photo:
                    requests.post(f"{get_api_url(False)}/sendPhoto", data={'chat_id': chat_id, 'caption': caption}, files={'photo': photo})
                os.remove(image_path)
            else:
                send_reply(chat_id, caption)
        else: send_reply(chat_id, f"⚠️ AwasBot-AI Error: {report_data.get('error', 'Unknown')}")
    except Exception as e: send_reply(chat_id, f"⚠️ ERROR: {str(e)}")

def check_apk(chat_id, fid, name):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, t(lang, f"🦠 **[Layer 1]** Querying VirusTotal...", f"🦠 **[Lapisan 1]** Menyemak VirusTotal...", f"🦠 **[第一层]** 查询 VirusTotal..."))
    url = get_telegram_file(fid)
    apk_path = f"/tmp/{fid}.apk"
    with session.get(url, stream=True) as r:
        with open(apk_path, 'wb') as f:
            for chunk in r.iter_content(8192): f.write(chunk)
    with open(apk_path, 'rb') as f: apk_bytes = f.read()
    f_hash = hashlib.sha256(apk_bytes).hexdigest()
    vt_res = session.get(f"https://www.virustotal.com/api/v3/files/{f_hash}", headers={"x-apikey": VT_API_KEY})
    malicious = vt_res.json().get('data', {}).get('attributes', {}).get('last_analysis_stats', {}).get('malicious', 0) if vt_res.status_code == 200 else 0

    send_interim(chat_id, t(lang, f"📦 **[Layer 2]** Unpacking APK & Extracting Permissions...", f"📦 **[Lapisan 2]** Mengekstrak Kebenaran APK...", f"📦 **[第二层]** 提取 APK 权限..."))
    try:
        apk_obj = APK(apk_path)
        permissions = apk_obj.get_permissions()
        package_name = apk_obj.package
    except Exception as e:
        permissions = [f"Error: {str(e)}"]
        package_name = "Unknown"
    if os.path.exists(apk_path): os.remove(apk_path)

    send_interim(chat_id, t(lang, f"🧠 **[Layer 3]** Running AI Forensic Analysis...", f"🧠 **[Lapisan 3]** Menjalankan Analisis AI...", f"🧠 **[第三层]** 运行 AI 分析..."))
    model = genai.GenerativeModel('gemini-3-flash-preview')
    prompt = f"Analyze this APK data:\n- Filename: {name}\n- Package Name: {package_name}\n- VirusTotal Hits: {malicious}\n- Requested Permissions: {', '.join(permissions)}\nCRITICAL CONTEXT: Macau Scams use fake apps that request SMS permissions (READ_SMS, RECEIVE_SMS) to steal Bank TAC codes.\nRespond STRICTLY in JSON:\n{{\n  \"risk_score\": (0-100),\n  \"summary\": \"Explain what these permissions allow.\",\n  \"verdict_en\": \"1-sentence recommendation.\"\n}}"
    try:
        gemini_result = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.1, response_mime_type="application/json"))
        raw_text = gemini_result.text.strip()
        if raw_text.startswith("```json"): raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif raw_text.startswith("```"): raw_text = raw_text.split("```")[1].split("```")[0].strip()
        report_data = json.loads(raw_text)
        score = report_data.get("risk_score", 0)

        if int(score) > 70 or malicious > 0:
            send_sos(chat_id, t(lang, f"🚨 **SOS ALERT**: High Risk APK detected! {name}", f"🚨 **AMARAN SOS**: APK Berisiko Tinggi! {name}", f"🚨 **SOS 警报**: 高风险 APK！{name}"))
            log_threat_to_vault(chat_id, 'APK_MALWARE', name, max(int(score), 100) if malicious > 0 else score, report_data.get('summary', 'Banking Trojan detected.'))

        caption = t(lang,
            f"🔬 **AwasBot-AI APK FORENSIC REPORT**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** {name}\n**Package ID:** `{package_name}`\n**Risk Score:** {score}/100\n\n**AI Summary:** {report_data.get('summary')}\n\n**Verdict:** {report_data.get('verdict_en')}",
            f"🔬 **LAPORAN FORENSIK APK AwasBot-AI**\n━━━━━━━━━━━━━━━━━━━━━\n**Sasaran:** {name}\n**ID Pakej:** `{package_name}`\n**Skor Risiko:** {score}/100\n\n**Ringkasan AI:** {report_data.get('summary')}\n\n**Keputusan:** {report_data.get('verdict_en')}",
            f"🔬 **AwasBot-AI APK 取证报告**\n━━━━━━━━━━━━━━━━━━━━━\n**目标：** {name}\n**包名：** `{package_name}`\n**风险评分：** {score}/100\n\n**AI 摘要：** {report_data.get('summary')}\n\n**结论：** {report_data.get('verdict_en')}"
        )
        send_reply(chat_id, caption + get_disclaimer(lang))
    except Exception as e: send_reply(chat_id, f"⚠️ Analysis Error: {str(e)}")

def check_pdf(chat_id, fid):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, t(lang, "📄 **[Layer 1]** Scanning PDF for malware...", "📄 **[Lapisan 1]** Mengimbas PDF...", "📄 **[第一层]** 扫描 PDF..."))
    url = get_telegram_file(fid)
    data = session.get(url).content
    f_hash = hashlib.sha256(data).hexdigest()
    vt_res = session.get(f"https://www.virustotal.com/api/v3/files/{f_hash}", headers={"x-apikey": VT_API_KEY})
    if vt_res.status_code == 200:
        malicious = vt_res.json().get('data', {}).get('attributes', {}).get('last_analysis_stats', {}).get('malicious', 0)
        if malicious > 0:
            send_sos(chat_id, t(lang, f"🚨 **SOS ALERT**: Malware PDF!", f"🚨 **AMARAN SOS**: PDF Hasad!", f"🚨 **SOS 警报**: 恶意 PDF！"))
            log_threat_to_vault(chat_id, 'PDF_MALWARE', 'PDF Document', 'CRITICAL', f'Flagged by {malicious} Engines')
            virus_msg = t(lang, f"🔴 **THREAT REPORT: HIGH RISK**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** PDF\n**Status:** ☠️ Flagged by {malicious} Engines\n**Action:** DO NOT OPEN.", f"🔴 **LAPORAN ANCAMAN: RISIKO TINGGI**\n━━━━━━━━━━━━━━━━━━━━━\n**Sasaran:** PDF\n**Status:** ☠️ Ditanda Oleh {malicious} Enjin\n**Tindakan:** JANGAN BUKA.", f"🔴 **威胁报告：高风险**\n━━━━━━━━━━━━━━━━━━━━━\n**目标：** PDF\n**状态：** ☠️ 被 {malicious} 引擎标记\n**行动：** 请勿打开。")
            return send_reply(chat_id, virus_msg + get_disclaimer(lang))

    send_interim(chat_id, t(lang, "🔍 **[Layer 2]** Analyzing PDF contents...", "🔍 **[Lapisan 2]** Menganalisis kandungan...", "🔍 **[第二层]** 分析内容..."))
    model = genai.GenerativeModel('gemini-3-flash-preview')
    prompt = "Analyze this PDF for phishing or financial scams.\nDecision: Default to '🟢'. If highly aggressive, output '🟡'. Only output '🔴' if 99% sure it's a scam/phishing.\nFormat reply EXACTLY:\n[🔴, 🟡, or 🟢] **THREAT REPORT: [CRITICAL RISK, SUSPICIOUS, or CLEAN]**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** PDF\n**Status:** [Status]\n**Reason:** [Reason]\n**Action:** [Action]"
    response = model.generate_content([prompt + get_lang_append(lang), {'mime_type': 'application/pdf', 'data': data}], generation_config=strict_config)
    if "🔴" in response.text:
        send_sos(chat_id, t(lang, "🚨 SOS: Scam PDF detected!", "🚨 SOS: PDF Scam dikesan!", "🚨 SOS: 发现诈骗 PDF！"))
        log_threat_to_vault(chat_id, 'PDF_PHISHING', 'PDF Document', 'CRITICAL', 'Phishing content detected.')
    send_reply(chat_id, response.text.strip() + get_disclaimer(lang))

def check_general_document(chat_id, fid, name):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, t(lang, f"📄 **[Analysis]** Scanning {name}...", f"📄 **[Analisis]** Mengimbas {name}...", f"📄 **[分析]** 扫描 {name}..."))
    url = get_telegram_file(fid)
    data = session.get(url).content
    f_hash = hashlib.sha256(data).hexdigest()
    vt_res = session.get(f"https://www.virustotal.com/api/v3/files/{f_hash}", headers={"x-apikey": VT_API_KEY})
    if vt_res.status_code == 200:
        malicious = vt_res.json().get('data', {}).get('attributes', {}).get('last_analysis_stats', {}).get('malicious', 0)
        if malicious > 0:
            send_sos(chat_id, t(lang, f"🚨 **SOS ALERT**: Malware detected! {name}", f"🚨 **AMARAN SOS**: Hasad dikesan! {name}", f"🚨 **SOS 警报**: 检测到恶意软件！{name}"))
            log_threat_to_vault(chat_id, 'DOC_MALWARE', name, 'CRITICAL', f'Flagged by {malicious} Engines')
            virus_msg = t(lang, f"🔴 **THREAT REPORT: HIGH RISK**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** {name}\n**Status:** ☠️ Flagged by {malicious} Engines\n**Action:** DO NOT OPEN.", f"🔴 **LAPORAN ANCAMAN: RISIKO TINGGI**\n━━━━━━━━━━━━━━━━━━━━━\n**Sasaran:** {name}\n**Status:** ☠️ Ditanda Oleh {malicious} Enjin\n**Tindakan:** JANGAN BUKA.", f"🔴 **威胁报告：高风险**\n━━━━━━━━━━━━━━━━━━━━━\n**目标：** {name}\n**状态：** ☠️ 被 {malicious} 引擎标记\n**行动：** 请勿打开。")
            send_reply(chat_id, virus_msg + get_disclaimer(lang))
        else:
            send_reply(chat_id, t(lang, f"🟢 **THREAT REPORT: CLEAN**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** {name}\n**Status:** ✅ Passed Global Antivirus Scan\n**Action:** Safe to open.", f"🟢 **LAPORAN ANCAMAN: SELAMAT**\n━━━━━━━━━━━━━━━━━━━━━\n**Sasaran:** {name}\n**Status:** ✅ Melepasi Imbasan\n**Tindakan:** Selamat dibuka.", f"🟢 **威胁报告：安全**\n━━━━━━━━━━━━━━━━━━━━━\n**目标：** {name}\n**状态：** ✅ 通过扫描\n**行动：** 安全可打开。") + get_disclaimer(lang))
    else:
        send_reply(chat_id, t(lang, f"🟡 **THREAT REPORT: UNKNOWN**\n━━━━━━━━━━━━━━━━━━━━━\n**Target:** {name}\n**Status:** ⚠️ No Data\n**Action:** Proceed with caution.", f"🟡 **LAPORAN ANCAMAN: TIDAK DIKETAHUI**\n━━━━━━━━━━━━━━━━━━━━━\n**Sasaran:** {name}\n**Status:** ⚠️ Tiada Data\n**Tindakan:** Berhati-hati.", f"🟡 **威胁报告：未知**\n━━━━━━━━━━━━━━━━━━━━━\n**目标：** {name}\n**状态：** ⚠️ 无数据\n**行动：** 谨慎操作。") + get_disclaimer(lang))


#  5. REAL B2B BANK WEBHOOK HANDLER

def handle_bank_webhook(data, headers):
    PROJECT_ID = os.getenv("BANK_PROJECT_ID")
    API_KEY = os.getenv("BANK_API_KEY")
    SITE_KEY = os.getenv("BANK_SITE_KEY")
    
    token = data.get("token")
    raw_phone = data.get("user_phone", "") 
    search_phone = raw_phone.replace(" ", "").replace("+60", "0")
    
    url = f"https://recaptchaenterprise.googleapis.com/v1/projects/{PROJECT_ID}/assessments?key={API_KEY}"
    payload = {"event": {"token": token, "siteKey": SITE_KEY, "expectedAction": "transfer"}}
    res = session.post(url, json=payload).json()
    
    score = res.get("riskAnalysis", {}).get("score", 1.0)
    
    if score <= 0.3:
        users_ref = db.collection('users')
        query = users_ref.where('phone', '==', search_phone).stream()
        
        victim_chat_id = None
        guardian_id = None
        victim_name = "Unknown User"
        
        for doc in query:
            user_data = doc.to_dict()
            victim_chat_id = doc.id
            guardian_id = user_data.get("guardian_id")
            victim_name = user_data.get("name", "Unknown User")
            break 
            
        if victim_chat_id:
            if guardian_id:
                msg = f"🚨 **BANK FRAUD DETECTED** 🚨\n━━━━━━━━━━━━━━━━━━━━━\n**User Account:** {victim_name} ({search_phone})\n**Google Risk Score:** {score} (CRITICAL)\n**Source:** Maybank Secure Webhook\n\n⚠️ Transaction has been frozen. Guardian must verify."
                reply_markup = {"inline_keyboard": [[{"text": "✅ Approve Transfer", "callback_data": f"approve_{search_phone}"}, {"text": "❌ Block Transfer", "callback_data": f"block_{search_phone}"}]]}
                # SEND TO GUARDIAN BOT!
                send_reply(guardian_id, msg, is_guardian=True, reply_markup=reply_markup)
            else:
                # Send warning to user if no guardian
                send_reply(victim_chat_id, f"🚨 Warning: High risk bank transfer blocked (Score {score}), but no Guardian is linked to your account!", is_guardian=False)
            
            log_threat_to_vault(victim_chat_id, 'BANK_FRAUD', 'Transfer Attempt', score, 'Blocked by Maybank reCAPTCHA Enterprise.')
            
    return (jsonify({"status": "received", "risk_score": score}), 200, headers)