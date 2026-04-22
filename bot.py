import json
import logging
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# === CONFIG ===
BOT_TOKEN = "8204822480:AAGSeX2L5jBW0VpbEJv_TWtQwCG5ZGwS_dM"
ADMIN_IDS = [8204822480, 8770974330, 6031406805]
WEBAPP_URL = "https://cashplug02.netlify.app"

# === ADMIN CONTROLLED SETTINGS ===
settings = {
    "vnum_api_key": "uw1w7rscldpmkrhp9lmuf5a8f2yc1lhv",
    "vnum_api_url": "https://no1verify.com/api",
    "referral_bonus": 200,
    "listing_fee": 200,
    "deposit_bank": "Opay",
    "deposit_account": "9066274784",
    "deposit_name": "Cash Plug",
    "vnum_markup": 50
}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# === IN-MEMORY DB ===
users = {}
products = []
orders = []
vnum_orders = []
vnum_prices = {}

def is_admin(user_id):
    return user_id in ADMIN_IDS

# === VIRTUAL NUMBER API FUNCTIONS ===
def get_vnum_price(country, service="whatsapp"):
    try:
        res = requests.get(f"{settings['vnum_api_url']}/getPrices", params={
            "api_key": settings['vnum_api_key'],
            "service": service,
            "country": country
        }, timeout=10)
        data = res.json()
        base_price = float(data.get("price", 0))
        final_price = int((base_price * 1600) + settings["vnum_markup"])
        return max(final_price, 100)
    except Exception as e:
        logging.error(f"Price fetch error: {e}")
        return 150

def buy_vnum_number(country, service="whatsapp"):
    try:
        res = requests.get(f"{settings['vnum_api_url']}/getNumber", params={
            "api_key": settings['vnum_api_key'],
            "service": service,
            "country": country
        }, timeout=10)
        data = res.json()
        if data.get("status") == "success":
            return {"id": data["id"], "number": data["number"]}
        logging.warning(f"Number buy failed: {data}")
        return None
    except Exception as e:
        logging.error(f"Buy number error: {e}")
        return None

def get_vnum_status(order_id):
    try:
        res = requests.get(f"{settings['vnum_api_url']}/getStatus", params={
            "api_key": settings['vnum_api_key'],
            "id": order_id
        }, timeout=10)
        data = res.json()
        if data.get("status") == "sms_received":
            return f"STATUS_OK:{data.get('code')}"
        return data.get("status", "waiting")
    except Exception as e:
        logging.error(f"Status check error: {e}")
        return "ERROR"

# === BACKGROUND SMS POLLER ===
async def poll_sms_codes(app):
    while True:
        for order in vnum_orders:
            if order["status"] == "waiting":
                status = get_vnum_status(order["order_id"])
                if status.startswith("STATUS_OK:"):
                    code = status.split(":")[1]
                    order["status"] = "completed"
                    try:
                        await app.bot.send_message(
                            order["user_id"],
                            f"📲 SMS CODE RECEIVED\n\nService: {order['service'].title()}\nNumber: +{order['number']}\n\nCode: <code>{code}</code>",
                            parse_mode="HTML"
                        )
                    except Exception as e:
                        logging.error(f"Failed to send code to {order['user_id']}: {e}")
        await asyncio.sleep(5)

