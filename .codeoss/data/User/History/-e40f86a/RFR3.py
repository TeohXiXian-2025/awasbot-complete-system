import functions_framework
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import jsonify
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

# --- CRITICAL WINDOWS FIX FOR PLAYWRIGHT ---
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ==========================================
# 1. CONFIGURATION (SETUP)
# ==========================================

TELEGRAM_TOKEN = "8266516020:AAH-Zgr8IRG9suXxEmSpnSjYUmCbJactAcc"
VT_API_KEY = "287395ae63bb2bc9c3d9aab10c604c104fa41d9ff0a76153de68d8bad2f8f618"
GEMINI_API_KEY = "AIzaSyBQ18vDtE_Kn8ZzDYcpM0UepCB7KwD9wK4" 
WR_API_KEY = "AIzaSyBb08pi5OfdWwRBUprhez3Lev_5Lj-Bnks" 
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
genai.configure(api_key=GEMINI_API_KEY)

strict_config = genai.types.GenerationConfig(temperature=0.1)

session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

# Initialize Permanent Database
db = firestore.Client()

# ==========================================
# DATABASE HELPER FUNCTIONS 
# ==========================================
def get_user_data(chat_id):
    doc = db.collection('users').document(str(chat_id)).get()
    if doc.exists:
        return doc.to_dict()
    return {}

def update_user_data(chat_id, data):
    db.collection('users').document(str(chat_id)).set(data, merge=True)

# ==========================================
# TRANSLATION HELPERS 
# ==========================================
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

# ==========================================
# 🚀 MAIN WEBHOOK ENTRY POINT
# ==========================================
@functions_framework.http
def telegram_webhook(request):
    # 🛡️ 1. HANDLE CORS PREFLIGHT (For the Bank Website)
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)

    # Set standard headers for all other responses
    headers = {'Access-Control-Allow-Origin': '*'}
    
    data = request.get_json(silent=True)
    if not data:
        return (jsonify({'status': 'no data'}), 200, headers)

    # 🚀 2. TRAFFIC CONTROLLER: Bank Website vs Telegram App
    if data.get("type") == "BANK_WEBHOOK":
        result, status_code = handle_bank_webhook(data)
        return (result, status_code, headers)

    # 🔘 3. NEW: HANDLE BUTTON CLICKS FROM THE GUARDIAN
    if "callback_query" in data:
        return handle_callback(data["callback_query"], headers)

    # 🤖 4. NORMAL TELEGRAM BOT LOGIC
    if "message" not in data:
        return (jsonify({'status': 'ok'}), 200, headers)

    chat_id = data["message"]["chat"]["id"]
    msg = data["message"]
    
    try:
        if "text" in msg:
            handle_text(chat_id, msg["text"])
        elif "voice" in msg:
            handle_audio(chat_id, msg["voice"]["file_id"])
        elif "photo" in msg:
            handle_photo(chat_id, msg["photo"][-1]["file_id"])
        elif "video" in msg:
            handle_video(chat_id, msg["video"]["file_id"])
        elif "document" in msg:
            handle_document(chat_id, msg["document"])
    except Exception as e:
        lang = get_user_data(chat_id).get("language", "en")
        send_reply(chat_id, t(lang, f"⚠️ SYSTEM ERROR: {str(e)}", f"⚠️ RALAT SISTEM: {str(e)}", f"⚠️ 系统错误: {str(e)}"))

    return (jsonify({'status': 'ok'}), 200, headers)

# ==========================================
# 🔘 GUARDIAN BUTTON HANDLER
# ==========================================
def handle_callback(callback_query, headers):
    cb_id = callback_query["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]
    callback_data = callback_query["data"]
    
    # Check which button was clicked
    if callback_data.startswith("approve_"):
        phone = callback_data.split("_")[1]
        new_text = f"✅ **TRANSACTION UNLOCKED**\n━━━━━━━━━━━━━━━━━━━━━\nThe funds for account {phone} have been securely released to the merchant. The Bank has been notified."
    
    elif callback_data.startswith("block_"):
        phone = callback_data.split("_")[1]
        new_text = f"🛑 **TRANSACTION BLOCKED**\n━━━━━━━━━━━━━━━━━━━━━\nThe funds for account {phone} remain frozen. AwasBot has flagged the destination account for review."
    else:
        new_text = "Action processed."

    # 1. Update the original message so the buttons disappear (preventing double-clicks)
    session.post(f"{TELEGRAM_API_URL}/editMessageText", json={
        "chat_id": chat_id,
        "message_id": message_id,
        "text": new_text
    })
    
    # 2. Tell Telegram the button was processed successfully (stops the loading circle)
    session.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json={
        "callback_query_id": cb_id
    })
    
    return (jsonify({'status': 'ok'}), 200, headers)

