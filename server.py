#!/usr/bin/env python3
"""
NFT King API Server — PostgreSQL версія
"""
import os, time, logging, json, hmac, hashlib
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg

app = Flask(__name__)
CORS(app)

BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
BOT_SECRET = os.getenv("BOT_SECRET", "nftking2025")
DATABASE_URL = os.getenv("DATABASE_URL", "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db():
    conn = psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT DEFAULT '',
            stars INTEGER DEFAULT 0,
            coupons INTEGER DEFAULT 0,
            referrer_id BIGINT DEFAULT NULL,
            referrals INTEGER DEFAULT 0,
            cases_opened INTEGER DEFAULT 0,
            nfts_won INTEGER DEFAULT 0,
            daily_last INTEGER DEFAULT 0,
            daily_day INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            created_at INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            case_name TEXT,
            prize TEXT,
            stars_spent INTEGER DEFAULT 0,
            stars_won INTEGER DEFAULT 0,
            ts INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Database initialized!")

# Init on startup
try:
    init_db()
except Exception as e:
    logger.error(f"DB init error: {e}")

# ===== DB HELPERS =====
def db_get_user(user_id: int, username: str = ""):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if not row:
        now = int(time.time())
        cur.execute(
            "INSERT INTO users (user_id, username, created_at) VALUES (%s, %s, %s) RETURNING *",
            (user_id, username, now)
        )
        row = cur.fetchone()
        conn.commit()
    cur.close()
    conn.close()
    return dict(row)

def db_update_stars(user_id: int, delta: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET stars = GREATEST(0, stars + %s) WHERE user_id = %s RETURNING stars",
        (delta, user_id)
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return row["stars"] if row else 0

def db_add_history(user_id, case_name, prize, spent, won):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO history (user_id, case_name, prize, stars_spent, stars_won, ts) VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, case_name, prize, spent, won, int(time.time()))
    )
    cur.execute(
        "UPDATE users SET cases_opened = cases_opened + 1 WHERE user_id = %s",
        (user_id,)
    )
    conn.commit()
    cur.close()
    conn.close()

def db_claim_daily(user_id: int, reward: int, day: int):
    now = int(time.time())
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET stars = stars + %s, daily_last = %s, daily_day = %s WHERE user_id = %s RETURNING stars",
        (reward, now, day, user_id)
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return row["stars"] if row else 0

def db_add_referral(new_user: int, ref_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT referrer_id FROM users WHERE user_id = %s", (new_user,))
    row = cur.fetchone()
    if row and row["referrer_id"]:
        cur.close()
        conn.close()
        return False
    cur.execute("UPDATE users SET referrer_id = %s WHERE user_id = %s", (ref_id, new_user))
    cur.execute("UPDATE users SET referrals = referrals + 1, coupons = coupons + 1 WHERE user_id = %s", (ref_id,))
    cur.execute("UPDATE users SET coupons = coupons + 1 WHERE user_id = %s", (new_user,))
    conn.commit()
    cur.close()
    conn.close()
    return True

def db_use_coupon(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT coupons FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    if not row or row["coupons"] < 20:
        cur.close()
        conn.close()
        return False
    cur.execute("UPDATE users SET coupons = coupons - 20 WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    return True

def db_get_history(user_id: int, limit: int = 10):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT case_name, prize, stars_spent, stars_won, ts FROM history WHERE user_id = %s ORDER BY ts DESC LIMIT %s",
        (user_id, limit)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"case": r["case_name"], "prize": r["prize"], "spent": r["stars_spent"], "won": r["stars_won"], "ts": r["ts"]} for r in rows]

# ===== ENDPOINTS =====

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "NFT King API", "db": "postgresql"})

@app.route("/api/user", methods=["POST"])
def get_user():
    data = request.json or {}
    user_id = data.get("user_id")
    username = data.get("username", "")
    if not user_id:
        return jsonify({"error": "no user_id"}), 400
    try:
        user = db_get_user(int(user_id), username)
        return jsonify(user)
    except Exception as e:
        logger.error(f"get_user error: {e}")
        return jsonify({"error": str(e)}), 500

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

    try:
        user = db_get_user(int(user_id))
        if not free and user["stars"] < cost:
            return jsonify({"error": "not_enough_stars", "stars": user["stars"]}), 400

        if not free:
            db_update_stars(int(user_id), -cost)
        if stars_won > 0:
            db_update_stars(int(user_id), stars_won)
        if is_nft:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE users SET nfts_won = nfts_won + 1 WHERE user_id = %s", (int(user_id),))
            conn.commit()
            cur.close()
            conn.close()

        db_add_history(int(user_id), case_name, prize, cost if not free else 0, stars_won)
        user = db_get_user(int(user_id))
        return jsonify({"success": True, "stars": user["stars"], "coupons": user["coupons"]})
    except Exception as e:
        logger.error(f"open_case error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/claim_daily", methods=["POST"])
def claim_daily():
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "no user_id"}), 400
    try:
        user = db_get_user(int(user_id))
        now = int(time.time())
        if now - user.get("daily_last", 0) < 86400:
            return jsonify({"error": "already_claimed", "next": user["daily_last"] + 86400}), 400
        day = (user.get("daily_day", 0) % 7) + 1
        rewards = [1, 1, 2, 2, 3, 3, 5]
        reward = rewards[day - 1]
        stars = db_claim_daily(int(user_id), reward, day)
        return jsonify({"success": True, "reward": reward, "day": day, "stars": stars})
    except Exception as e:
        logger.error(f"claim_daily error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/referral", methods=["POST"])
