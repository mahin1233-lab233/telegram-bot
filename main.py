import logging
import asyncio
import io
import os
import re  
import json
import phonenumbers
import requests 
from functools import lru_cache
from datetime import datetime, timedelta
from phonenumbers import geocoder, format_number, PhoneNumberFormat
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# --- [ কনফিগারেশন ] ---
BOT_TOKEN = "8929890536:AAHuE8SxPtZPwR2QlwD1SP6EDXv3Cqou5mI"
ADMIN_ID = 8470505628
GROUP_CHAT_ID = -1003838945007 
OTP_GROUP_ID = -1003838945007 
NEW_OTP_GROUP_ID = -1003838945007

GROUP_LINK = "https://t.me/shawnotp007"
RANGE_GROUP_LINK = "https://t.me/shawonrange"
DB_FILE = "MASTER_MURAD_USERS.txt"
BAN_FILE = "All_Users_Deails.txt"

# --- [ ব্যালেন্স ও সেটিং কনফিগারেশন ] ---
BALANCES_FILE = "user_balances.json"
SETTINGS_FILE = "bot_settings.json"
OTP_COUNTS_FILE = "user_otp_counts.json"
WITHDRAW_FILE = "withdraw_requests.json"

# --- [ API SETTINGS (VoltX / 2oo9.cloud) ] ---
API_BASE = "https://2oo9.cloud/api/MXS47FLFX0U/project/tetragonexvoltxsms/@public/api"
API_KEY = "MWFC955WWXQ"

BUY_API = f"{API_BASE}/getnum"
STATUS_API = f"{API_BASE}/success-otp"

# Cache storage for API responses to prevent server block
api_cache = {
    "data": None,
    "timestamp": None
}
CACHE_DURATION = 5  # 5 seconds cache

def get_auth_headers():
    """Authentication headers for API"""
    return {
        "mauthapi": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def get_status_api_cached():
    """Get status API with 5 seconds caching"""
    global api_cache
    
    # Check if cache is valid
    if api_cache["data"] is not None and api_cache["timestamp"] is not None:
        if datetime.now() - api_cache["timestamp"] < timedelta(seconds=CACHE_DURATION):
            return api_cache["data"]
    
    # Fetch new data
    try:
        scraper = requests.Session()
        r = scraper.get(STATUS_API, headers=get_auth_headers(), timeout=10)
        if r.status_code == 200:
            api_cache["data"] = r.json()
            api_cache["timestamp"] = datetime.now()
            return api_cache["data"]
    except Exception as e:
        logging.error(f"Status API error: {e}")
    
    return api_cache["data"] if api_cache["data"] else {"meta": {"code": 0}, "data": {"otps": []}}
# ------------------------------

user_state = {}
withdraw_sessions = {}

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- [ ব্যালেন্স, উইথড্র ও সেটিং ফাংশন ] ---
def get_bot_settings():
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"reward_amount": 0.10, "min_withdraw": 10.0}, f)
    with open(SETTINGS_FILE, "r") as f:
        settings = json.load(f)
        if "min_withdraw" not in settings:
            settings["min_withdraw"] = 10.0
            save_bot_settings(settings)
        return settings

def save_bot_settings(data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f)

def get_user_balance(user_id):
    if not os.path.exists(BALANCES_FILE): return 0.0
    with open(BALANCES_FILE, "r") as f:
        try: balances = json.load(f)
        except: balances = {}
    return balances.get(str(user_id), 0.0)

def add_user_balance(user_id, amount):
    if not os.path.exists(BALANCES_FILE):
        balances = {}
    else:
        with open(BALANCES_FILE, "r") as f:
            try: balances = json.load(f)
            except: balances = {}
    
    current = balances.get(str(user_id), 0.0)
    balances[str(user_id)] = current + float(amount)
    
    with open(BALANCES_FILE, "w") as f:
        json.dump(balances, f)

def get_otp_count(user_id):
    if not os.path.exists(OTP_COUNTS_FILE): return 0
    with open(OTP_COUNTS_FILE, "r") as f:
        try: data = json.load(f)
        except: data = {}
    return data.get(str(user_id), 0)

def add_otp_count(user_id):
    if not os.path.exists(OTP_COUNTS_FILE): data = {}
    else:
        with open(OTP_COUNTS_FILE, "r") as f:
            try: data = json.load(f)
            except: data = {}
    data[str(user_id)] = data.get(str(user_id), 0) + 1
    with open(OTP_COUNTS_FILE, "w") as f: json.dump(data, f)