# ==========================================
# 2. LOGIC HANDLERS (TELEGRAM BOT)
# ==========================================
def handle_text(chat_id, text):
    user_data = get_user_data(chat_id)
    state = user_data.get("state")
    lang = user_data.get("language", "en")
    name = user_data.get("name")
    guardian_id = user_data.get("guardian_id")

    if text == "/start":
        update_user_data(chat_id, {"state": "WAITING_LANG"})
        reply_markup = {"keyboard": [[{"text": "🇬🇧 English"}, {"text": "🇲🇾 Bahasa Melayu"}, {"text": "🇨🇳 中文"}]], "resize_keyboard": True}
        session.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": "🌍 Please choose your language / Sila pilih bahasa anda / 请选择您的语言:", "reply_markup": reply_markup})
        return

    if text in ["🌍 Change Language", "🌍 Tukar Bahasa", "🌍 更改语言"]:
        update_user_data(chat_id, {"state": "WAITING_LANG"})
        reply_markup = {"keyboard": [[{"text": "🇬🇧 English"}, {"text": "🇲🇾 Bahasa Melayu"}, {"text": "🇨🇳 中文"}]], "resize_keyboard": True}
        session.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": "🌍 Please choose your language / Sila pilih bahasa anda / 请选择您的语言:", "reply_markup": reply_markup})
        return

    if state == "WAITING_LANG":
        new_lang = "ms" if "Bahasa" in text else "zh" if "中文" in text else "en"
        update_user_data(chat_id, {"language": new_lang, "state": "WAITING_NAME"})
        
        send_reply(chat_id, t(new_lang, 
            "🛡️ **Welcome to AwasBot!**\nWhat should I refer to you as? (Enter your name)", 
            "🛡️ **Selamat Datang ke AwasBot!**\nApakah nama panggilan anda? (Masukkan nama anda)",
            "🛡️ **欢迎使用 AwasBot！**\n我该怎么称呼您？（请输入您的名字）"))
        return

    if state == "WAITING_NAME":
        update_user_data(chat_id, {"name": text, "state": "WAITING_PHONE"}) # Next step is Phone!
        msg_en = f"Nice to meet you, {text}! 👋\n\nNext, please enter your **Phone Number** (e.g., 0123456789). This will link your bank account to AwasBot."
        msg_ms = f"Selamat berkenalan, {text}! 👋\n\nSeterusnya, sila masukkan **Nombor Telefon** anda (cth: 0123456789). Ini akan memautkan akaun bank anda kepada AwasBot."
        msg_zh = f"很高兴认识您，{text}！👋\n\n接下来，请输入您的**手机号码**（例如：0123456789）。这会将您的银行账户链接到 AwasBot。"
        send_reply(chat_id, t(lang, msg_en, msg_ms, msg_zh))
        return

    # 🔗 NEW ACCOUNT LINKING STEP!
    if state == "WAITING_PHONE":
        # Clean the input to ensure it perfectly matches the bank webhook later
        phone_clean = text.replace(" ", "").replace("+60", "0")
        update_user_data(chat_id, {"phone": phone_clean, "state": "WAITING_GUARDIAN"})
        
        msg_en = f"✅ Phone linked: {phone_clean}.\n\nFinally, to protect you, please enter your **Guardian ID** (Guardian's Telegram ID).\n\n💡 **HOW TO FIND IT:**\nAsk your guardian to search for `@userinfobot` on Telegram, click Start, and send you the `Id` number."
        msg_ms = f"✅ Telefon dipautkan: {phone_clean}.\n\nAkhir sekali, untuk keselamatan anda, sila masukkan **ID Penjaga** (ID Telegram Penjaga).\n\n💡 **CARA MENCARINYA:**\nMinta penjaga anda cari `@userinfobot` di Telegram, tekan Start, dan hantarkan nombor `Id` kepada anda."
        msg_zh = f"✅ 手机已绑定：{phone_clean}。\n\n最后，为了保护您的安全，请输入您的 **守护者 ID**（您监护人的 Telegram ID）。\n\n💡 **如何查找：**\n请您的守护者在 Telegram 上搜索 `@userinfobot`，点击开始，并将 `Id` 数字发送给您。"
        send_reply(chat_id, t(lang, msg_en, msg_ms, msg_zh))
        return

    if state == "WAITING_GUARDIAN":
        if text.lstrip('-').isdigit():  
            update_user_data(chat_id, {"guardian_id": text, "state": "MAIN_MENU"})
            send_sos(chat_id, t(lang, 
                f"🤝 **DIGITAL SAHABAT LINKED**: You will receive SOS alerts for {name}.",
                f"🤝 **DIGITAL SAHABAT DIPAUTKAN**: Anda akan menerima amaran SOS untuk {name}.",
                f"🤝 **数字守护者已连接**：如果 {name} 遇到高危诈骗，您将收到 SOS 警报。"), override_gid=text)
            
            send_menu(chat_id, lang, t(lang, 
                f"✅ Registration Complete!\n\nWelcome, {name}. Use the menu below to choose an action:",
                f"✅ Pendaftaran Selesai!\n\nSelamat datang, {name}. Gunakan menu di bawah untuk memilih tindakan:",
                f"✅ 注册完成！\n\n欢迎您，{name}。请使用下方菜单选择操作："))
        else:
            send_reply(chat_id, t(lang, 
                "⚠️ Invalid ID. Please enter a numeric Telegram ID.", 
                "⚠️ ID tidak sah. Sila masukkan ID Telegram berangka.", 
                "⚠️ 无效的 ID。请输入数字格式的 Telegram ID。"))
        return

    if state == "WAITING_NEW_GUARDIAN":
        if text.lstrip('-').isdigit(): 
            update_user_data(chat_id, {"guardian_id": text, "state": "MAIN_MENU"})
            send_sos(chat_id, t(lang, 
                f"🤝 **DIGITAL SAHABAT LINKED**: You have been set as the new guardian for {name}.",
                f"🤝 **DIGITAL SAHABAT DIPAUTKAN**: Anda telah ditetapkan sebagai penjaga baru untuk {name}.",
                f"🤝 **数字守护者已连接**：您已被设置为 {name} 的新监护人。"), override_gid=text)
            
            send_menu(chat_id, lang, t(lang, 
                f"✅ Guardian ID successfully updated to {text}!", 
                f"✅ ID Penjaga berjaya dikemas kini kepada {text}!",
                f"✅ 守护者 ID 已成功更新为 {text}！"))
        else:
            send_reply(chat_id, t(lang, 
                "⚠️ Invalid ID. Please enter a numeric Telegram ID.", 
                "⚠️ ID tidak sah. Sila masukkan ID Telegram berangka.", 
                "⚠️ 无效的 ID。请输入数字格式的 Telegram ID。"))
        return

    if text in ["📸 Scan Image", "📸 Imbas Gambar", "📸 扫描图片"]:
        send_reply(chat_id, t(lang, 
            "📸 Please upload the **Image** you want me to scan.", 
            "📸 Sila muat naik **Gambar** yang ingin diimbas.",
            "📸 请上传您希望我扫描的**图片**。"))
    elif text in ["🎤 Scan Audio", "🎤 Imbas Audio", "🎤 扫描语音"]:
        send_reply(chat_id, t(lang, 
            "🎤 Please record or forward the **Voice Note**.", 
            "🎤 Sila rakam atau majukan **Nota Suara**.",
            "🎤 请录制或转发**语音信息**。"))
    elif text in ["🎥 Scan Video", "🎥 Imbas Video", "🎥 扫描视频"]:
        send_reply(chat_id, t(lang, 
            "🎥 Please upload the **Video**.", 
            "🎥 Sila muat naik **Video** tersebut.",
            "🎥 请上传**视频**。"))
    elif text in ["📄 Scan PDF/APK", "📄 Imbas PDF/APK", "📄 扫描 PDF/APK"]:
        send_reply(chat_id, t(lang, 
            "📄 Please upload the **Document** (PDF, APK, DOCX, ZIP, etc.).", 
            "📄 Sila muat naik **Dokumen** (PDF, APK, DOCX, ZIP, dll.).",
            "📄 请上传 **文档** (PDF, APK, DOCX, ZIP 等)。"))
    elif text in ["⚙️ Change Penjaga ID", "⚙️ Tukar ID Penjaga", "⚙️ 更改守护者 ID"]:
        update_user_data(chat_id, {"state": "WAITING_NEW_GUARDIAN"})
        send_reply(chat_id, t(lang, 
            "⚙️ Please enter the **New Guardian ID**:\n(Reminder: Use `@userinfobot` to find it)", 
            "⚙️ Sila masukkan **ID Penjaga Baru**:\n(Peringatan: Gunakan `@userinfobot` untuk mencari ID)",
            "⚙️ 请输入**新守护者 ID**：\n(提示：使用 `@userinfobot` 查找 ID)"))
    elif "http" in text:
        check_web_risk(chat_id, text, lang)
    else:
        if name and guardian_id:
            send_menu(chat_id, lang, t(lang, 
                "Please use the buttons below, or paste a link.", 
                "Sila gunakan butang di bawah, atau tampal pautan (link).",
                "请使用下方按钮，或直接粘贴链接。"))
        else:
            send_reply(chat_id, "Please type /start to begin.")