def referral():
    data = request.json or {}
    new_user = data.get("user_id")
    ref_id = data.get("ref_id")
    if not new_user or not ref_id:
        return jsonify({"error": "missing params"}), 400
    try:
        success = db_add_referral(int(new_user), int(ref_id))
        return jsonify({"success": success})
    except Exception as e:
        logger.error(f"referral error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/use_coupon", methods=["POST"])
def use_coupon():
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "no user_id"}), 400
    try:
        success = db_use_coupon(int(user_id))
        if not success:
            return jsonify({"error": "not_enough_coupons"}), 400
        user = db_get_user(int(user_id))
        return jsonify({"success": True, "coupons": user["coupons"]})
    except Exception as e:
        logger.error(f"use_coupon error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/history", methods=["POST"])
def history():
    data = request.json or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "no user_id"}), 400
    try:
        hist = db_get_history(int(user_id))
        return jsonify({"history": hist})
    except Exception as e:
        logger.error(f"history error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/add_stars", methods=["POST"])
def add_stars():
    secret = request.headers.get("X-Bot-Secret", "")
    if secret != BOT_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    data = request.json or {}
    user_id = data.get("user_id")
    amount = data.get("amount", 0)
    if not user_id or amount <= 0:
        return jsonify({"error": "invalid params"}), 400
    try:
        db_get_user(int(user_id))  # ensure user exists
        stars = db_update_stars(int(user_id), amount)
        return jsonify({"success": True, "stars": stars})
    except Exception as e:
        logger.error(f"add_stars error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    secret = request.headers.get("X-Bot-Secret", "")
    if secret != BOT_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM users")
        users = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as cnt FROM history")
        cases = cur.fetchone()["cnt"]
        cur.execute("SELECT COALESCE(SUM(stars), 0) as total FROM users")
        stars = cur.fetchone()["total"]
        cur.close()
        conn.close()
        return jsonify({"users": users, "cases": cases, "stars": stars})
    except Exception as e:
        logger.error(f"admin_stats error: {e}")
        return jsonify({"error": str(e)}), 500
@app.route("/api/set_stars", methods=["POST"])
def set_stars():
    secret = request.headers.get("X-Bot-Secret", "")
    if secret != BOT_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    data = request.json or {}
    user_id = data.get("user_id")
    amount = data.get("amount", 0)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET stars = %s WHERE user_id = %s RETURNING stars", (int(amount), int(user_id)))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True, "stars": row["stars"]})
    @app.route("/api/casino_grant", methods=["POST"])
def casino_grant():
    secret = request.headers.get("X-Bot-Secret", "")
    if secret != BOT_SECRET:
        return jsonify({"error": "unauthorized"}), 401
    data = request.json or {}
    user_id = data.get("user_id")
    grant = data.get("grant", "1")
    today = time.strftime("%Y-%m-%d")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS casino_grants (
        user_id BIGINT, date TEXT, extra_spins INTEGER DEFAULT 0,
        unlimited BOOLEAN DEFAULT FALSE, PRIMARY KEY (user_id, date))""")
    if grant == "unlimited":
        cur.execute("""INSERT INTO casino_grants VALUES (%s,%s,0,TRUE)
            ON CONFLICT (user_id,date) DO UPDATE SET unlimited=TRUE""", (int(user_id), today))
    else:
        cur.execute("""INSERT INTO casino_grants VALUES (%s,%s,%s,FALSE)
            ON CONFLICT (user_id,date) DO UPDATE SET extra_spins=casino_grants.extra_spins+%s""",
            (int(user_id), today, int(grant), int(grant)))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True})
    @app.route("/api/casino_check", methods=["POST"])
def casino_check():
    data = request.json or {}
    user_id = data.get("user_id")
    today = time.strftime("%Y-%m-%d")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT extra_spins, unlimited FROM casino_grants WHERE user_id=%s AND date=%s", (int(user_id), today))
    row = cur.fetchone()
    cur.execute("""CREATE TABLE IF NOT EXISTS casino_spins (
        user_id BIGINT, date TEXT, spins_used INTEGER DEFAULT 0, PRIMARY KEY(user_id,date))""")
    cur.execute("SELECT spins_used FROM casino_spins WHERE user_id=%s AND date=%s", (int(user_id), today))
    spin_row = cur.fetchone()
    cur.close(); conn.close()
    extra = row["extra_spins"] if row else 0
    unlimited = row["unlimited"] if row else False
    used = spin_row["spins_used"] if spin_row else 0
    return jsonify({"unlimited": unlimited, "spins_left": 999 if unlimited else max(0, 1+extra-used)})
    @app.route("/api/casino_spin", methods=["POST"])
def casino_spin():
    data = request.json or {}
    user_id = data.get("user_id")
    today = time.strftime("%Y-%m-%d")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT extra_spins, unlimited FROM casino_grants WHERE user_id=%s AND date=%s", (int(user_id), today))
    grant = cur.fetchone()
    cur.execute("SELECT spins_used FROM casino_spins WHERE user_id=%s AND date=%s", (int(user_id), today))
    spin_row = cur.fetchone()
    extra = grant["extra_spins"] if grant else 0
    unlimited = grant["unlimited"] if grant else False
    used = spin_row["spins_used"] if spin_row else 0
    if not unlimited and used >= 1 + extra:
        cur.close(); conn.close()
        return jsonify({"error": "limit_reached"}), 403
    cur.execute("""INSERT INTO casino_spins VALUES (%s,%s,1)
        ON CONFLICT (user_id,date) DO UPDATE SET spins_used=casino_spins.spins_used+1""", (int(user_id), today))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"success": True, "spins_left": 999 if unlimited else max(0, extra-used)})
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
