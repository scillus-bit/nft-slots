#!/usr/bin/env python3
import logging, os
import requests as req
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, LabeledPrice
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, PreCheckoutQueryHandler, CallbackQueryHandler
import nest_asyncio
nest_asyncio.apply()

BOT_TOKEN  = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://scillus-bit.github.io/nft-slots/nft_slots.html")
ADMIN_ID   = int(os.getenv("ADMIN_ID", "0"))
API_URL    = os.getenv("API_URL", "http://localhost:5000")
BOT_SECRET = os.getenv("BOT_SECRET", "nftking2025")
ADMIN_PASS = os.getenv("ADMIN_PASS", "Bob20173925+")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

admin_sessions = {}
waiting_for = {}

PACKAGES = {
    "pkg_50":  {"stars": 50,  "price": 50},
    "pkg_150": {"stars": 150, "price": 150},
    "pkg_300": {"stars": 300, "price": 300},
    "pkg_700": {"stars": 700, "price": 700},
}

def api_call(endpoint, body, secret=False):
    try:
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-Bot-Secret"] = BOT_SECRET
        url = f"{API_URL}{endpoint}"
        logger.info(f"API CALL: {url} body={body}")
        r = req.post(url, json=body, headers=headers, timeout=10)
        logger.info(f"API RESPONSE: {r.status_code} {r.text[:200]}")
        return r.json()
    except Exception as e:
        logger.error(f"API ERROR: {e}")
        return {}

def api_get_user(user_id, username=""):
    return api_call("/api/user", {"user_id": user_id, "username": username})

def api_add_stars(user_id, amount):
    result = api_call("/api/add_stars", {"user_id": user_id, "amount": amount}, secret=True)
    logger.info(f"ADD STARS RESULT for {user_id}: {result}")
    return result

def api_take_stars(user_id, amount):
    # Take stars = add negative amount (uses GREATEST(0,...) so won't go below 0)
    result = api_call("/api/add_stars", {"user_id": user_id, "amount": -amount}, secret=True)
    logger.info(f"TAKE STARS RESULT for {user_id}: {result}")
    return result