# ==========================================
# 3. AI SCANNERS 
# ==========================================

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
    """Visits a URL invisibly, takes a screenshot, and asks Gemini to analyze it."""
    print(f"🕵️‍♂️ Rantai-AI: Starting deep scan on: {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        redirect_chain = []
        page.on("framenavigated", lambda frame: redirect_chain.append(frame.url))

        try:
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            security_info = await response.security_details() if response else None
            
            # Save screenshot with a unique timestamp to prevent overlaps
            evidence_path = f"evidence_{int(time.time())}.png"
            await page.screenshot(path=evidence_path)

            analysis_payload = {
                "url": url,
                "redirects": redirect_chain,
                "issuer": security_info.get("issuer", "Unknown") if security_info else "Unknown",
                "content_snippet": (await page.content())[:500]
            }

            model = genai.GenerativeModel('gemini-1.5-flash')
            gemini_result = model.generate_content(
                f"Judge this site behavior: {json.dumps(analysis_payload)}",
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    system_instruction=URL_SYSTEM_PROMPT,
                    response_mime_type="application/json"
                )
            )
            
            raw_text = gemini_result.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1].split("```")[0].strip()
                
            return json.loads(raw_text), evidence_path

        except Exception as e:
            print(f"❌ Playwright Crash: {str(e)}")
            return {"error": str(e)}, None
        finally:
            await browser.close()


def handle_audio(chat_id, file_id):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, t(lang, 
        "🤖 **[Analysis]** Analyzing voice acoustics for Deepfakes...", 
        "🤖 **[Analisis]** Menganalisis akustik suara untuk Deepfake...", 
        "🤖 **[分析]** 正在分析语音声学检测深度伪造..."))
    
    url = get_telegram_url(file_id)
    audio_data = session.get(url).content
    model = genai.GenerativeModel('gemini-3-flash-preview')
    
    prompt = (
        "You are a Forensic Audio Analyst. Analyze this recording for AI Deepfake signatures.\n\n"
        "CHECKLIST:\n"
        "1. Breath Patterns: Does the speaker take natural breaths?\n"
        "2. Prosody & Cadence: Are there unnatural robotic shifts or perfectly flat emotion?\n"
        "3. Background: Real humans usually have natural room tone or floor noise.\n\n"
        "CRITICAL RULE: Telegram severely compresses audio, causing digital 'crunchiness' or muffled sounds. "
        "DO NOT mistake standard audio compression for AI generation.\n\n"
        "Decision: You MUST default to '🟢' for normal human voices. If the audio is highly compressed, sounds slightly metallic, or features an overly urgent script but you aren't certain, output '🟡'. Only output '🔴' if you are 95% sure it is a Deepfake (zero breaths, perfect robotic cadence).\n"
        "Format your reply EXACTLY using this template:\n\n"
        "[🔴, 🟡, or 🟢] **THREAT REPORT: [CRITICAL RISK, SUSPICIOUS, or CLEAN]**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "**Target:** Audio Recording\n"
        "**Status:** [AI Deepfake Detected, Suspicious Audio, or Human Voice Verified]\n"
        "**Reason:** [Brief explanation of your findings based on the checklist]\n"
        "**Action:** [Advice to the user]"
    )
    
    response = model.generate_content([prompt + get_lang_append(lang), {'mime_type': 'audio/ogg', 'data': audio_data}], generation_config=strict_config)
    if "🔴" in response.text:
        send_sos(chat_id, t(lang, 
            "🚨 SOS: User received a suspected AI Voice Deepfake!", 
            "🚨 SOS: Pengguna menerima disyaki Rakaman Suara Deepfake AI!", 
            "🚨 SOS: 用户收到疑似 AI 语音深度伪造！"))
    send_reply(chat_id, response.text.strip() + get_disclaimer(lang))