# === START COMMAND ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if user.id not in users:
        users[user.id] = {
            "name": user.first_name,
            "username": user.username or f"user{user.id}",
            "balance": 0,
            "referrals": 0,
            "referred_by": None
        }

        if args and args[0].startswith("ref"):
            try:
                referrer_id = int(args[0][3:])
                if referrer_id in users and referrer_id!= user.id:
                    users[referrer_id]["balance"] += settings["referral_bonus"]
                    users[referrer_id]["referrals"] += 1
                    users[user.id]["referred_by"] = referrer_id
                    await context.bot.send_message(
                        referrer_id,
                        f"🎉 +₦{settings['referral_bonus']}! {user.first_name} joined. Balance: ₦{users[referrer_id]['balance']}"
                    )
            except: pass

    keyboard = [[InlineKeyboardButton(
        "🚀 Open Cash Plug",
        web_app=WebAppInfo(url=f"{WEBAPP_URL}/home.html?id={user.id}&name={user.first_name}")
    )]]

    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])

    await update.message.reply_text(
        f"Welcome to Cash Plug, {user.first_name}! 💰\n\nEarn, shop, and withdraw instantly.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# === HANDLE WEB APP DATA ===
async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = json.loads(update.effective_message.web_app_data.data)
    action = data.get("action")
    user_id = int(data.get("user_id", user.id))

    if user_id not in users:
        users[user_id] = {"name": user.first_name, "username": user.username or f"user{user.id}", "balance": 0, "referrals": 0}

    u = users[user_id]

    if action == "get_user_data":
        await update.effective_message.reply_web_app(json.dumps({
            "balance": u["balance"], "referrals": u["referrals"], "username": u["username"], "name": u["name"]
        }))

    elif action == "get_profile_data":
        badge = "Admin" if is_admin(user_id) else "Member" if u["referrals"] == 0 else "VIP"
        await update.effective_message.reply_web_app(json.dumps({
            "balance": u["balance"], "name": u["name"], "username": u["username"], "badge": badge
        }))

    elif action == "get_wallet_data":
        await update.effective_message.reply_web_app(json.dumps({
            "balance": u["balance"],
            "deposit_bank": settings["deposit_bank"],
            "deposit_account": settings["deposit_account"],
            "deposit_name": settings["deposit_name"]
        }))

    elif action == "get_earn_data":
        bot_info = await context.bot.get_me()
        await update.effective_message.reply_web_app(json.dumps({
            "balance": u["balance"], "referrals": u["referrals"], "username": u["username"], "bot_username": bot_info.username
        }))

    elif action == "get_products":
        await update.effective_message.reply_web_app(json.dumps({"products": products}))

    elif action == "filter_products":
        cat = data.get("category")
        filtered = products if cat == "all" else [p for p in products if p["category"] == cat]
        await update.effective_message.reply_web_app(json.dumps({"products": filtered}))

    elif action == "post_product":
        fee = settings["listing_fee"]
        if u["balance"] < fee:
            return await update.effective_message.reply_text(f"❌ Insufficient balance. Fee: ₦{fee}")

        u["balance"] -= fee
        products.append({
            "id": len(products) + 1, "seller_id": user_id, "seller": u["name"], "name": data["name"],
            "description": data["description"], "price": int(data["price"]), "phone": data["phone"],
            "category": data["category"], "payment_method": data["payment_method"], "image_url": "https://via.placeholder.com/150"
        })
        await update.effective_message.reply_text(f"✅ Product posted! -₦{fee} fee deducted")
        for admin_id in ADMIN_IDS:
            if admin_id!= user_id:
                try: await context.bot.send_message(admin_id, f"📦 New product: {data['name']} by {u['name']} ₦{data['price']}")
                except: pass

    elif action == "buy_product":
        price = int(data["price"])
        if u["balance"] < price and data.get("payment_method") == "instant":
            return await update.effective_message.reply_text("❌ Insufficient balance")
        orders.append({"buyer_id": user_id, "product_id": data["product_id"], "price": price, "payment_method": data.get("payment_method", "instant"), "status": "pending"})
        if data.get("payment_method") == "instant":
            u["balance"] -= price
            await update.effective_message.reply_text(f"✅ Order placed! -₦{price}")
        else:
            await update.effective_message.reply_text(f"✅ Order created. Payment: {data.get('payment_method')}")

    # === VIRTUAL NUMBERS ===
    elif action == "get_vnum_data":
        await update.effective_message.reply_web_app(json.dumps({"balance": u["balance"]}))

    elif action == "get_vnum_prices":
        service = data.get("service", "whatsapp")
        country_list = [
            {"code": "187", "name": "USA", "flag": "🇺🇸", "dial_code": "1"},
            {"code": "16", "name": "UK", "flag": "🇬🇧", "dial_code": "44"},
            {"code": "40", "name": "Nigeria", "flag": "🇳🇬", "dial_code": "234"},
            {"code": "6", "name": "Indonesia", "flag": "🇮🇩", "dial_code": "62"},
            {"code": "0", "name": "Russia", "flag": "🇷🇺", "dial_code": "7"},
        ]

        for c in country_list:
            custom = vnum_prices.get(c["code"], {}).get(service)
            c["price"] = custom if custom else get_vnum_price(c["code"], service)

        await update.effective_message.reply_web_app(json.dumps({"countries": country_list}))

    elif action == "buy_vnum":
        price = int(data["price"])
        if u["balance"] < price:
            return await update.effective_message.reply_text("❌ Insufficient balance")

        result = buy_vnum_number(data["country"], data["service"])
        if not result:
            return await update.effective_message.reply_text("❌ No numbers available. Try another country.")

        u["balance"] -= price
        vnum_orders.append({
            "user_id": user_id, "order_id": result["id"], "number": result["number"],
            "service": data["service"], "country": data["country"], "price": price, "status": "waiting"
        })
        await update.effective_message.reply_text(
            f"✅ Number: +{result['number']}\n\nWaiting for SMS...\nCode will be sent here automatically.\nValid 20 mins."
        )

    elif action == "confirm_deposit":
        await update.effective_message.reply_text("✅ Deposit noted. Credit within 5 mins.")
        for admin_id in ADMIN_IDS:
            try: await context.bot.send_message(admin_id, f"💵 Deposit: {u['name']} ({user_id})")
            except: pass

    elif action == "request_withdraw":
        amt = int(data["amount"])
        if u["balance"] < amt: return await update.effective_message.reply_text("❌ Insufficient balance")
        if amt < 500: return await update.effective_message.reply_text("❌ Min ₦500")

        u["balance"] -= amt
        await update.effective_message.reply_text(f"✅ Withdrawal sent!\n₦{amt} to {data['bank']} {data['account_number']}")
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, f"💸 WITHDRAW\nUser: {u['name']} ({user_id})\nAmount: ₦{amt}\nBank: {data['bank']}\nAcc: {data['account_number']}\nName: {data['account_name']}")
            except: pass