def save_withdraw_req(req_id, user_id, method, number, amount):
    if not os.path.exists(WITHDRAW_FILE): reqs = {}
    else:
        with open(WITHDRAW_FILE, "r") as f:
            try: reqs = json.load(f)
            except: reqs = {}
    reqs[str(req_id)] = {"user_id": user_id, "method": method, "number": number, "amount": amount}
    with open(WITHDRAW_FILE, "w") as f: json.dump(reqs, f)

def get_withdraw_req(req_id):
    if not os.path.exists(WITHDRAW_FILE): return None
    with open(WITHDRAW_FILE, "r") as f:
        try: reqs = json.load(f)
        except: return None
    return reqs.get(str(req_id))

def delete_withdraw_req(req_id):
    if not os.path.exists(WITHDRAW_FILE): return
    with open(WITHDRAW_FILE, "r") as f:
        try: reqs = json.load(f)
        except: return
    if str(req_id) in reqs:
        del reqs[str(req_id)]
        with open(WITHDRAW_FILE, "w") as f: json.dump(reqs, f)
# ------------------------------------

def is_banned(user_id):
    if not os.path.exists(BAN_FILE): return False
    with open(BAN_FILE, "r") as f:
        return str(user_id) in [line.strip() for line in f]

def ban_user(user_id):
    with open(BAN_FILE, "a") as f:
        f.write(f"{user_id}\n")

def parse_otp_info(sms_text):
    otp = re.search(r'\b\d{4,8}\b', sms_text)
    otp_code = otp.group(0) if otp else "N/A"
    app_name = "Service"
    apps = ['Facebook', 'WhatsApp', 'Telegram', 'Google', 'IMO', 'TikTok', 'Instagram', 'Netflix', 'Twitter', 'Viber']
    for app in apps:
        if app.lower() in sms_text.lower():
            app_name = app
            break
    return otp_code, app_name

def save_user(user_id):
    if not os.path.exists(DB_FILE):
        open(DB_FILE, "w").close()
    with open(DB_FILE, "r") as f:
        users = [line.strip() for line in f]
    if str(user_id) not in users:
        with open(DB_FILE, "a") as f:
            f.write(f"{user_id}\n")

def get_all_users():
    if not os.path.exists(DB_FILE): return []
    with open(DB_FILE, "r") as f:
        return [line.strip() for line in f if line.strip()]

def get_country_info(phone_number):
    try:
        if not phone_number.startswith('+'):
            phone_number = '+' + phone_number
        parsed_num = phonenumbers.parse(phone_number)
        country = geocoder.description_for_number(parsed_num, "en")
        country_code = phonenumbers.region_code_for_number(parsed_num)
        flag = "".join(chr(127397 + ord(c)) for c in country_code.upper())
        return f"{flag} {country}"
    except:
        return "🌍 Unknown Country"

def mask_phone_number(number):
    num_str = str(number)
    if not num_str.startswith('+'):
        num_str = '+' + num_str
    if len(num_str) > 10:
        return f"{num_str[:-6]}**{num_str[-4:]}"
    return num_str