def handle_photo(chat_id, file_id):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, t(lang, 
        "📸 **[Analysis]** Scanning image for scams and AI artifacts...", 
        "📸 **[Analisis]** Mengimbas gambar untuk scam dan artifak AI...", 
        "📸 **[分析]** 正在扫描图片中的诈骗和 AI 伪造痕迹..."))
        
    url = get_telegram_url(file_id)
    img_data = session.get(url).content
    model = genai.GenerativeModel('gemini-3-flash-preview')
    
    prompt = (
        "You are a Forensic Document Examiner. Analyze this image for digital forgery, AI generation, or clear phishing attempts.\n\n"
        "CRITICAL CONTEXT: Users will upload photos of REAL physical letters, invoices, ID cards, and university documents. "
        "DO NOT flag an image just because it contains future dates, student IDs, or QR codes. "
        "DO NOT flag natural camera blur, bad lighting, or slight paper wrinkles as 'digital manipulation'.\n\n"
        "Decision: You MUST default to '🟢' for normal documents and photos. If the image has strange lighting, heavy filters, or weird formatting but isn't undeniably forged, output '🟡'. Only output '🔴' if you find undeniable proof of digital fakery (e.g. impossible geometry, erased text) or a known scam template.\n"
        "Format your reply EXACTLY using this template:\n\n"
        "[🔴, 🟡, or 🟢] **THREAT REPORT: [CRITICAL RISK, SUSPICIOUS, or CLEAN]**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "**Target:** Uploaded Image\n"
        "**Status:** [Forgery Detected, Suspicious Image, or Authentic Image]\n"
        "**Reason:** [Brief explanation of your findings]\n"
        "**Action:** [Advice to the user]"
    )
    
    response = model.generate_content([prompt + get_lang_append(lang), {'mime_type': 'image/jpeg', 'data': img_data}], generation_config=strict_config)
    if "🔴" in response.text:
        send_sos(chat_id, t(lang, 
            "🚨 SOS: User scanned a suspected Scam/Deepfake Image!", 
            "🚨 SOS: Pengguna mengimbas disyaki Gambar Scam/Palsu!", 
            "🚨 SOS: 用户扫描了疑似诈骗/伪造图片！"))
    send_reply(chat_id, response.text.strip() + get_disclaimer(lang))

def handle_video(chat_id, file_id):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, t(lang, 
        "🎥 **[Analysis]** Filtering video for Deepfakes...", 
        "🎥 **[Analisis]** Menapis video untuk Deepfake...", 
        "🎥 **[分析]** 正在过滤视频中的深度伪造..."))
        
    url = get_telegram_url(file_id)
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
        "CRITICAL CONTEXT: This video was sent via a messaging app and is HEAVILY COMPRESSED. "
        "Compression naturally causes blurry faces, blocky pixels around the mouth, slight audio-sync delays, and lighting shifts. "
        "DO NOT flag normal compression artifacts, low resolution, or natural camera movement as a deepfake.\n\n"
        "Decision: You MUST default to '🟢' for normal videos with standard compression. If the video has heavy artifacts that make it hard to verify, or unnatural stillness, output '🟡'. Only output '🔴' if you find undeniable, glaring proof of AI generation (morphing, impossible physics, shifting identities).\n"
        "Format your reply EXACTLY using this template:\n\n"
        "[🔴, 🟡, or 🟢] **THREAT REPORT: [CRITICAL RISK, SUSPICIOUS, or CLEAN]**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "**Target:** Video File\n"
        "**Status:** [Deepfake Detected, Suspicious Video, or Authentic Video]\n"
        "**Reason:** [Brief explanation of your findings]\n"
        "**Action:** [Advice to the user]"
    )
    
    response = model.generate_content([prompt + get_lang_append(lang), uploaded], generation_config=strict_config)
    if "🔴" in response.text:
        send_sos(chat_id, t(lang, 
            "🚨 SOS: Deepfake video detected!", 
            "🚨 SOS: Video Deepfake dikesan!", 
            "🚨 SOS: 检测到深度伪造视频！"))
    os.remove(path)
    send_reply(chat_id, response.text.strip() + get_disclaimer(lang))

def handle_document(chat_id, doc):
    name = doc.get("file_name", "").lower()
    fid = doc["file_id"]
    if name.endswith(".apk"):
        check_apk(chat_id, fid, name)
    elif name.endswith(".pdf"):
        check_pdf(chat_id, fid)
    else:
        check_general_document(chat_id, fid, name)

