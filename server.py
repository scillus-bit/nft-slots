#!/usr/bin/env python3
"""
NFT King — Flask API Server
Синхронізує баланс між ботом і WebApp
"""
import os, asyncio, logging, aiosqlite, json
from flask import Flask, request, jsonify
from flask_cors import CORS
import hashlib, hmac, time
from threading import Thread

app = Flask(__name__)
CORS(app)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH   = "nftking.db"

logging.basicConfig(level=logging.INFO)

# ===== DB =====
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            stars INTEGER DEFAULT 0,
            coupons INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT NULL,
            referrals INTEGER DEFAULT 0,
            cases_opened INTEGER DEFAULT 0,
            nfts_won INTEGER DEFAULT 0,
            daily_last INTEGER DEFAULT 0,
            daily_day INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            created_at INTEGER DEFAULT 0
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            case_name TEXT,
            prize TEXT,
            stars_spent INTEGER DEFAULT 0,
            stars_won INTEGER DEFAULT 0,
            ts INTEGER DEFAULT 0
        )""")
        await db.commit()

def run_async(coro):
    loop = asyncio.new_event_loop()
    result = loop.run_until_complete(coro)
    loop.close()
    return result

async def _get_user(user_id: int, username: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as c:
            row = await c.fetchone()
        if not row:
            now = int(time.time())
            await db.execute(
                "INSERT INTO users (user_id, username, created_at) VALUES (?,?,?)",
                (user_id, username, now)
            )
            await db.commit()
            return {"user_id": user_id, "username": username, "stars": 0, "coupons": 0,
                    "referrals": 0, "cases_opened": 0, "nfts_won": 0,
                    "daily_last": 0, "daily_day": 0, "xp": 0, "level": 1}
        cols = ["user_id","username","stars","coupons","referrer_id","referrals",
                "cases_opened","nfts_won","daily_last","daily_day","xp","level","created_at"]
        return dict(zip(cols, row))

async def _update_stars(user_id: int, delta: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET stars = MAX(0, stars + ?) WHERE user_id=?", (delta, user_id))
        await db.commit()

async def _add_history(user_id, case_name, prize, spent, won):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO history (user_id, case_name, prize, stars_spent, stars_won, ts) VALUES (?,?,?,?,?,?)",
            (user_id, case_name, prize, spent, won, int(time.time()))
        )
        await db.execute("UPDATE users SET cases_opened=cases_opened+1, stars_spent=COALESCE(stars_spent,0)+? WHERE user_id=?", (spent, user_id))
        await db.commit()

async def _claim_daily(user_id: int, reward: int, day: int):
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET stars=stars+?, daily_last=?, daily_day=? WHERE user_id=?",
            (reward, now, day, user_id)
        )
        await db.commit()

async def _add_referral(new_user: int, ref_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT referrer_id FROM users WHERE user_id=?", (new_user,)) as c:
            row = await c.fetchone()
        if row and row[0]: return False
        await db.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (ref_id, new_user))
        await db.execute("UPDATE users SET referrals=referrals+1, coupons=coupons+1 WHERE user_id=?", (ref_id,))
        await db.execute("UPDATE users SET coupons=coupons+1 WHERE user_id=?", (new_user,))
        await db.commit()
        return True

async def _use_coupon(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT coupons FROM users WHERE user_id=?", (user_id,)) as c:
            row = await c.fetchone()
        if not row or row[0] < 20: return False
        await db.execute("UPDATE users SET coupons=coupons-20 WHERE user_id=?", (user_id,))
        await db.commit()
        return True

async def _get_history(user_id: int, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT case_name, prize, stars_spent, stars_won, ts FROM history WHERE user_id=? ORDER BY ts DESC LIMIT ?",
            (user_id, limit)
        ) as c:
            rows = await c.fetchall()
    return [{"case": r[0], "prize": r[1], "spent": r[2], "won": r[3], "ts": r[4]} for r in rows]

# ===== TELEGRAM VALIDATION =====
def validate_init_data(init_data: str) -> dict | None:
    """Перевірити підпис Telegram WebApp initData"""
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = {}
        pairs = [p.split("=", 1) for p in init_data.split("&")]
        for k, v in pairs:
            parsed[k] = v

        hash_val = parsed.pop("hash", "")
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected, hash_val):
            return None

        user_str = parsed.get("user", "{}")
        return json.loads(user_str)
    except:
        return None

def get_user_from_request():
    """Отримати user_id з запиту"""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_init_data(init_data)
    if user:
        return user.get("id"), user.get("username", "")
    # Dev fallback
    uid = request.json.get("user_id") if request.is_json else None
    return uid, ""

# ===== API ENDPOINTS =====

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "NFT King API"})

@app.route("/api/user", methods=["POST"])
def get_user():
    data = request.json or {}
    user_id = data.get("user_id")
    username = data.get("username", "")
    if not user_id:
        return jsonify({"error": "no user_id"}), 400
    user = run_async(_get_user(int(user_id), username))
    return jsonify(user)

@app.route("/api/open_case", methods=["POST"])
def open_case():
    data = request.json or {}
    user_id = data.get("user_id")
    case_name = data.get("case_name", "Unknown")
    cost = data.get("cost", 0)
    prize = data.get("prize", "Nothing")
    stars_won = data.get("stars_won", 0)
    is_nft = data.get("is_nft", False)
    free = data.get("free", False)

    if not user_id:
        return jsonify({"error": "no user_id"}), 400

    user = run_async(_get_user(int(user_id)))
    if not free and user["stars"] < cost:
        return jsonify({"error": "not_enough_stars", "stars": user["stars"]}), 400

    # Deduct cost
    if not free:
        run_async(_update_stars(int(user_id), -cost))
    # Add won stars
    if stars_won > 0:
        run_async(_update_stars(int(user_id), stars_won))
    if is_nft:
        async def _mark_nft(uid):
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET nfts_won=nfts_won+1 WHERE user_id=?", (uid,))
                await db.commit()
        run_async(_mark_nft(int(user_id)))

    run_async(_add_history(int(user_id), case_name, prize, cost if not free else 0, stars_won))

    user = run_async(_get_user(int(user_id)))
    return jsonify({"success": True, "stars": user["stars"], "coupons": user["coupons"]})

@app.route("/api/claim_daily", methods=["POST"])
def claim_daily():
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "no user_id"}), 400

    user = run_async(_get_user(int(user_id)))
    now = int(time.time())
    last = user.get("daily_last", 0)

    if now - last < 86400:
        return jsonify({"error": "already_claimed", "next": last + 86400}), 400

    day = (user.get("daily_day", 0) % 7) + 1
    rewards = [1, 1, 2, 2, 3, 3, 5]
    reward = rewards[day - 1]

    run_async(_claim_daily(int(user_id), reward, day))
    user = run_async(_get_user(int(user_id)))
    return jsonify({"success": True, "reward": reward, "day": day, "stars": user["stars"]})

@app.route("/api/referral", methods=["POST"])
def referral():
    data = request.json or {}
    new_user = data.get("user_id")
    ref_id = data.get("ref_id")
    if not new_user or not ref_id:
        return jsonify({"error": "missing params"}), 400
    success = run_async(_add_referral(int(new_user), int(ref_id)))
    return jsonify({"success": success})

@app.route("/api/use_coupon", methods=["POST"])
def use_coupon():
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "no user_id"}), 400
    success = run_async(_use_coupon(int(user_id)))
    if not success:
        return jsonify({"error": "not_enough_coupons"}), 400
    user = run_async(_get_user(int(user_id)))
    return jsonify({"success": True, "coupons": user["coupons"]})

@app.route("/api/history", methods=["POST"])
def history():
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "no user_id"}), 400
    hist = run_async(_get_history(int(user_id)))
    return jsonify({"history": hist})

@app.route("/api/add_stars", methods=["POST"])
def add_stars_endpoint():
    """Викликається ботом після Stars платежу"""
    secret = request.headers.get("X-Bot-Secret", "")
    if secret != os.getenv("BOT_SECRET", "nftking2025"):
        return jsonify({"error": "unauthorized"}), 401
    data = request.json or {}
    user_id = data.get("user_id")
    amount = data.get("amount", 0)
    if not user_id or amount <= 0:
        return jsonify({"error": "invalid params"}), 400
    run_async(_update_stars(int(user_id), amount))
    user = run_async(_get_user(int(user_id)))
    return jsonify({"success": True, "stars": user["stars"]})

@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    secret = request.headers.get("X-Bot-Secret", "")
    if secret != os.getenv("BOT_SECRET", "nftking2025"):
        return jsonify({"error": "unauthorized"}), 401
    async def _stats():
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as c:
                users = (await c.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM history") as c:
                cases = (await c.fetchone())[0]
            async with db.execute("SELECT SUM(stars) FROM users") as c:
                stars = (await c.fetchone())[0] or 0
        return {"users": users, "cases": cases, "stars": stars}
    return jsonify(run_async(_stats()))

if __name__ == "__main__":
    run_async(init_db())
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