def format_number_national(phone_number):
    """Convert number to national format (without country code prefix)"""
    try:
        if not phone_number.startswith('+'):
            phone_number = '+' + phone_number
        parsed_num = phonenumbers.parse(phone_number)
        # Get national format - removes country code and + sign
        national = format_number(parsed_num, PhoneNumberFormat.NATIONAL)
        # Remove any spaces from national format if needed
        return national
    except:
        return phone_number

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_banned(user_id):
        await update.message.reply_text("❌ You are banned from using this bot.")
        return
    save_user(user_id)
    user_state[user_id] = None 

    main_menu = [
        [KeyboardButton("📲 Get Number")],
        [KeyboardButton("🔗 View Range")],
        [KeyboardButton("💳 My Balance"), KeyboardButton("💸 Withdraw")],
        [KeyboardButton("🆘 Help & Support")]
    ]
    
    if user_id == ADMIN_ID:
        main_menu.append([KeyboardButton("⚙️ ADMIN PANEL")])

    reply_markup = ReplyKeyboardMarkup(main_menu, resize_keyboard=True)

    await update.message.reply_text(
        "Welcome to **ALL METHOD NUMBER**! 👋\n\n"
        "I can provide you with virtual numbers to receive SMS.\n"
        "Use the menu below to get started:\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📲 **Get Number** → Request a number\n"
        "🔗 **View Range** → Join our range channel\n"
        "💳 **My Balance** → Check your current balance\n"
        "💸 **Withdraw** → Withdraw your money\n"
        "━━━━━━━━━━━━━━━━━━",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if is_banned(user_id):
        await query.answer("❌ You are banned!", show_alert=True)
        return
    await query.answer()

    if data == 'admin_main' and user_id == ADMIN_ID:
        kb = [
            [InlineKeyboardButton("📢 Send Notification", callback_data='admin_broadcast')],
            [InlineKeyboardButton("📊 User Stats & List", callback_data='admin_stats')],
            [InlineKeyboardButton("🚫 Ban User", callback_data='ask_ban_id')],
            [InlineKeyboardButton("💰 Set OTP Reward", callback_data='admin_set_reward')],
            [InlineKeyboardButton("⚙️ Set Min Withdraw", callback_data='admin_set_min_wd')],
            [InlineKeyboardButton("💰 All User Blance", callback_data='admin_all_balances')]
        ]
        await query.message.edit_text(f"🛠 **Admin Control Panel**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    elif data == 'admin_broadcast' and user_id == ADMIN_ID:
        user_state[user_id] = "WAITING_FOR_BROADCAST"
        await query.message.reply_text("✉️ **Send any message to broadcast:**", parse_mode="Markdown")
    elif data == 'ask_ban_id' and user_id == ADMIN_ID:
        user_state[user_id] = "WAITING_FOR_BAN_ID"
        await query.message.reply_text("🚫 **Enter User ID to Ban:**", parse_mode="Markdown")
    elif data == 'admin_set_reward' and user_id == ADMIN_ID:
        user_state[user_id] = "WAITING_FOR_REWARD_AMOUNT"
        await query.message.reply_text("💰 **Enter new reward amount (e.g. 0.10):**", parse_mode="Markdown")
    elif data == 'admin_set_min_wd' and user_id == ADMIN_ID:
        user_state[user_id] = "WAITING_FOR_MIN_WD_AMOUNT"
        await query.message.reply_text("💰 **Enter new minimum withdrawal amount:**", parse_mode="Markdown")
    elif data == 'admin_stats' and user_id == ADMIN_ID:
        users = get_all_users()
        report = "📊 **USER STATISTICS**\n━━━━━━━━━━━━━━━━━━\n"
        for u in users: report += f"👤 ID: `{u}`\n"
        report += f"\n👥 **Total: {len(users)}**"
        await query.message.reply_text(report, parse_mode="Markdown")
    elif data == 'admin_all_balances' and user_id == ADMIN_ID:
        if not os.path.exists(BALANCES_FILE):
            await query.message.reply_text("❌ No balance data found.")
        else:
            with open(BALANCES_FILE, "r") as f:
                try: balances = json.load(f)
                except: balances = {}
            if not balances:
                await query.message.reply_text("❌ No users have a balance yet.")
            else:
                report = "💰 **ALL USER BALANCES**\n━━━━━━━━━━━━━━━━━━\n"
                for uid, bal in balances.items():
                    if float(bal) > 0:
                        report += f"👤 ID: `{uid}` | Balance: `{bal}৳`\n"
                
                if report == "💰 **ALL USER BALANCES**\n━━━━━━━━━━━━━━━━━━\n":
                    report = "❌ No users have a balance greater than 0."
                
                if len(report) > 4000:
                    file_obj = io.BytesIO(report.encode('utf-8'))
                    file_obj.name = "All_User_Balances.txt"
                    await context.bot.send_document(chat_id=user_id, document=file_obj, caption="💰 **All User Balances**", parse_mode="Markdown")
                else:
                    await query.message.reply_text(report, parse_mode="Markdown")
    elif data.startswith('change_num_'):
        range_id = data.split('_')[2]
        try: await query.message.edit_reply_markup(reply_markup=None)
        except: pass
        await generate_single_number(query.message, range_id, user_id, context, is_edit=False)
        
    elif data.startswith('wd_'):
        method = data.split('_')[1]
        if user_id not in withdraw_sessions: withdraw_sessions[user_id] = {}
        withdraw_sessions[user_id]['method'] = method
        user_state[user_id] = "WAITING_FOR_WITHDRAW_NUMBER"
        await query.message.reply_text(f"⌨️ **Enter Your {method} Number:**", parse_mode="Markdown")
        
    elif data.startswith('acc_wd_') and user_id == ADMIN_ID:
        req_id = data.split('_')[2]
        req = get_withdraw_req(req_id)
        if req:
            uid = req['user_id']
            amt = req['amount']
            delete_withdraw_req(req_id)
            await query.message.edit_text(query.message.text + "\n\n✅ **Status: ACCEPTED**")
            try: await context.bot.send_message(chat_id=uid, text=f"✅ Your withdrawal request of {amt}৳ has been successfully completed!")
            except: pass
        else:
            await query.message.edit_text("❌ Request not found or already processed.")
            
    elif data.startswith('rej_wd_') and user_id == ADMIN_ID:
        req_id = data.split('_')[2]
        req = get_withdraw_req(req_id)
        if req:
            uid = req['user_id']
            amt = req['amount']
            add_user_balance(uid, amt)
            delete_withdraw_req(req_id)
            await query.message.edit_text(query.message.text + "\n\n❌ **Status: REJECTED (Balance Refunded)**")
            try: await context.bot.send_message(chat_id=uid, text=f"❌ Your withdrawal request of {amt}৳ has failed/rejected. Balance has been refunded to your account.")
            except: pass
        else:
            await query.message.edit_text("❌ Request not found or already processed.")

async def single_otp_checker(context, msg_obj, full_number, national_number, target_id, range_id, keyboard, user_data=None):
    received_otps = set() 
    for _ in range(30): 
        await asyncio.sleep(10)
        try:
            response_data = get_status_api_cached()
            
            if response_data and response_data.get("meta", {}).get("code") == 200:
                data = response_data.get("data", {})
                otps = data.get("otps", [])
                
                for x in otps:
                    num_from_api = str(x.get('number', '')).replace('+', '')
                    if num_from_api == str(full_number):
                        full_sms = x.get('message', '')
                        otp_id = x.get('otp_id', full_sms)
                        if full_sms and otp_id not in received_otps:
                            received_otps.add(otp_id)
                            otp_code, app_name = parse_otp_info(full_sms)
                            country_info = get_country_info(full_number)

                            private_msg = (f"✅ OTP Received Successfully ✅\n\n🌍 Country: {country_info}\n\n📱 Service: {app_name}\n📞 Full Number: `+{full_number}`\n📞 National Number: `{national_number}`\n🔑 OTP: `{otp_code}`\n\n📩 Full SMS: `{full_sms}`")
                            group_msg = (f"✅ OTP Received Successfully ✅\n\n🌍 Country: {country_info}\n\n📱 Service: {app_name}\n📞 Full Number: `{mask_phone_number(full_number)}`\n📞 National Number: `{national_number}`\n🔑 OTP: `{otp_code}`\n\n📩 Full SMS: `{full_sms}`")
                            
                            markup = InlineKeyboardMarkup([[InlineKeyboardButton("💥 NUMBER PANEL 💥", url="https://t.me/otppanel1_bot")]])
                            
                            try: await context.bot.send_message(chat_id=target_id, text=f"Your OTP Code Is: {otp_code}")
                            except: pass
                            
                            try: await context.bot.send_message(chat_id=target_id, text=private_msg, parse_mode="Markdown")
                            except: await context.bot.send_message(chat_id=target_id, text=private_msg)

                            settings = get_bot_settings()
                            reward = settings.get("reward_amount", 0.10)
                            add_user_balance(target_id, reward)
                            add_otp_count(target_id)
                            try: await context.bot.send_message(chat_id=target_id, text=f"Money Received Successfull {reward}৳ +")
                            except: pass

                            try: await context.bot.send_message(chat_id=OTP_GROUP_ID, text=group_msg, parse_mode="Markdown", reply_markup=markup)
                            except: await context.bot.send_message(chat_id=OTP_GROUP_ID, text=group_msg, reply_markup=markup)
        except Exception as e:
            logging.error(f"OTP check error: {e}")
            continue

async def handle_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_banned(user_id): return
    text = update.message.text.strip() if update.message.text else ""

    if text == "📲 Get Number":
        user_state[user_id] = "WAITING_FOR_SINGLE_RANGE"
        await update.message.reply_text("⌨️ **Enter Range ID:**", parse_mode="Markdown")
        return
    elif text == "🔗 View Range":
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("👉 Click to Join Range Channel", url=RANGE_GROUP_LINK)]])
        await update.message.reply_text("Click the button below to see the ranges:", reply_markup=markup)
        return
    elif text == "💳 My Balance":
        bal = get_user_balance(user_id)
        otps = get_otp_count(user_id)
        await update.message.reply_text(f"💰 **Your Current Balance:** `{bal:.2f}৳`\n📥 **Total OTP Received:** `{otps}`", parse_mode="Markdown")
        return
    elif text == "💸 Withdraw":
        kb = [
            [InlineKeyboardButton("Bkash", callback_data='wd_Bkash'),
             InlineKeyboardButton("Nagad", callback_data='wd_Nagad'),
             InlineKeyboardButton("Rocket", callback_data='wd_Rocket')]
        ]
        await update.message.reply_text("💳 **Select Your Withdrawal Method:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return
    elif text == "🆘 Help & Support":
        await update.message.reply_text("Contact Admin for support: @shawon8173")
        return
    elif text == "⚙️ ADMIN PANEL" and user_id == ADMIN_ID:
        kb = [
            [InlineKeyboardButton("📢 Send Notification", callback_data='admin_broadcast')],
            [InlineKeyboardButton("📊 User Stats & List", callback_data='admin_stats')],
            [InlineKeyboardButton("🚫 Ban User", callback_data='ask_ban_id')],
            [InlineKeyboardButton("💰 Set OTP Reward", callback_data='admin_set_reward')],
            [InlineKeyboardButton("⚙️ Set Min Withdraw", callback_data='admin_set_min_wd')],
            [InlineKeyboardButton("💰 All User Blance", callback_data='admin_all_balances')]
        ]
        await update.message.reply_text(f"🛠 **Admin Control Panel**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    state = user_state.get(user_id)
    if state == "WAITING_FOR_BROADCAST" and user_id == ADMIN_ID:
        user_state[user_id] = None
        users = get_all_users()
        asyncio.create_task(broadcast_task(context, update.message, users))
        await update.message.reply_text(f"✅ Broadcast initiated.")
    elif state == "WAITING_FOR_BAN_ID" and user_id == ADMIN_ID:
        user_state[user_id] = None
        ban_user(text)
        await update.message.reply_text(f"✅ User `{text}` banned.")
    elif state == "WAITING_FOR_REWARD_AMOUNT" and user_id == ADMIN_ID:
        user_state[user_id] = None
        try:
            new_amount = float(text)
            settings = get_bot_settings()
            settings["reward_amount"] = new_amount
            save_bot_settings(settings)
            await update.message.reply_text(f"✅ OTP Reward updated to `{new_amount}৳`")
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please enter a valid number (e.g. 0.10).")
    elif state == "WAITING_FOR_MIN_WD_AMOUNT" and user_id == ADMIN_ID:
        user_state[user_id] = None
        try:
            new_amount = float(text)
            settings = get_bot_settings()
            settings["min_withdraw"] = new_amount
            save_bot_settings(settings)
            await update.message.reply_text(f"✅ Minimum withdrawal updated to `{new_amount}৳`")
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please enter a valid number.")
    elif state == "WAITING_FOR_SINGLE_RANGE":
        user_state[user_id] = None
        await generate_single_number(update.message, text, user_id, context)
    elif state == "WAITING_FOR_WITHDRAW_NUMBER":
        user_state[user_id] = "WAITING_FOR_WITHDRAW_AMOUNT"
        if user_id not in withdraw_sessions: withdraw_sessions[user_id] = {}
        withdraw_sessions[user_id]['number'] = text
        await update.message.reply_text("⌨️ **Enter Your Amount:**", parse_mode="Markdown")
        
    elif state == "WAITING_FOR_WITHDRAW_AMOUNT":
        try:
            amount = float(text)
            settings = get_bot_settings()
            min_wd = settings.get("min_withdraw", 10.0)
            bal = get_user_balance(user_id)

            if amount < min_wd:
                await update.message.reply_text(f"❌ Minimum withdrawal amount is `{min_wd}৳`", parse_mode="Markdown")
                return
            if amount > bal:
                await update.message.reply_text("❌ Insufficient balance. You don't have enough money.")
                return
            
            user_state[user_id] = None
            
            add_user_balance(user_id, -amount)
            
            method = withdraw_sessions.get(user_id, {}).get('method', 'Unknown')
            number = withdraw_sessions.get(user_id, {}).get('number', 'Unknown')
            req_id = str(int(datetime.now().timestamp()))
            
            save_withdraw_req(req_id, user_id, method, number, amount)
            
            await update.message.reply_text("⏳ Your withdrawal request has been sent to the admin. Please wait for approval.")
            
            admin_msg = f"💸 **New Withdrawal Request**\n\n👤 User ID: `{user_id}`\n💳 Method: `{method}`\n📞 Number: `{number}`\n💰 Amount: `{amount}৳`"
            admin_kb = [
                [InlineKeyboardButton("✅ Accept", callback_data=f'acc_wd_{req_id}'),
                 InlineKeyboardButton("❌ Reject", callback_data=f'rej_wd_{req_id}')]
            ]
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, reply_markup=InlineKeyboardMarkup(admin_kb), parse_mode="Markdown")
            
        except ValueError:
            user_state[user_id] = "WAITING_FOR_WITHDRAW_AMOUNT"
            await update.message.reply_text("❌ Invalid amount. Please enter a valid number.")

async def broadcast_task(context, message_obj, user_list):
    text = f"📢 **ADMIN NOTICE**\n\n{message_obj.text or message_obj.caption or ''}"
    photo = message_obj.photo[-1].file_id if message_obj.photo else None
    video = message_obj.video.file_id if message_obj.video else None
    document = message_obj.document.file_id if message_obj.document else None
    for uid in user_list:
        try:
            if photo: await context.bot.send_photo(chat_id=uid, photo=photo, caption=text, parse_mode="Markdown")
            elif video: await context.bot.send_video(chat_id=uid, video=video, caption=text, parse_mode="Markdown")
            elif document: await context.bot.send_document(chat_id=uid, document=document, caption=text, parse_mode="Markdown")
            else: await context.bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
            await asyncio.sleep(0.05)
        except: continue

async def generate_single_number(message_obj, range_id, user_id, context, is_edit=False):
    status_msg = await message_obj.reply_text("📡 Searching for number...") 
    
    clean_range_id = str(range_id).replace("XXX", "").strip()
    
    try:
        scraper = requests.Session()
        r = scraper.post(BUY_API, headers=get_auth_headers(), json={"rid": clean_range_id}, timeout=15)
        
        if r.status_code == 200:
            response_data = r.json()
            if response_data.get("meta", {}).get("code") == 200:
                data = response_data.get('data', {})
                full_number = str(data.get('no_plus_number', '')).replace('+', '')
                country = data.get('country', '')
                
                if full_number and full_number != '':
                    # Convert to national format (without country code)
                    national_number = format_number_national(full_number)
                    country_info = f"{country}" if country else get_country_info(full_number)
                    
                    keyboard = [[InlineKeyboardButton("🔄 Change Number", callback_data=f'change_num_{range_id}')],[InlineKeyboardButton("📩 View OTP", url=GROUP_LINK)]]
                    
                    # Display both formats to the user
                    msg = (f"✅ **YOUR NUMBER**\n\n📶 Range: `{range_id}`\n🌍 Country: `{country_info}`\n\n📞 **Full Number:** `+{full_number}`\n📞 **National Number:** `{national_number}`\n\n📩 SMS Status: `Waiting...`")
                    
                    await status_msg.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
                    asyncio.create_task(single_otp_checker(context, status_msg, full_number, national_number, user_id, range_id, keyboard, message_obj.from_user))
                else:
                    await status_msg.edit_text("❌ No number received from API. Please try again.")
            else:
                error_message = response_data.get("message", "Range empty or invalid")
                await status_msg.edit_text(f"❌ {error_message}\n\nPlease check the Range ID and try again.")
        else:
            await status_msg.edit_text(f"❌ API Error: Status {r.status_code}\nPlease contact admin.")
    except Exception as e:
        logging.error(f"Single number error: {e}")
        await status_msg.edit_text(f"❌ Error: {str(e)[:100]}")

if __name__ == '__main__':
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message_input))
    application.add_handler(MessageHandler(filters.ALL & (~filters.TEXT) & (~filters.COMMAND), handle_message_input)) 
    print("🚀 Master Murad Number Bot LIVE with VoltX API!")
    application.run_polling(drop_pending_updates=True)
