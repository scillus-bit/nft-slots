#!/usr/bin/env python3
"""
NFT Drops Bot — автономний, Stars платежі, реферали, SQLite
pip install python-telegram-bot aiosqlite
"""
import logging, asyncio, aiosqlite, os, json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, LabeledPrice
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, PreCheckoutQueryHandler, CallbackQueryHandler

BOT_TOKEN  = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://scillus-bit.github.io/nft-slots/nft_slots52.html")
ADMIN_ID   = int(os.getenv("ADMIN_ID", "0"))
DB_PATH    = "nftdrops.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PACKAGES = {
    "stars_50":  {"stars": 50,  "price": 50},
    "stars_150": {"stars": 150, "price": 150},
    "stars_300": {"stars": 300, "price": 300},
    "stars_700": {"stars": 700, "price": 700},
}

# ===== DATABASE =====
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, stars INTEGER DEFAULT 0,
            coupons INTEGER DEFAULT 0, referrer_id INTEGER DEFAULT NULL,
            referrals INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            type TEXT, amount INTEGER, note TEXT,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.commit()

async def get_user(user_id: int, username: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as c:
            row = await c.fetchone()
        if not row:
            await db.execute("INSERT INTO users (user_id, username) VALUES (?,?)", (user_id, username))
            await db.commit()
            return {"user_id": user_id, "username": username, "stars": 0, "coupons": 0, "referrals": 0}
        return {"user_id": row[0], "username": row[1], "stars": row[2], "coupons": row[3], "referrals": row[5]}

async def add_stars(user_id: int, amount: int, note: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET stars = stars + ? WHERE user_id=?", (amount, user_id))
        await db.execute("INSERT INTO transactions (user_id, type, amount, note) VALUES (?,?,?,?)", (user_id, "credit", amount, note))
        await db.commit()

async def add_coupon(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET coupons = coupons + 1 WHERE user_id=?", (user_id,))
        await db.commit()

async def handle_referral(new_user_id: int, referrer_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        # Check not already referred
        async with db.execute("SELECT referrer_id FROM users WHERE user_id=?", (new_user_id,)) as c:
            row = await c.fetchone()
        if row and row[0]: return  # already has referrer
        await db.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (referrer_id, new_user_id))
        await db.execute("UPDATE users SET referrals=referrals+1, coupons=coupons+1 WHERE user_id=?", (referrer_id,))
        await db.commit()

def main_kb(url):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 Open NFT Cases", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton("⭐ Buy Stars", callback_data="buy"), InlineKeyboardButton("📊 My Balance", callback_data="balance")],
        [InlineKeyboardButton("👥 Referral Link", callback_data="ref"), InlineKeyboardButton("❓ Help", callback_data="help")],
    ])

# ===== HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = await get_user(user.id, user.username or "")

    # Handle referral
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                ref_id = int(arg.replace("ref_", ""))
                if ref_id != user.id:
                    await handle_referral(user.id, ref_id)
                    await add_coupon(user.id)  # new user gets 1 coupon too
                    try:
                        await context.bot.send_message(ref_id,
                            f"🎟 *+1 Coupon!*\n\nYour friend @{user.username or user.first_name} joined via your referral!\n20 coupons = 1 free case open 🎁",
                            parse_mode="Markdown")
                    except: pass
            except: pass

    await update.message.reply_text(
        f"👋 Welcome, *{user.first_name}*!\n\n"
        "🌌 *NFT DROPS* — Web3 Case Opening\n\n"
        f"⭐ Your Stars: *{data['stars']}*\n"
        f"🎟 Coupons: *{data['coupons']}*\n\n"
        "Open cases and win real Telegram NFTs!\nBuy Stars to start playing 👇",
        parse_mode="Markdown",
        reply_markup=main_kb(WEBAPP_URL)
    )

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    payload = update.message.successful_payment.invoice_payload
    if payload in PACKAGES:
        pkg = PACKAGES[payload]
        await add_stars(user.id, pkg["stars"], f"Purchased {pkg['stars']} stars")
        await update.message.reply_text(
            f"✅ *Payment Successful!*\n\n"
            f"⭐ Added: *{pkg['stars']} Stars*\n\n"
            f"Open the game and start opening cases! 🎁",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎁 Open Cases", web_app=WebAppInfo(url=WEBAPP_URL))
            ]])
        )
        if ADMIN_ID:
            await context.bot.send_message(ADMIN_ID,
                f"💰 Payment: @{user.username or user.first_name} bought {pkg['stars']} Stars")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if query.data == "buy":
        kb = [
            [InlineKeyboardButton("⭐ 50 Stars — 50 XTR", callback_data="pkg_stars_50")],
            [InlineKeyboardButton("⭐ 150 Stars — 150 XTR", callback_data="pkg_stars_150")],
            [InlineKeyboardButton("⭐ 300 Stars — 300 XTR", callback_data="pkg_stars_300")],
            [InlineKeyboardButton("⭐ 700 Stars — 700 XTR", callback_data="pkg_stars_700")],
            [InlineKeyboardButton("◀️ Back", callback_data="back")],
        ]
        await query.message.edit_text(
            "⭐ *Buy Stars*\n\nChoose a package:\n\n"
            "50 ⭐ · 150 ⭐ · 300 ⭐ · 700 ⭐\n\n"
            "_Stars are stored permanently in your account_",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data.startswith("pkg_"):
        key = query.data.replace("pkg_", "")
        if key not in PACKAGES: return
        pkg = PACKAGES[key]
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=f"NFT Drops — {pkg['stars']} Stars",
            description=f"Purchase {pkg['stars']} Stars for case openings",
            payload=key, currency="XTR",
            prices=[LabeledPrice(f"{pkg['stars']} Stars", pkg["price"])],
            provider_token="")

    elif query.data == "balance":
        data = await get_user(user.id, user.username or "")
        await query.message.edit_text(
            f"📊 *Your Balance*\n\n"
            f"⭐ Stars: *{data['stars']}*\n"
            f"🎟 Coupons: *{data['coupons']}*\n"
            f"👥 Referrals: *{data['referrals']}*\n\n"
            f"_Stars are saved permanently!_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back")]]))

    elif query.data == "ref":
        link = f"https://t.me/{(await context.bot.get_me()).username}?start=ref_{user.id}"
        await query.message.edit_text(
            f"👥 *Referral System*\n\n"
            f"Invite friends and earn *1 Coupon* per referral!\n"
            f"🎟 *20 Coupons* = 1 free Common Case\n\n"
            f"Your link:\n`{link}`\n\n"
            f"Share it and start earning! 🚀",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back")]]))

    elif query.data == "help":
        await query.message.edit_text(
            "❓ *How to play:*\n\n"
            "1️⃣ Buy Stars via the Buy button\n"
            "2️⃣ Open the game and choose a case\n"
            "3️⃣ Each case costs Stars to open\n"
            "4️⃣ Win Stars or ultra-rare NFTs!\n"
            "5️⃣ Invite friends for free coupons\n\n"
            "🌌 NFT drop chance is ultra-rare\n"
            "⭐ Stars are saved permanently",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back")]]))

    elif query.data == "back":
        data = await get_user(user.id)
        await query.message.edit_text(
            f"👋 Welcome back, *{user.first_name}*!\n\n"
            "🌌 *NFT DROPS* — Web3 Case Opening\n\n"
            f"⭐ Stars: *{data['stars']}* · 🎟 Coupons: *{data['coupons']}*\n\n"
            "Open cases and win real Telegram NFTs! 🎁",
            parse_mode="Markdown", reply_markup=main_kb(WEBAPP_URL))

async def main():
    await init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    logger.info("🤖 NFT Drops Bot running!")
    await app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.get_event_loop().run_until_complete(main())