def main_kb(url):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Open NFT Cases", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton("⭐ Buy Stars", callback_data="buy"),
         InlineKeyboardButton("📊 Balance", callback_data="balance")],
        [InlineKeyboardButton("👥 Referral", callback_data="ref"),
         InlineKeyboardButton("❓ Help", callback_data="help")],
    ])

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Give 1000 Stars to me", callback_data="adm_give_1000")],
        [InlineKeyboardButton("⭐ Give 500 Stars to me", callback_data="adm_give_500")],
        [InlineKeyboardButton("⭐ Give 100 Stars to me", callback_data="adm_give_100")],
        [InlineKeyboardButton("👤 Give Stars to user", callback_data="adm_give_user")],
        [InlineKeyboardButton("🔻 Take Stars from user", callback_data="adm_take_user")],
        [InlineKeyboardButton("📊 Stats", callback_data="adm_stats")],
        [InlineKeyboardButton("🔒 Logout", callback_data="adm_logout")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = api_get_user(user.id, user.username or "")

    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                ref_id = int(arg.replace("ref_", ""))
                if ref_id != user.id:
                    res = api_call("/api/referral", {"user_id": user.id, "ref_id": ref_id})
                    if res.get("success"):
                        try:
                            await context.bot.send_message(
                                ref_id,
                                f"🎟 *+1 Coupon!*\n\nFriend @{user.username or user.first_name} joined!\n20 coupons = 1 free case 🎁",
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            logger.error(f"Send message error: {e}")
            except Exception as e:
                logger.error(f"Referral error: {e}")
        elif arg.startswith("invoice_"):
            key = arg.replace("invoice_", "")
            if key in PACKAGES:
                pkg = PACKAGES[key]
                await context.bot.send_invoice(
                    chat_id=user.id,
                    title=f"NFT King — {pkg['stars']} Stars",
                    description=f"Purchase {pkg['stars']} Stars for case openings",
                    payload=key,
                    currency="XTR",
                    prices=[LabeledPrice(f"{pkg['stars']} Stars", pkg["price"])],
                    provider_token=""
                )
                return
        elif arg == "admin":
            if user.id == ADMIN_ID or admin_sessions.get(user.id):
                await update.message.reply_text(
                    "👑 *Admin Panel*",
                    parse_mode="Markdown",
                    reply_markup=admin_kb()
                )
                return

    await update.message.reply_text(
        f"👋 Welcome, *{user.first_name}*!\n\n"
        "🌌 *NFT KING* — Web3 Case Opening\n\n"
        f"⭐ Stars: *{data.get('stars', 0)}*\n"
        f"🎟 Coupons: *{data.get('coupons', 0)}*\n\n"
        "Open cases and win NFTs! 🎁",
        parse_mode="Markdown",
        reply_markup=main_kb(WEBAPP_URL)
    )

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if admin_sessions.get(user.id):
        await update.message.reply_text(
            "👑 *Admin Panel*",
            parse_mode="Markdown",
            reply_markup=admin_kb()
        )
        return
    waiting_for[user.id] = "admin_pass"
    await update.message.reply_text(
        "🔐 *Admin Access*\n\nEnter the admin password:",
        parse_mode="Markdown"
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    payload = update.message.successful_payment.invoice_payload
    if payload in PACKAGES:
        pkg = PACKAGES[payload]
        result = api_add_stars(user.id, pkg["stars"])
        data = api_get_user(user.id)
        await update.message.reply_text(
            f"✅ *Payment Successful!*\n\n"
            f"⭐ Added: *{pkg['stars']} Stars*\n"
            f"💰 Balance: *{data.get('stars', 0)} Stars*\n\n"
            f"Open the game and start playing! 🎁",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎁 Open Cases", web_app=WebAppInfo(url=WEBAPP_URL))
            ]])
        )
        if ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                f"💰 *New Purchase!*\n\n"
                f"👤 User: @{user.username or user.first_name} (`{user.id}`)\n"
                f"⭐ Bought: *{pkg['stars']} Stars*\n"
                f"💵 Paid: *{pkg['price']} XTR*",
                parse_mode="Markdown"
            )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    # Admin password
    if waiting_for.get(user.id) == "admin_pass":
        del waiting_for[user.id]
        if text == ADMIN_PASS:
            admin_sessions[user.id] = True
            await update.message.reply_text(
                "✅ *Access granted!*\n\n👑 Welcome to Admin Panel",
                parse_mode="Markdown",
                reply_markup=admin_kb()
            )
        else:
            await update.message.reply_text("❌ Wrong password!")
        return

    # Give stars — get user ID
    if waiting_for.get(user.id) == "adm_user_id":
        try:
            target_id = int(text)
            waiting_for[user.id] = {"action": "adm_user_stars", "target_id": target_id}
            await update.message.reply_text(
                f"✅ User ID: `{target_id}`\nNow enter amount of stars to GIVE:",
                parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text("❌ Invalid user ID! Enter a number.")
        return

    # Give stars — get amount
    if isinstance(waiting_for.get(user.id), dict) and waiting_for[user.id].get("action") == "adm_user_stars":
        try:
            amount = int(text)
            target_id = waiting_for[user.id]["target_id"]
            del waiting_for[user.id]
            res = api_add_stars(target_id, amount)
            if res.get("success"):
                await update.message.reply_text(
                    f"✅ *Done!*\n\n⭐ Added *{amount} Stars* to user `{target_id}`\nNew balance: *{res.get('stars', 0)}*",
                    parse_mode="Markdown",
                    reply_markup=admin_kb()
                )
                # Notify user
                try:
                    await context.bot.send_message(
                        target_id,
                        f"🎁 *You received {amount} Stars from admin!*\n\nYour new balance: *{res.get('stars', 0)} ⭐*",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            else:
                await update.message.reply_text(f"❌ Error! Response: {res}", reply_markup=admin_kb())
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}", reply_markup=admin_kb())
        return

    # Take stars — get user ID
    if waiting_for.get(user.id) == "adm_take_user_id":
        try:
            target_id = int(text)
            waiting_for[user.id] = {"action": "adm_take_user_stars", "target_id": target_id}
            await update.message.reply_text(
                f"✅ User ID: `{target_id}`\nNow enter amount of stars to TAKE:",
                parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text("❌ Invalid user ID! Enter a number.")
        return

    # Take stars — get amount
    if isinstance(waiting_for.get(user.id), dict) and waiting_for[user.id].get("action") == "adm_take_user_stars":
        try:
            amount = int(text)
            target_id = waiting_for[user.id]["target_id"]
            del waiting_for[user.id]
            # Get current balance first
            user_data = api_get_user(target_id)
            current = user_data.get("stars", 0)
            res = api_take_stars(target_id, amount)
            if res.get("success") is not False:
                taken = min(amount, current)
                await update.message.reply_text(
                    f"✅ *Done!*\n\n🔻 Took *{taken} Stars* from user `{target_id}`\nNew balance: *{res.get('stars', 0)}*",
                    parse_mode="Markdown",
                    reply_markup=admin_kb()
                )
                # Notify user
                try:
                    await context.bot.send_message(
                        target_id,
                        f"⚠️ *{taken} Stars were deducted from your balance by admin.*\n\nYour new balance: *{res.get('stars', 0)} ⭐*",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
            else:
                await update.message.reply_text(f"❌ Error! Response: {res}", reply_markup=admin_kb())
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}", reply_markup=admin_kb())
        return

    # Withdraw request from WebApp — admin notification
    if waiting_for.get(user.id) == "withdraw_pending":
        del waiting_for[user.id]
        return

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data.startswith("adm_"):
        if not admin_sessions.get(user.id):
            await query.message.edit_text("❌ Not authorized! Use /admin")
            return

        if query.data == "adm_give_1000":
            res = api_add_stars(user.id, 1000)
            stars = res.get('stars', '?')
            await query.message.edit_text(
                f"✅ *+1000 Stars added!*\n\nNew balance: *{stars} Stars*",
                parse_mode="Markdown",
                reply_markup=admin_kb()
            )

        elif query.data == "adm_give_500":
            res = api_add_stars(user.id, 500)
            stars = res.get('stars', '?')
            await query.message.edit_text(
                f"✅ *+500 Stars added!*\n\nNew balance: *{stars} Stars*",
                parse_mode="Markdown",
                reply_markup=admin_kb()
            )

        elif query.data == "adm_give_100":
            res = api_add_stars(user.id, 100)
            stars = res.get('stars', '?')
            await query.message.edit_text(
                f"✅ *+100 Stars added!*\n\nNew balance: *{stars} Stars*",
                parse_mode="Markdown",
                reply_markup=admin_kb()
            )

        elif query.data == "adm_give_user":
            waiting_for[user.id] = "adm_user_id"
            await query.message.edit_text(
                "👤 *Give Stars to User*\n\nEnter the Telegram user ID:",
                parse_mode="Markdown"
            )

        elif query.data == "adm_take_user":
            waiting_for[user.id] = "adm_take_user_id"
            await query.message.edit_text(
                "🔻 *Take Stars from User*\n\nEnter the Telegram user ID:",
                parse_mode="Markdown"
            )

        elif query.data == "adm_stats":
            try:
                r = req.get(
                    f"{API_URL}/api/admin/stats",
                    headers={"X-Bot-Secret": BOT_SECRET},
                    timeout=5
                )
                stats = r.json()
                await query.message.edit_text(
                    f"📊 *Bot Statistics*\n\n"
                    f"👥 Total users: *{stats.get('users', 0)}*\n"
                    f"📦 Cases opened: *{stats.get('cases', 0)}*\n"
                    f"⭐ Stars in DB: *{stats.get('stars', 0)}*",
                    parse_mode="Markdown",
                    reply_markup=admin_kb()
                )
            except Exception as e:
                await query.message.edit_text(f"❌ API error: {e}", reply_markup=admin_kb())

        elif query.data == "adm_logout":
            admin_sessions.pop(user.id, None)
            await query.message.edit_text("🔒 Logged out from admin panel.")

        return

    if query.data == "buy":
        kb = [
            [InlineKeyboardButton("⭐ 50 Stars — 50 XTR", callback_data="pay_pkg_50")],
            [InlineKeyboardButton("⭐ 150 Stars — 150 XTR", callback_data="pay_pkg_150")],
            [InlineKeyboardButton("⭐ 300 Stars — 300 XTR", callback_data="pay_pkg_300")],
            [InlineKeyboardButton("⭐ 700 Stars — 700 XTR", callback_data="pay_pkg_700")],
            [InlineKeyboardButton("◀️ Back", callback_data="back")],
        ]
        await query.message.edit_text(
            "⭐ *Buy Stars*\n\nChoose a package:\n\n_Stars are saved permanently!_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif query.data.startswith("pay_"):
        key = query.data.replace("pay_", "")
        if key not in PACKAGES:
            return
        pkg = PACKAGES[key]
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=f"NFT King — {pkg['stars']} Stars",
            description=f"Purchase {pkg['stars']} Stars for case openings",
            payload=key,
            currency="XTR",
            prices=[LabeledPrice(f"{pkg['stars']} Stars", pkg["price"])],
            provider_token=""
        )

    elif query.data == "balance":
        data = api_get_user(user.id, user.username or "")
        await query.message.edit_text(
            f"📊 *Your Balance*\n\n"
            f"⭐ Stars: *{data.get('stars', 0)}*\n"
            f"🎟 Coupons: *{data.get('coupons', 0)}*\n"
            f"👥 Referrals: *{data.get('referrals', 0)}*\n"
            f"📦 Cases opened: *{data.get('cases_opened', 0)}*\n\n"
            f"_Stars are saved permanently!_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back")]])
        )

    elif query.data == "ref":
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=ref_{user.id}"
        await query.message.edit_text(
            f"👥 *Referral System*\n\n"
            f"Invite friends → get *1 Coupon* each!\n"
            f"🎟 *20 Coupons* = 1 free Common Case\n\n"
            f"Your link:\n`{link}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back")]])
        )

    elif query.data == "help":
        await query.message.edit_text(
            "❓ *How to play:*\n\n"
            "1️⃣ Buy Stars via ⭐ button\n"
            "2️⃣ Open the game and pick a case\n"
            "3️⃣ Win Stars or ultra-rare NFTs!\n"
            "4️⃣ Lucky Pick — choose your bet!\n"
            "5️⃣ Casino — pick your odds!\n"
            "6️⃣ Invite friends for coupons\n\n"
            "🌌 NFT drop is ultra-rare\n"
            "⭐ Stars saved permanently",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back")]])
        )

    elif query.data == "back":
        data = api_get_user(user.id)
        await query.message.edit_text(
            f"👋 *NFT KING* — Web3 Case Opening\n\n"
            f"⭐ Stars: *{data.get('stars', 0)}* · 🎟 Coupons: *{data.get('coupons', 0)}*\n\n"
            "Open cases and win NFTs! 🎁",
            parse_mode="Markdown",
            reply_markup=main_kb(WEBAPP_URL)
        )

async def withdraw_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle withdraw notifications sent from WebApp via bot API"""
    pass

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("🤖 NFT King Bot running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