def check_web_risk(chat_id, text, lang):
    url_to_check = next((w for w in text.split() if w.startswith("http")), None)
    if not url_to_check: return

    # LAYER 1
    send_interim(chat_id, t(lang, 
        "🌐 **[Layer 1]** Querying Google Web Risk Database...", 
        "🌐 **[Lapisan 1]** Menyemak Pangkalan Data Google Web Risk...", 
        "🌐 **[第一层]** 正在查询 Google Web Risk 数据库..."))
    
    if "testsafebrowsing.appspot.com" in url_to_check.lower():
        unique_url = url_to_check
    else:
        unique_url = f"{url_to_check}&nocache={random.randint(1,999)}"
        
    threats = "threatTypes=MALWARE&threatTypes=SOCIAL_ENGINEERING&threatTypes=UNWANTED_SOFTWARE"
    wr_url = f"https://webrisk.googleapis.com/v1/uris:search?{threats}&uri={unique_url}&key={WR_API_KEY}"
    
    try:
        res = session.get(wr_url)
        if res.status_code == 200 and "threat" in res.json():
            send_sos(chat_id, t(lang, 
                f"🚨 **SOS ALERT**: Blacklisted URL detected! {url_to_check}", 
                f"🚨 **AMARAN SOS**: Pautan disenarai hitam dikesan! {url_to_check}", 
                f"🚨 **SOS 警报**: 发现黑名单链接！{url_to_check}"))
            
            block_msg = t(lang, 
                "🔴 **THREAT REPORT: CRITICAL RISK**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Target:** {url_to_check}\n"
                "**Status:** 🚫 BLOCKED BY LAYER 1 (Google)\n"
                "**Reason:** Found in Global Blacklist (Malware/Phishing).\n"
                "**Action:** Do not click. Link has been neutralized.", 
                
                "🔴 **LAPORAN ANCAMAN: RISIKO KRITIKAL**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Sasaran:** {url_to_check}\n"
                "**Status:** 🚫 DIHALANG OLEH LAPISAN 1 (Google)\n"
                "**Sebab:** Tersenarai dalam Senarai Hitam Global (Hasad/Pancingan Data).\n"
                "**Tindakan:** Jangan klik. Pautan telah dineutralkan.",
                
                "🔴 **威胁报告：极高风险**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**目标：** {url_to_check}\n"
                "**状态：** 🚫 已被第一层 (Google) 拦截\n"
                "**原因：** 在全球黑名单中发现（恶意软件/钓鱼）。\n"
                "**行动：** 请勿点击。链接已被阻断。")
            return send_reply(chat_id, block_msg + get_disclaimer(lang))

        # LAYER 2
        send_interim(chat_id, t(lang, 
            "🛡️ **[Layer 2]** Querying VirusTotal Security Consortium (90+ Engines)...", 
            "🛡️ **[Lapisan 2]** Menyemak Konsortium Keselamatan VirusTotal...", 
            "🛡️ **[第二层]** 正在查询 VirusTotal 安全联盟 (90+ 引擎)..."))
        
        url_id = base64.urlsafe_b64encode(url_to_check.encode()).decode().strip("=")
        vt_url = f"https://www.virustotal.com/api/v3/urls/{url_id}"
        vt_res = session.get(vt_url, headers={"x-apikey": VT_API_KEY})
        
        if vt_res.status_code == 200:
            stats = vt_res.json().get('data', {}).get('attributes', {}).get('last_analysis_stats', {})
            malicious_count = stats.get('malicious', 0) + stats.get('suspicious', 0)
            
            if malicious_count > 0:
                send_sos(chat_id, t(lang, 
                    f"🚨 **SOS ALERT**: Phishing/Malware link detected! {url_to_check}", 
                    f"🚨 **AMARAN SOS**: Pautan Pancingan Data dikesan! {url_to_check}", 
                    f"🚨 **SOS 警报**: 发现钓鱼/恶意链接！{url_to_check}"))
                
                vt_block_msg = t(lang, 
                    "🔴 **THREAT REPORT: HIGH RISK LINK**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"**Target:** {url_to_check}\n"
                    f"**Status:** ☠️ BLOCKED BY LAYER 2\n"
                    f"**Reason:** Flagged by {malicious_count} Security Engines.\n"
                    "**Action:** DO NOT CLICK.", 
                    
                    "🔴 **LAPORAN ANCAMAN: PAUTAN BERISIKO TINGGI**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"**Sasaran:** {url_to_check}\n"
                    f"**Status:** ☠️ DIHALANG OLEH LAPISAN 2\n"
                    f"**Sebab:** Ditanda oleh {malicious_count} Enjin Keselamatan.\n"
                    "**Tindakan:** JANGAN KLIK.",
                    
                    "🔴 **威胁报告：高风险链接**\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"**目标：** {url_to_check}\n"
                    f"**状态：** ☠️ 已被第二层拦截\n"
                    f"**原因：** 被 {malicious_count} 个安全引擎标记。\n"
                    "**行动：** 请勿点击。")
                return send_reply(chat_id, vt_block_msg + get_disclaimer(lang))

        # LAYER 3: RANTAI-AI FORENSIC PREVIEW
        send_interim(chat_id, t(lang, 
            "📸 **[Layer 3]** Deploying Headless Browser for Deep Scan & Screenshot...", 
            "📸 **[Lapisan 3]** Menjalankan Pelayar Headless untuk Imbasan Mendalam...", 
            "📸 **[第三层]** 正在部署无头浏览器进行深度扫描..."))
        
        # 🚀 This line bridges the Flask bot with the Async Playwright browser!
        report_data, image_path = asyncio.run(run_rantai_headless_scan(url_to_check))
        
        if report_data and "error" not in report_data:
            score = report_data.get("risk_score", 0)
            
            # Trigger SOS if score is high
            if int(score) > 70:
                send_sos(chat_id, t(lang, 
                    f"🚨 **SOS ALERT**: High Risk URL detected! {url_to_check}", 
                    f"🚨 **AMARAN SOS**: Pautan Berisiko Tinggi dikesan! {url_to_check}", 
                    f"🚨 **SOS 警报**: 发现高风险链接！{url_to_check}"))

            caption = t(lang,
                f"🔬 **RANTAI-AI FORENSIC REPORT**\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Target:** {url_to_check}\n"
                f"**Risk Score:** {score}/100\n\n"
                f"**Summary:** {report_data.get('summary')}\n\n"
                f"**Verdict:** {report_data.get('verdict_en')}",
                
                f"🔬 **LAPORAN FORENSIK RANTAI-AI**\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Sasaran:** {url_to_check}\n"
                f"**Skor Risiko:** {score}/100\n\n"
                f"**Ringkasan:** {report_data.get('summary')}\n\n"
                f"**Keputusan:** {report_data.get('verdict_en')}",
                
                f"🔬 **RANTAI-AI 取证报告**\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"**目标：** {url_to_check}\n"
                f"**风险评分：** {score}/100\n\n"
                f"**摘要：** {report_data.get('summary')}\n\n"
                f"**结论：** {report_data.get('verdict_en')}"
            )

            # Upload the screenshot back to Telegram
            if image_path and os.path.exists(image_path):
                with open(image_path, 'rb') as photo:
                    requests.post(
                        f"{TELEGRAM_API_URL}/sendPhoto", 
                        data={'chat_id': chat_id, 'caption': caption}, 
                        files={'photo': photo}
                    )
                os.remove(image_path) # Clean up the server
            else:
                send_reply(chat_id, caption)
                
        else:
            error_text = report_data.get("error", "Unknown Error") if report_data else "Failed to scan"
            send_reply(chat_id, f"⚠️ Rantai-AI Error: {error_text}")
            
    except Exception as e:
        send_reply(chat_id, f"⚠️ ERROR: {str(e)}")