# === ADMIN COMMANDS ===
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return await update.message.reply_text("❌ Admin only")

    await update.message.reply_text(
        f"⚙️ ADMIN PANEL\n\n"
        f"Users: {len(users)}\nTotal Balance: ₦{sum(u['balance'] for u in users.values())}\n"
        f"Products: {len(products)}\nOrders: {len(orders)}\nVNum Orders: {len(vnum_orders)}\n\n"
        f"=== SETTINGS ===\n"
        f"Referral: ₦{settings['referral_bonus']}\nListing Fee: ₦{settings['listing_fee']}\n"
        f"VNum Markup: ₦{settings['vnum_markup']}\n\n"
        f"=== COMMANDS ===\n"
        f"/broadcast <msg>\n/credit <user_id> <amount>\n/addadmin <user_id>\n"
        f"/setbonus <amount>\n/setfee <amount>\n/setmarkup <amount>\n"
        f"/setvnumprice <country> <service> <price>\n/setapi <key>\n/setbank <bank> <acc> <name>\n/stats"
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    msg = " ".join(context.args)
    if not msg: return await update.message.reply_text("Usage: /broadcast <message>")
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(uid, f"📢 {msg}")
            count += 1
        except: pass
    await update.message.reply_text(f"✅ Sent to {count}")

async def credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        target_id, amount = int(context.args[0]), int(context.args[1])
        if target_id in users:
            users[target_id]["balance"] += amount
            await update.message.reply_text(f"✅ Credited ₦{amount} to {target_id}")
            await context.bot.send_message(target_id, f"💰 Admin credited ₦{amount}!\nBalance: ₦{users[target_id]['balance']}")
        else:
            await update.message.reply_text("❌ User not found")
    except: await update.message.reply_text("Usage: /credit <user_id> <amount>")

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        new_admin_id = int(context.args[0])
        if new_admin_id not in ADMIN_IDS:
            ADMIN_IDS.append(new_admin_id)
            await update.message.reply_text(f"✅ Added {new_admin_id} as admin")
            await context.bot.send_message(new_admin_id, "🎉 You are now admin!\nUse /admin")
        else:
            await update.message.reply_text("Already admin")
    except: await update.message.reply_text("Usage: /addadmin <user_id>")

async def setbonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        settings["referral_bonus"] = int(context.args[0])
        await update.message.reply_text(f"✅ Referral bonus: ₦{settings['referral_bonus']}")
    except: await update.message.reply_text("Usage: /setbonus <amount>")

async def setfee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        settings["listing_fee"] = int(context.args[0])
        await update.message.reply_text(f"✅ Listing fee: ₦{settings['listing_fee']}")
    except: await update.message.reply_text("Usage: /setfee <amount>")

async def setmarkup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        settings["vnum_markup"] = int(context.args[0])
        await update.message.reply_text(f"✅ VNum markup: ₦{settings['vnum_markup']}")
    except: await update.message.reply_text("Usage: /setmarkup <amount>")

async def setvnumprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        country, service, price = context.args[0], context.args[1], int(context.args[2])
        if country not in vnum_prices: vnum_prices[country] = {}
        vnum_prices[country][service] = price
        await update.message.reply_text(f"✅ Set {country} {service} to ₦{price}")
    except: await update.message.reply_text("Usage: /setvnumprice <country_code> <service> <price>\nEx: /setvnumprice 187 whatsapp 400")

async def setapi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        settings["vnum_api_key"] = context.args[0]
        await update.message.reply_text(f"✅ API key updated")
    except: await update.message.reply_text("Usage: /setapi <new_api_key>")

async def setbank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    try:
        settings["deposit_bank"] = context.args[0]
        settings["deposit_account"] = context.args[1]
        settings["deposit_name"] = " ".join(context.args[2:])
        await update.message.reply_text(f"✅ Deposit account updated")
    except: await update.message.reply_text("Usage: /setbank <bank> <account> <name>")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text(
        f"📊 STATS\n\nUsers: {len(users)}\nBalances: ₦{sum(u['balance'] for u in users.values())}\n"
        f"Referrals: {sum(u['referrals'] for u in users.values())}\nProducts: {len(products)}\n"
        f"Orders: {len(orders)}\nVNum Orders: {len(vnum_orders)}\nAdmins: {', '.join(map(str, ADMIN_IDS))}"
    )

# === MAIN ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("credit", credit))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("setbonus", setbonus))
    app.add_handler(CommandHandler("setfee", setfee))
    app.add_handler(CommandHandler("setmarkup", setmarkup))
    app.add_handler(CommandHandler("setvnumprice", setvnumprice))
    app.add_handler(CommandHandler("setapi", setapi))
    app.add_handler(CommandHandler("setbank", setbank))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))

    # Start SMS polling in background
    async def post_init(application):
        asyncio.create_task(poll_sms_codes(application))

    app.post_init = post_init

    print("Cashplug01_bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