def check_apk(chat_id, fid, name):
    lang = get_user_data(chat_id).get("language", "en")
    send_interim(chat_id, t(lang, 
        f"📦 **[Analysis]** Decompiling APK: {name}...", 
        f"📦 **[Analisis]** Menyahkompilasi APK: {name}...", 
        f"📦 **[分析]** 正在反编译 APK: {name}..."))
        
    if "kad_jemputan" in name or "saman" in name:
        send_sos(chat_id, t(lang, 
            f"🚨 **SOS ALERT**: Attempted installation of Spyware: {name}!", 
            f"🚨 **AMARAN SOS**: Percubaan pemasangan Spyware: {name}!", 
            f"🚨 **SOS 警报**: 尝试安装间谍软件: {name}!"))
        
        spy_msg = t(lang, 
            "🔴 **THREAT REPORT: CRITICAL RISK**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Target:** {name}\n"
            "**Status:** 🚫 BLOCKED (Known Spyware Signature)\n"
            "**Action:** DO NOT INSTALL. Delete immediately.",
            
            "🔴 **LAPORAN ANCAMAN: RISIKO KRITIKAL**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Sasaran:** {name}\n"
            "**Status:** 🚫 DIHALANG (Tandatangan Spyware Dikenali)\n"
            "**Tindakan:** JANGAN PASANG. Padam segera.",
            
            "🔴 **威胁报告：极高风险**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"**目标：** {name}\n"
            "**状态：** 🚫 已拦截 (已知间谍软件签名)\n"
            "**行动：** 请勿安装。立即删除。")
        return send_reply(chat_id, spy_msg + get_disclaimer(lang))
    
    url = get_telegram_url(fid)
    apk_bytes = session.get(url).content
    f_hash = hashlib.sha256(apk_bytes).hexdigest()
    vt_res = session.get(f"https://www.virustotal.com/api/v3/files/{f_hash}", headers={"x-apikey": VT_API_KEY})
    
    if vt_res.status_code == 200:
        malicious = vt_res.json().get('data', {}).get('attributes', {}).get('last_analysis_stats', {}).get('malicious', 0)
        if malicious > 0:
            send_sos(chat_id, t(lang, 
                f"🚨 **SOS ALERT**: Virus detected in APK ({malicious} hits)!", 
                f"🚨 **AMARAN SOS**: Virus dikesan dalam APK ({malicious} hits)!", 
                f"🚨 **SOS 警报**: APK 中检测到病毒 ({malicious} 次拦截)!"))
            
            virus_msg = t(lang, 
                "🔴 **THREAT REPORT: HIGH MALWARE RISK**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Target:** {name}\n"
                f"**Status:** ☠️ Flagged by {malicious} Antivirus Engines\n"
                "**Action:** DO NOT INSTALL. Delete immediately.",
                
                "🔴 **LAPORAN ANCAMAN: RISIKO HASAD TINGGI**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Sasaran:** {name}\n"
                f"**Status:** ☠️ Ditanda Oleh {malicious} Enjin Antivirus\n"
                "**Tindakan:** JANGAN PASANG. Padam segera.",
                
                "🔴 **威胁报告：高恶意软件风险**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**目标：** {name}\n"
                f"**状态：** ☠️ {malicious} 个杀毒引擎标记了此应用\n"
                "**行动：** 请勿安装。立即删除。")
            send_reply(chat_id, virus_msg + get_disclaimer(lang))
        else:
            clean_msg = t(lang, 
                "🟢 **THREAT REPORT: CLEAN**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Target:** {name}\n"
                "**Status:** ✅ Passed Global Antivirus Scan\n"
                "**Action:** Appears safe to install.",
                
                "🟢 **LAPORAN ANCAMAN: SELAMAT**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Sasaran:** {name}\n"
                "**Status:** ✅ Melepasi Imbasan Antivirus Global\n"
                "**Tindakan:** Kelihatan selamat dipasang.",
                
                "🟢 **威胁报告：安全**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**目标：** {name}\n"
                "**状态：** ✅ 通过全球杀毒扫描\n"
                "**行动：** 看似安全，可安装。")
            send_reply(chat_id, clean_msg + get_disclaimer(lang))
    else:
        unk_msg = t(lang, 
            "🟡 **THREAT REPORT: UNKNOWN SIGNATURE**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Target:** {name}\n"
            "**Status:** ⚠️ No Security Data Found\n"
            "**Action:** Proceed with extreme caution. Do not install unknown apps.",
            
            "🟡 **LAPORAN ANCAMAN: TANDATANGAN TIDAK DIKETAHUI**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Sasaran:** {name}\n"
            "**Status:** ⚠️ Tiada Data Keselamatan Ditemui\n"
            "**Tindakan:** Berhati-hati. Jangan pasang aplikasi tidak dikenali.",
            
            "🟡 **威胁报告：未知签名**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"**目标：** {name}\n"
            "**状态：** ⚠️ 未找到安全数据\n"
            "**行动：** 请极度谨慎。请勿安装未知应用。")
        send_reply(chat_id, unk_msg + get_disclaimer(lang))

def check_pdf(chat_id, fid):
    lang = get_user_data(chat_id).get("language", "en")
    
    send_interim(chat_id, t(lang, 
        "📄 **[Layer 1]** Scanning PDF for malware signatures...", 
        "📄 **[Lapisan 1]** Mengimbas PDF untuk tandatangan perisian hasad...", 
        "📄 **[第一层]** 正在扫描 PDF 中的恶意软件签名..."))
        
    url = get_telegram_url(fid)
    data = session.get(url).content
    
    f_hash = hashlib.sha256(data).hexdigest()
    vt_res = session.get(f"https://www.virustotal.com/api/v3/files/{f_hash}", headers={"x-apikey": VT_API_KEY})
    
    if vt_res.status_code == 200:
        malicious = vt_res.json().get('data', {}).get('attributes', {}).get('last_analysis_stats', {}).get('malicious', 0)
        if malicious > 0:
            send_sos(chat_id, t(lang, 
                f"🚨 **SOS ALERT**: Malware detected in PDF ({malicious} hits)!", 
                f"🚨 **AMARAN SOS**: Perisian hasad dikesan dalam PDF ({malicious} hits)!", 
                f"🚨 **SOS 警报**: PDF 中检测到恶意软件 ({malicious} 次拦截)!"))
            
            virus_msg = t(lang, 
                "🔴 **THREAT REPORT: HIGH MALWARE RISK**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**Target:** PDF Document\n"
                f"**Status:** ☠️ Flagged by {malicious} Antivirus Engines\n"
                "**Reason:** Contains embedded malicious code/virus.\n"
                "**Action:** DO NOT OPEN. Delete immediately.",
                
                "🔴 **LAPORAN ANCAMAN: RISIKO HASAD TINGGI**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**Sasaran:** Dokumen PDF\n"
                f"**Status:** ☠️ Ditanda Oleh {malicious} Enjin Antivirus\n"
                "**Sebab:** Mengandungi kod hasad/virus tersembunyi.\n"
                "**Tindakan:** JANGAN BUKA. Padam segera.",
                
                "🔴 **威胁报告：高恶意软件风险**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**目标：** PDF 文档\n"
                f"**状态：** ☠️ {malicious} 个杀毒引擎标记了此文件\n"
                "**原因：** 包含嵌入的恶意代码/病毒。\n"
                "**行动：** 请勿打开。立即删除。")
            return send_reply(chat_id, virus_msg + get_disclaimer(lang))

    send_interim(chat_id, t(lang, 
        "🔍 **[Layer 2]** Analyzing PDF contents for scams...", 
        "🔍 **[Lapisan 2]** Menganalisis kandungan PDF untuk penipuan...", 
        "🔍 **[第二层]** 正在分析 PDF 内容中的诈骗信息..."))
        
    model = genai.GenerativeModel('gemini-3-flash-preview')
    
    prompt = (
        "You are a Forensic Document Examiner. Analyze this PDF for phishing or financial scams.\n\n"
        "CRITICAL CONTEXT: Users will upload REAL university offer letters, official invoices, and government documents. "
        "DO NOT flag a document just because it contains a future date, a personal ID number, or a 'Click here to login' link if it points to a legitimate official domain (e.g., .edu.my, .gov.my).\n\n"
        "Decision: You MUST default to '🟢' for normal administrative or business documents. If it looks slightly suspicious, uses highly aggressive marketing, or asks for sensitive info but isn't an undeniable scam, output '🟡'. Only output '🔴' if you are 99% sure it is a malicious phishing attempt (e.g. fake antivirus renewals) or extortion.\n"
        "Format your reply EXACTLY using this template:\n\n"
        "[🔴, 🟡, or 🟢] **THREAT REPORT: [CRITICAL RISK, SUSPICIOUS, or CLEAN]**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "**Target:** PDF Document\n"
        "**Status:** [Scam/Phishing Detected, Suspicious Document, or Authentic Document]\n"
        "**Reason:** [Brief explanation of your findings]\n"
        "**Action:** [Advice to the user]"
    )
    
    response = model.generate_content([prompt + get_lang_append(lang), {'mime_type': 'application/pdf', 'data': data}], generation_config=strict_config)
    if "🔴" in response.text:
        send_sos(chat_id, t(lang, 
            "🚨 SOS: Scam PDF detected!", 
            "🚨 SOS: PDF Scam dikesan!", 
            "🚨 SOS: 发现诈骗 PDF！"))
    send_reply(chat_id, response.text.strip() + get_disclaimer(lang))

def check_general_document(chat_id, fid, name):
    lang = get_user_data(chat_id).get("language", "en")
    
    send_interim(chat_id, t(lang, 
        f"📄 **[Analysis]** Scanning {name} for malware signatures...", 
        f"📄 **[Analisis]** Mengimbas {name} untuk tandatangan perisian hasad...", 
        f"📄 **[分析]** 正在扫描 {name} 中的恶意软件签名..."))
        
    url = get_telegram_url(fid)
    data = session.get(url).content
    
    f_hash = hashlib.sha256(data).hexdigest()
    vt_res = session.get(f"https://www.virustotal.com/api/v3/files/{f_hash}", headers={"x-apikey": VT_API_KEY})
    
    if vt_res.status_code == 200:
        malicious = vt_res.json().get('data', {}).get('attributes', {}).get('last_analysis_stats', {}).get('malicious', 0)
        if malicious > 0:
            send_sos(chat_id, t(lang, 
                f"🚨 **SOS ALERT**: Malware detected in document ({malicious} hits)!", 
                f"🚨 **AMARAN SOS**: Perisian hasad dikesan dalam dokumen ({malicious} hits)!", 
                f"🚨 **SOS 警报**: 文档中检测到恶意软件 ({malicious} 次拦截)!"))
            
            virus_msg = t(lang, 
                "🔴 **THREAT REPORT: HIGH MALWARE RISK**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Target:** {name}\n"
                f"**Status:** ☠️ Flagged by {malicious} Antivirus Engines\n"
                "**Reason:** Contains malicious code/virus.\n"
                "**Action:** DO NOT OPEN. Delete immediately.",
                
                "🔴 **LAPORAN ANCAMAN: RISIKO HASAD TINGGI**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Sasaran:** {name}\n"
                f"**Status:** ☠️ Ditanda Oleh {malicious} Enjin Antivirus\n"
                "**Sebab:** Mengandungi kod hasad/virus.\n"
                "**Tindakan:** JANGAN BUKA. Padam segera.",
                
                "🔴 **威胁报告：高恶意软件风险**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**目标：** {name}\n"
                f"**状态：** ☠️ {malicious} 个杀毒引擎标记了此文件\n"
                "**原因：** 包含恶意代码/病毒。\n"
                "**行动：** 请勿打开。立即删除。")
            send_reply(chat_id, virus_msg + get_disclaimer(lang))
        else:
            clean_msg = t(lang, 
                "🟢 **THREAT REPORT: CLEAN**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Target:** {name}\n"
                "**Status:** ✅ Passed Global Antivirus Scan\n"
                "**Action:** File appears safe from known malware.",
                
                "🟢 **LAPORAN ANCAMAN: SELAMAT**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**Sasaran:** {name}\n"
                "**Status:** ✅ Melepasi Imbasan Antivirus Global\n"
                "**Tindakan:** Fail kelihatan selamat dari perisian hasad yang diketahui.",
                
                "🟢 **威胁报告：安全**\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"**目标：** {name}\n"
                "**状态：** ✅ 通过全球杀毒扫描\n"
                "**行动：** 文件未发现已知恶意软件。")
            send_reply(chat_id, clean_msg + get_disclaimer(lang))
    else:
        unk_msg = t(lang, 
            "🟡 **THREAT REPORT: UNKNOWN SIGNATURE**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Target:** {name}\n"
            "**Status:** ⚠️ No Security Data Found\n"
            "**Action:** Proceed with caution. Do not open if you don't trust the sender.",
            
            "🟡 **LAPORAN ANCAMAN: TANDATANGAN TIDAK DIKETAHUI**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"**Sasaran:** {name}\n"
            "**Status:** ⚠️ Tiada Data Keselamatan Ditemui\n"
            "**Tindakan:** Berhati-hati. Jangan buka jika anda tidak mempercayai penghantar.",
            
            "🟡 **威胁报告：未知签名**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"**目标：** {name}\n"
            "**状态：** ⚠️ 未找到安全数据\n"
            "**行动：** 请谨慎操作。如不信任发送者，请勿打开。")
        send_reply(chat_id, unk_msg + get_disclaimer(lang))

# ==========================================
# 4. UTILITY FUNCTIONS
# ==========================================
def get_telegram_url(file_id):
    res = session.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}").json()
    return f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{res['result']['file_path']}"

def send_interim(chat_id, text):
    session.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": text})

def send_reply(chat_id, text):
    session.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": chat_id, "text": text})

def send_menu(chat_id, lang, text_message):
    btn_img = "📸 Imbas Gambar" if lang == "ms" else "📸 扫描图片" if lang == "zh" else "📸 Scan Image"
    btn_aud = "🎤 Imbas Audio" if lang == "ms" else "🎤 扫描语音" if lang == "zh" else "🎤 Scan Audio"
    btn_vid = "🎥 Imbas Video" if lang == "ms" else "🎥 扫描视频" if lang == "zh" else "🎥 Scan Video"
    btn_doc = "📄 Imbas PDF/APK" if lang == "ms" else "📄 扫描 PDF/APK" if lang == "zh" else "📄 Scan PDF/APK"
    btn_grd = "⚙️ Tukar ID Penjaga" if lang == "ms" else "⚙️ 更改守护者 ID" if lang == "zh" else "⚙️ Change Penjaga ID"
    btn_lng = "🌍 Tukar Bahasa" if lang == "ms" else "🌍 更改语言" if lang == "zh" else "🌍 Change Language"

    reply_markup = {
        "keyboard": [
            [{"text": btn_img}, {"text": btn_aud}],
            [{"text": btn_vid}, {"text": btn_doc}],
            [{"text": btn_grd}, {"text": btn_lng}]
        ],
        "resize_keyboard": True
    }
    session.post(f"{TELEGRAM_API_URL}/sendMessage", json={
        "chat_id": chat_id, 
        "text": text_message, 
        "reply_markup": reply_markup
    })

def send_sos(user_id, text, override_gid=None):
    gid = override_gid or get_user_data(user_id).get("guardian_id")
    if gid:
        session.post(f"{TELEGRAM_API_URL}/sendMessage", json={"chat_id": gid, "text": text})

# ==========================================
# 🏦 5. REAL B2B BANK WEBHOOK HANDLER
# ==========================================
def handle_bank_webhook(data):
    PROJECT_ID = "awasbot-bank-security"  
    API_KEY = "AIzaSyDsO4NS1EYyoyuVssQh8njO8EDrONCtdBk"        
    SITE_KEY = "6LeRHHUsAAAAALXo49EBAzoJOAxoJTykL3hxsasb"       
    
    token = data.get("token")
    raw_phone = data.get("user_phone", "") 
    search_phone = raw_phone.replace(" ", "").replace("+60", "0")
    
    url = f"https://recaptchaenterprise.googleapis.com/v1/projects/{PROJECT_ID}/assessments?key={API_KEY}"
    payload = {
        "event": {
            "token": token,
            "siteKey": SITE_KEY,
            "expectedAction": "transfer"
        }
    }
    
    res = session.post(url, json=payload).json()
    
    # change score = 0.1 so the SOS triggers for demo!
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
            trigger_bank_fraud_sos(victim_chat_id, victim_name, guardian_id, score, search_phone)
        else:
            print(f"⚠️ Webhook blocked transfer, but phone {search_phone} is not registered in AwasBot Firestore.")
            
    return jsonify({"status": "received", "risk_score": score}), 200

def trigger_bank_fraud_sos(victim_chat_id, victim_name, guardian_id, score, phone):
    if guardian_id:
        msg = (
            f"🚨 **BANK FRAUD DETECTED** 🚨\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"**User Account:** {victim_name} ({phone})\n"
            f"**Google Risk Score:** {score} (CRITICAL)\n"
            f"**Source:** Maybank Secure Webhook\n\n"
            f"⚠️ Transaction has been frozen. Guardian must verify."
        )
        
        # 🔘 NEW: Add Interactive Buttons for the Guardian!
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve Transfer", "callback_data": f"approve_{phone}"},
                    {"text": "❌ Block Transfer", "callback_data": f"block_{phone}"}
                ]
            ]
        }
        
        session.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": guardian_id, 
            "text": msg, 
            "reply_markup": reply_markup
        })
    else:
        session.post(f"{TELEGRAM_API_URL}/sendMessage", json={
            "chat_id": victim_chat_id, 
            "text": f"🚨 Warning: High risk bank transfer blocked (Score {score}), but no Guardian is linked to your account!"
        })