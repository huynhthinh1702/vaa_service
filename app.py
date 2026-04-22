from flask import Flask, request, jsonify, render_template, session, Response
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from datetime import timedelta

import sqlite3
import os
import shutil
from dotenv import load_dotenv

print("SMTP_HOST =", os.getenv("SMTP_HOST"))

import base64
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

import csv
from io import StringIO
from pathlib import Path
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "123456"
app.permanent_session_lifetime = timedelta(days=30)
CORS(app)
DB_PATH = Path(app.root_path) / "airport.db"

# Hàm kết nối DB
def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def ensure_service_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(service)")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    migration_columns = {
        "location": "TEXT",
        "position": "TEXT",
        "usage_hours": "TEXT",
        "amenities": "TEXT"
    }

    for col_name, col_type in migration_columns.items():
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE service ADD COLUMN {col_name} {col_type}")

    conn.commit()
    conn.close()

def ensure_passenger_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(passenger)")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    # Payment status: Paid / Unpaid (default Unpaid)
    if "payment_status" not in existing_cols:
        cursor.execute("ALTER TABLE passenger ADD COLUMN payment_status TEXT DEFAULT 'Unpaid'")

    # Link passenger to logged-in user for user history
    if "username" not in existing_cols:
        cursor.execute("ALTER TABLE passenger ADD COLUMN username TEXT")

    # Backfill: if passenger has any booking -> mark Paid (best-effort for existing data)
    try:
        cursor.execute("""
            UPDATE passenger
            SET payment_status='Paid'
            WHERE id IN (SELECT DISTINCT passenger_id FROM booking_service)
        """)
    except Exception:
        pass

    conn.commit()
    conn.close()

ensure_service_schema()
ensure_passenger_schema()

def ensure_user_activity_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            event_type TEXT NOT NULL,
            service_id INTEGER,
            category TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def ensure_restaurant_reservation_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS restaurant_reservation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            service_id INTEGER NOT NULL,
            reserved_date TEXT NOT NULL,
            reserved_time TEXT NOT NULL,
            pax INTEGER NOT NULL,
            contact_name TEXT NOT NULL,
            contact_phone TEXT NOT NULL,
            note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

ensure_user_activity_schema()
ensure_restaurant_reservation_schema()

def ensure_restaurant_reservation_paid_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(restaurant_reservation)")
    existing_cols = {row["name"] for row in cursor.fetchall()}
    if "paid_at" not in existing_cols:
        cursor.execute("ALTER TABLE restaurant_reservation ADD COLUMN paid_at DATETIME")
    conn.commit()
    conn.close()

def ensure_booking_service_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(booking_service)")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    if "using_date" not in existing_cols:
        cursor.execute("ALTER TABLE booking_service ADD COLUMN using_date TEXT")

    if "paid_at" not in existing_cols:
        cursor.execute("ALTER TABLE booking_service ADD COLUMN paid_at DATETIME")

    if "order_code" not in existing_cols:
        cursor.execute("ALTER TABLE booking_service ADD COLUMN order_code TEXT")

    # Backfill order_code (best-effort)
    try:
        cursor.execute("SELECT id, order_code FROM booking_service")
        rows = cursor.fetchall()
        for r in rows:
            if not (r["order_code"] or "").strip():
                code = f"ORD{int(r['id']):06d}"
                cursor.execute("UPDATE booking_service SET order_code=? WHERE id=?", (code, r["id"]))
    except Exception:
        pass

    conn.commit()
    conn.close()

def ensure_user_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(user)")
    existing_cols = {row["name"] for row in cursor.fetchall()}

    if "is_active" not in existing_cols:
        cursor.execute("ALTER TABLE user ADD COLUMN is_active INTEGER DEFAULT 1")

    try:
        cursor.execute("UPDATE user SET is_active=1 WHERE is_active IS NULL")
    except Exception:
        pass

    conn.commit()
    conn.close()

def ensure_service_image_schema():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS service_image (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def ensure_performance_indexes():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_username ON user(username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_is_active ON user(is_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_service_category ON service(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_booking_created ON booking_service(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_booking_service_id ON booking_service(service_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_booking_passenger_id ON booking_service(passenger_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reservation_created ON restaurant_reservation(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reservation_service_id ON restaurant_reservation(service_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_service_image_service_id ON service_image(service_id)")
    conn.commit()
    conn.close()

def ensure_user_profile_columns():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(user)")
    existing_cols = {row["name"] for row in cursor.fetchall()}
    if "gender" not in existing_cols:
        cursor.execute("ALTER TABLE user ADD COLUMN gender TEXT")
    conn.commit()
    conn.close()

ensure_restaurant_reservation_paid_schema()
ensure_booking_service_schema()
ensure_user_schema()
ensure_user_profile_columns()
ensure_service_image_schema()
ensure_performance_indexes()

def to_is_active(value, default=1):
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("0", "false", "no", "off"):
        return 0
    if text in ("1", "true", "yes", "on"):
        return 1
    return default

def parse_pagination(default_size=20, max_size=100):
    try:
        page = max(1, int(request.args.get("page", "1")))
    except Exception:
        page = 1
    try:
        page_size = int(request.args.get("page_size", str(default_size)))
    except Exception:
        page_size = default_size
    page_size = min(max(1, page_size), max_size)
    offset = (page - 1) * page_size
    return page, page_size, offset

def require_admin():
    return ('role' in session and session['role'] == 'admin')

UPLOAD_ROOT = Path(app.root_path) / "static" / "uploads" / "services"

# ==============================
# VIEW ROUTES (RENDER HTML)
# ==============================

@app.route('/')
def home():
    return """
    <h1>Airport System</h1>
    <a href='/admin'>Admin</a><br>
    <a href='/user'>User</a>
    """

# admin
@app.route('/admin')
def admin():
    print("SESSION:", session)
    if not require_admin():
        return "Không có quyền truy cập!"
    return render_template("admin/orders.html")

# Quản lý dịch vụ
@app.route('/admin/service')
def admin_service():
    if not require_admin():
        return "Không có quyền!"
    return render_template("admin/service.html")

# Dashboard
@app.route('/admin/dashboard')
def dashboard():
    if not require_admin():
        return "Không có quyền!"
    return render_template("admin/dashboard.html")

# Orders management (alias of /admin)
@app.route('/admin/orders')
def admin_orders():
    if not require_admin():
        return "Không có quyền!"
    return render_template("admin/orders.html")

# Service image management
@app.route('/admin/service-images')
def admin_service_images():
    if not require_admin():
        return "Không có quyền!"
    return render_template("admin/service_images.html")

@app.route('/admin/service-images/<int:service_id>')
def admin_service_images_detail(service_id):
    if not require_admin():
        return "Không có quyền!"
    return render_template("admin/service_images_detail.html", service_id=service_id)

# User management
@app.route('/admin/users')
def admin_users_page():
    if not require_admin():
        return "Không có quyền!"
    return render_template("admin/users.html")

# user
@app.route('/user')
def user():
    return render_template("user/index.html")

# đăng nhập
@app.route('/login')
def login_page():
    return render_template("user/login.html")

@app.route('/forgot-password')
def forgot_password_page():
    return render_template("user/forgot_password.html")

# đăng ký
@app.route('/register')
def register_page():
    return render_template("user/register.html")

# đặt dịch vụ
@app.route('/booking')
def booking_page():
    return render_template("user/booking.html")


@app.route('/order-confirm')
def order_confirm_page():
    return render_template("user/order_confirm.html")


@app.route('/category')
def category():
    return render_template("user/category.html")

@app.route('/detail')
def detail():
    return render_template("user/detail.html")

@app.route('/profile')
def profile_page():
    return render_template("user/profile.html")

@app.route('/invoice/send', methods=['POST'])
def send_invoice_email():
    data = request.json or {}
    recipient = (data.get("recipient") or "").strip()
    subject = (data.get("subject") or "Hoa don dien tu").strip()
    body = (data.get("body") or "").strip()
    filename = (data.get("filename") or "hoa-don-dien-tu.pdf").strip()
    pdf_base64 = data.get("pdf_base64") or ""

    if not recipient or not pdf_base64:
        return jsonify({"message": "Missing recipient or invoice file"}), 400

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@example.com")

    if not smtp_host or not smtp_user or not smtp_pass:
        return jsonify({
            "message": "Email giả lập: Chưa cấu hình SMTP, hệ thống đã tạo hóa đơn thành công.",
            "simulated": True
        })

    try:
        file_bytes = base64.b64decode(pdf_base64)

        msg = MIMEMultipart()
        msg["From"] = smtp_from
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body or "Vui lòng xem hóa đơn điện tử đính kèm.", "plain", "utf-8"))

        part = MIMEBase("application", "pdf")
        part.set_payload(file_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [recipient], msg.as_string())

        return jsonify({"message": "Email hóa đơn đã được gửi thành công."})
    except Exception as e:
        return jsonify({"message": f"Không thể gửi email: {str(e)}"}), 500

# ==============================
# USER ACTIVITY + RECOMMENDATION
# ==============================

@app.route("/activity/log", methods=["POST"])
def log_activity():
    data = request.json or {}
    event_type = (data.get("event_type") or "").strip()
    if not event_type:
        return jsonify({"message": "Missing event_type"}), 400

    username = session.get("user")
    service_id = data.get("service_id")
    category = data.get("category")

    try:
        service_id = int(service_id) if service_id is not None and str(service_id).strip() != "" else None
    except Exception:
        service_id = None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO user_activity (username, event_type, service_id, category) VALUES (?, ?, ?, ?)",
        (username, event_type, service_id, category)
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Logged"})

@app.route("/recommendations", methods=["GET"])
def get_recommendations():
    """
    Return a list of recommended services for the current user.
    Strategy (simple + explainable):
    - If logged in: take last seen categories (most recent) and recommend top priced/popular in those categories.
    - Fallback: popular services by total quantity booked + reservations.
    """
    username = session.get("user")
    conn = get_db_connection()
    cursor = conn.cursor()

    preferred_categories = []
    if username:
        cursor.execute("""
            SELECT category
            FROM user_activity
            WHERE username=? AND category IS NOT NULL AND TRIM(category) != ''
            ORDER BY created_at DESC
            LIMIT 12
        """, (username,))
        rows = cursor.fetchall()
        for r in rows:
            c = (r["category"] or "").strip()
            if c and c not in preferred_categories:
                preferred_categories.append(c)

    services = []
    if preferred_categories:
        placeholders = ",".join(["?"] * len(preferred_categories))
        cursor.execute(f"""
            SELECT s.*
            FROM service s
            WHERE s.category IN ({placeholders})
            ORDER BY s.id DESC
            LIMIT 6
        """, preferred_categories)
        services = [dict(row) for row in cursor.fetchall()]

    if not services:
        cursor.execute("""
            SELECT s.*, COALESCE(SUM(bs.quantity), 0) AS booked_qty
            FROM service s
            LEFT JOIN booking_service bs ON bs.service_id = s.id
            GROUP BY s.id
            ORDER BY booked_qty DESC, s.id DESC
            LIMIT 6
        """)
        services = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return jsonify({"items": services})

# ==============================
# RESTAURANT RESERVATION
# ==============================

@app.route("/reservation/add", methods=["POST"])
def add_reservation():
    data = request.json or {}

    # Require login to personalize + manage reservation history
    if "user" not in session:
        return jsonify({"message": "Vui lòng đăng nhập!"}), 401

    try:
        service_id = int(data.get("service_id"))
        pax = int(data.get("pax"))
    except Exception:
        return jsonify({"message": "Invalid service_id or pax"}), 400

    reserved_date = (data.get("reserved_date") or "").strip()
    reserved_time = (data.get("reserved_time") or "").strip()
    contact_name = (data.get("contact_name") or "").strip()
    contact_phone = (data.get("contact_phone") or "").strip()
    note = (data.get("note") or "").strip()

    if not reserved_date or not reserved_time or pax <= 0 or not contact_name or not contact_phone:
        return jsonify({"message": "Thiếu thông tin đặt bàn."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, category FROM service WHERE id=?", (service_id,))
    s = cursor.fetchone()
    if not s:
        conn.close()
        return jsonify({"message": "Service not found"}), 404

    # Only allow reservation for restaurant/cafe category
    if (s["category"] or "").strip() != "restaurant":
        conn.close()
        return jsonify({"message": "Dịch vụ này không hỗ trợ đặt bàn."}), 400

    cursor.execute("""
        INSERT INTO restaurant_reservation (
            username, service_id, reserved_date, reserved_time, pax, contact_name, contact_phone, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (session["user"], service_id, reserved_date, reserved_time, pax, contact_name, contact_phone, note))

    reservation_id = cursor.lastrowid

    # log activity for recommendation
    cursor.execute(
        "INSERT INTO user_activity (username, event_type, service_id, category) VALUES (?, ?, ?, ?)",
        (session["user"], "reserve", service_id, "restaurant")
    )

    conn.commit()
    conn.close()
    return jsonify({"message": "Reserved successfully", "id": reservation_id})

# ==============================
# USER HISTORY
# ==============================

@app.route("/history")
def history_page():
    return render_template("user/history.html")

@app.route("/history/data")
def history_data():
    if "user" not in session:
        return jsonify({"message": "Vui lòng đăng nhập!"}), 401

    username = session["user"]
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT rr.id, rr.service_id, rr.reserved_date, rr.reserved_time, rr.pax,
               rr.contact_name, rr.contact_phone, rr.note, rr.created_at,
               s.name AS service_name, s.category AS service_category, s.image AS service_image, s.open_time AS open_time
        FROM restaurant_reservation rr
        LEFT JOIN service s ON s.id = rr.service_id
        WHERE rr.username=?
        ORDER BY rr.created_at DESC
        LIMIT 200
    """, (username,))
    reservations = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
        SELECT bs.id AS booking_id, bs.service_id, bs.quantity, bs.total_price, bs.created_at,
               s.name AS service_name, s.category AS service_category, s.image AS service_image, s.open_time AS open_time,
               p.name AS passenger_name, p.phone AS passenger_phone, p.payment_status AS payment_status
        FROM booking_service bs
        JOIN passenger p ON p.id = bs.passenger_id
        LEFT JOIN service s ON s.id = bs.service_id
        WHERE p.username=?
        ORDER BY bs.created_at DESC
        LIMIT 200
    """, (username,))
    bookings = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return jsonify({"reservations": reservations, "bookings": bookings})

# ==============================
# AUTH ROUTES (AUTH MODULE)
# ==============================

# Đăng ký tài khoản
@app.route('/auth/register', methods=['POST'])
def register():
    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        hashed = generate_password_hash(data['password'])

        cursor.execute(
            "INSERT INTO user (username, password, email, fullname, dob) VALUES (?, ?, ?, ?, ?)",
            (data['username'], hashed, data.get('email'), data.get('fullname'), data.get('dob'))
        )

        conn.commit()
        return jsonify({"message": "Register success"})
    except:
        return jsonify({"message": "User exists"})
    
# Đăng nhập
@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json
    remember_me = bool(data.get("remember_me"))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM user WHERE username=?",
        (data['username'],)
    )

    user = cursor.fetchone()

    if user and to_is_active(user["is_active"] if "is_active" in user.keys() else 1) != 1:
        return jsonify({"message": "Account inactive"})

    if user and check_password_hash(user['password'], data['password']):
        session.permanent = remember_me
        session['user'] = user['username']
        session['role'] = user['role']   
        return jsonify({"message": "Login success"})
    else:
        return jsonify({"message": "Invalid account"})

# Lấy user hiện tại
@app.route('/auth/me')
def get_me():
    if 'user' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, email, fullname, dob, role, gender FROM user WHERE username=?",
            (session['user'],)
        )
        user = cursor.fetchone()
        conn.close()

        if user:
            return jsonify({
                "user": user["username"],
                "role": user["role"],
                "email": user["email"],
                "fullname": user["fullname"],
                "dob": user["dob"],
                "gender": user["gender"] if "gender" in user.keys() else None
            })

        return jsonify({
            "user": session['user'],
            "role": session.get('role'),
            "email": "",
            "fullname": "",
            "dob": "",
            "gender": None
        })
    return jsonify({"user": None})

# Logout
@app.route('/auth/logout')
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})

@app.route('/auth/profile', methods=['PUT'])
def update_profile():
    if 'user' not in session:
        return jsonify({"message": "Vui lòng đăng nhập"}), 401
    data = request.json or {}
    email = (data.get('email') or '').strip()
    fullname = (data.get('fullname') or '').strip()
    dob = (data.get('dob') or '').strip()
    gender = (data.get('gender') or '').strip().lower()
    allowed = {'male', 'female', 'other', ''}
    if gender not in allowed:
        return jsonify({"message": "Giới tính không hợp lệ"}), 400
    gender_val = gender if gender else None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE user SET email=?, fullname=?, dob=?, gender=? WHERE username=?",
        (email or None, fullname or None, dob or None, gender_val, session['user'])
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Đã lưu hồ sơ"})

@app.route('/auth/change-password', methods=['POST'])
def change_password_logged_in():
    if 'user' not in session:
        return jsonify({"message": "Vui lòng đăng nhập"}), 401
    data = request.json or {}
    old_password = data.get('old_password') or ''
    new_password = (data.get('new_password') or '').strip()
    confirm = (data.get('confirm_password') or '').strip()
    if new_password != confirm:
        return jsonify({"message": "Mật khẩu mới không khớp"}), 400
    if len(new_password) < 6:
        return jsonify({"message": "Mật khẩu mới quá ngắn (tối thiểu 6 ký tự)"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM user WHERE username=?", (session['user'],))
    u = cursor.fetchone()
    if not u or not check_password_hash(u['password'], old_password):
        conn.close()
        return jsonify({"message": "Mật khẩu hiện tại không đúng"}), 400
    hashed = generate_password_hash(new_password)
    cursor.execute("UPDATE user SET password=? WHERE username=?", (hashed, session['user']))
    conn.commit()
    conn.close()
    return jsonify({"message": "Đã đổi mật khẩu thành công"})

# Forgot password -> reset password (verify by username or email)
@app.route('/auth/reset-password', methods=['POST'])
def reset_password():
    data = request.json or {}
    identifier = (data.get("identifier") or "").strip()
    new_password = (data.get("new_password") or "").strip()

    if not identifier or not new_password:
        return jsonify({"message": "Missing identifier or new_password"}), 400
    if len(new_password) < 6:
        return jsonify({"message": "Password too short"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, email FROM user WHERE username=? OR email=?",
        (identifier, identifier)
    )
    u = cursor.fetchone()
    if not u:
        conn.close()
        return jsonify({"message": "User not found"}), 404

    hashed = generate_password_hash(new_password)
    cursor.execute("UPDATE user SET password=? WHERE username=?", (hashed, u["username"]))
    conn.commit()
    conn.close()
    return jsonify({"message": "Password updated"})

# ==============================
# ADMIN USER MANAGEMENT (API)
# ==============================

@app.route('/admin/users/list')
def admin_users_list():
    if not require_admin():
        return jsonify({"message": "Forbidden"}), 403
    q = (request.args.get("q") or "").strip().lower()
    page, page_size, offset = parse_pagination(default_size=12, max_size=100)
    conn = get_db_connection()
    cursor = conn.cursor()
    params = []
    where = []
    if q:
        like = f"%{q}%"
        where.append("(LOWER(TRIM(username)) LIKE ? OR LOWER(TRIM(email)) LIKE ? OR LOWER(TRIM(fullname)) LIKE ?)")
        params.extend([like, like, like])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    cursor.execute(f"SELECT COUNT(*) AS total FROM user {where_sql}", params)
    total = int(cursor.fetchone()["total"] or 0)
    cursor.execute(f"""
        SELECT username, email, fullname, dob, role, COALESCE(is_active, 1) AS is_active
        FROM user
        {where_sql}
        ORDER BY username
        LIMIT ? OFFSET ?
    """, params + [page_size, offset])
    items = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify({"items": items, "total": total, "page": page, "page_size": page_size})

@app.route('/admin/users/update/<string:username>', methods=['PUT'])
def admin_users_update(username):
    if not require_admin():
        return jsonify({"message": "Forbidden"}), 403
    data = request.json or {}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM user WHERE username=?", (username,))
    u = cursor.fetchone()
    if not u:
        conn.close()
        return jsonify({"message": "Not found"}), 404

    cursor.execute("""
        UPDATE user
        SET email=?, fullname=?, dob=?, role=?, is_active=?
        WHERE username=?
    """, (
        data.get("email"),
        data.get("fullname"),
        data.get("dob"),
        data.get("role") or "user",
        to_is_active(data.get("is_active", 1)),
        username
    ))
    conn.commit()
    conn.close()
    return jsonify({"message": "Updated"})

@app.route('/admin/users/toggle/<string:username>', methods=['PUT'])
def admin_users_toggle(username):
    if not require_admin():
        return jsonify({"message": "Forbidden"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, COALESCE(is_active, 1) AS is_active FROM user WHERE username=?", (username,))
    u = cursor.fetchone()
    if not u:
        conn.close()
        return jsonify({"message": "Not found"}), 404
    data = request.json or {}
    requested = data.get("is_active", None)
    if requested is None:
        next_active = 0 if int(u["is_active"] or 1) == 1 else 1
    else:
        next_active = to_is_active(requested, default=int(u["is_active"] or 1))
    cursor.execute("UPDATE user SET is_active=? WHERE username=?", (next_active, username))
    conn.commit()
    conn.close()
    return jsonify({"message": "Updated active status", "is_active": next_active})

@app.route('/admin/users/delete/<string:username>', methods=['DELETE'])
def admin_users_delete(username):
    if not require_admin():
        return jsonify({"message": "Forbidden"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user WHERE username=?", (username,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted"})

# reset
@app.route("/reset")
def reset_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM booking_service")
    cursor.execute("DELETE FROM passenger")
    cursor.execute("DELETE FROM service")

    cursor.execute("DELETE FROM sqlite_sequence WHERE name='booking_service'")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='passenger'")
    cursor.execute("DELETE FROM sqlite_sequence WHERE name='service'")

    conn.commit()
    conn.close()

    return "Reset done!"

# ==============================
#  ADMIN
# ==============================

    # ==============================
    #  PASSENGER ROUTES
    # ==============================
# Thêm khách
@app.route('/passenger/add', methods=['POST'])
def add_passenger():
    data = request.json

    name = data.get('name')
    cccd = data.get('cccd')
    phone = data.get('phone')
    flight_id = data.get('flight_id')
    ticket_class = data.get('ticket_class')
    checkin_status = data.get('checkin_status')
    payment_status = data.get('payment_status') or "Unpaid"
    username = data.get('username')

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO passenger (name, cccd, phone, flight_id, ticket_class, checkin_status, payment_status, username)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, cccd, phone, flight_id, ticket_class, checkin_status, payment_status, username))

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Passenger added successfully",
        "id": cursor.lastrowid
    })

# lấy danh sách khách
@app.route('/passenger/list', methods=['GET'])
def get_passengers():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM passenger")
    passengers = cursor.fetchall()

    result = []
    for row in passengers:
        result.append(dict(row))

    conn.close()

    return jsonify(result)

# Cập nhật khách
@app.route('/passenger/update/<int:id>', methods=['PUT'])
def update_passenger(id):
    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE passenger
        SET name=?, cccd=?, ticket_class=?, checkin_status=?
        WHERE id=?
    """, (
        data.get('name'),
        data.get('cccd'),
        data.get('ticket_class'),
        data.get('checkin_status'),
        id
    ))

    conn.commit()
    conn.close()

    return jsonify({"message": "Updated successfully"})

# Xóa khách
@app.route('/passenger/delete/<int:id>', methods=['DELETE'])
def delete_passenger(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM passenger WHERE id=?", (id,))

    conn.commit()
    conn.close()

    return jsonify({"message": "Deleted successfully"})

# Check-in
@app.route('/passenger/checkin/<int:id>', methods=['PUT'])
def checkin(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT payment_status FROM passenger WHERE id=?", (id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return jsonify({"message": "Passenger not found"}), 404

    payment_status = (row["payment_status"] or "Unpaid").strip().lower()
    if payment_status != "paid":
        conn.close()
        return jsonify({"message": "Khách hàng chưa thanh toán nên không thể check-in."}), 400

    cursor.execute("""
        UPDATE passenger
        SET checkin_status='Checked'
        WHERE id=?
    """, (id,))

    conn.commit()
    conn.close()

    return jsonify({"message": "Checked-in"})

# Mark passenger as paid
@app.route('/passenger/pay/<int:id>', methods=['PUT'])
def mark_paid(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM passenger WHERE id=?", (id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"message": "Passenger not found"}), 404

    cursor.execute("UPDATE passenger SET payment_status='Paid' WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Payment marked as Paid"})

# Mark booking order as paid (sets paid_at and passenger.payment_status)
@app.route('/order/pay/<int:booking_id>', methods=['PUT'])
def mark_order_paid(booking_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, passenger_id FROM booking_service WHERE id=?", (booking_id,))
    bs = cursor.fetchone()
    if not bs:
        conn.close()
        return jsonify({"message": "Order not found"}), 404

    cursor.execute("UPDATE booking_service SET paid_at=CURRENT_TIMESTAMP WHERE id=?", (booking_id,))
    cursor.execute("UPDATE passenger SET payment_status='Paid' WHERE id=?", (bs["passenger_id"],))

    conn.commit()
    conn.close()
    return jsonify({"message": "Order paid"})

@app.route('/reservation/pay/<int:reservation_id>', methods=['PUT'])
def mark_reservation_paid(reservation_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM restaurant_reservation WHERE id=?", (reservation_id,))
    r = cursor.fetchone()
    if not r:
        conn.close()
        return jsonify({"message": "Reservation not found"}), 404
    cursor.execute("UPDATE restaurant_reservation SET paid_at=CURRENT_TIMESTAMP WHERE id=?", (reservation_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Reservation paid"})

    # ==============================
    # SERVICE ROUTES
    # ==============================

# Thêm dịch vụ
@app.route('/service/add', methods=['POST'])
def add_service():
    data = request.json

    name = data.get('name')
    category = data.get('category')
    image = data.get('image')
    open_time = data.get('open_time')
    phone = data.get('phone')
    description = data.get('description')
    location = data.get('location')
    position = data.get('position')
    usage_hours = data.get('usage_hours')
    amenities = data.get('amenities')

    try:
        price = float(data.get('price'))
        if price <= 0:
            return jsonify({"message": "Invalid price"})
    except:
        return jsonify({"message": "Invalid price"})

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO service (
            name, price, category, image, open_time, phone, description, location, position, usage_hours, amenities
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, price, category, image, open_time, phone, description, location, position, usage_hours, amenities))

    conn.commit()
    conn.close()

    return jsonify({"message": "Service added"})

# Lấy danh sách dịch vụ
@app.route('/service/list', methods=['GET'])
def get_services():
    q = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip().lower()
    page, page_size, offset = parse_pagination(default_size=500, max_size=1000)
    conn = get_db_connection()
    cursor = conn.cursor()
    params = []
    where = []
    if category:
        where.append("LOWER(TRIM(category)) = ?")
        params.append(category)
    if q:
        where.append("LOWER(TRIM(name)) LIKE ?")
        params.append(f"%{q}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    cursor.execute(f"SELECT COUNT(*) AS total FROM service {where_sql}", params)
    total = int(cursor.fetchone()["total"] or 0)
    cursor.execute(f"SELECT * FROM service {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?", params + [page_size, offset])
    result = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return jsonify({"items": result, "total": total, "page": page, "page_size": page_size})

@app.route('/service/<int:service_id>/images')
def service_images(service_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, filename FROM service_image WHERE service_id=? ORDER BY created_at DESC, id DESC", (service_id,))
    rows = cursor.fetchall()
    conn.close()

    items = []
    for r in rows:
        url = f"/static/uploads/services/{service_id}/{r['filename']}"
        items.append({"id": r["id"], "url": url})
    return jsonify({"items": items})

@app.route('/admin/service-images/services')
def admin_service_images_services():
    if not require_admin():
        return jsonify({"message": "Forbidden"}), 403
    q = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip().lower()
    page, page_size, offset = parse_pagination(default_size=12, max_size=100)
    conn = get_db_connection()
    cursor = conn.cursor()
    params = []
    where = []
    if category:
        where.append("LOWER(TRIM(category)) = ?")
        params.append(category)
    if q:
        where.append("LOWER(TRIM(name)) LIKE ?")
        params.append(f"%{q}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    cursor.execute(f"SELECT COUNT(*) AS total FROM service {where_sql}", params)
    total = int(cursor.fetchone()["total"] or 0)
    cursor.execute(f"SELECT id, name, category FROM service {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?", params + [page_size, offset])
    items = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify({"items": items, "total": total, "page": page, "page_size": page_size})

@app.route('/admin/service-images/<int:service_id>/list')
def admin_service_images_list(service_id):
    if not require_admin():
        return jsonify({"message": "Forbidden"}), 403
    return service_images(service_id)

@app.route('/admin/service-images/<int:service_id>/upload', methods=['POST'])
def admin_service_images_upload(service_id):
    if not require_admin():
        return jsonify({"message": "Forbidden"}), 403

    files = request.files.getlist("files")
    if not files:
        return jsonify({"message": "No files"}), 400

    service_dir = UPLOAD_ROOT / str(service_id)
    service_dir.mkdir(parents=True, exist_ok=True)

    conn = get_db_connection()
    cursor = conn.cursor()

    saved = 0
    for f in files:
        if not f or not f.filename:
            continue
        filename = secure_filename(f.filename)
        if not filename:
            continue
        # avoid collisions
        target = service_dir / filename
        if target.exists():
            stem = target.stem
            suffix = target.suffix
            filename = f"{stem}-{int(__import__('time').time())}{suffix}"
            target = service_dir / filename

        f.save(str(target))
        cursor.execute("INSERT INTO service_image (service_id, filename) VALUES (?, ?)", (service_id, filename))
        saved += 1

    conn.commit()
    conn.close()
    return jsonify({"message": f"Uploaded {saved} file(s)"})

@app.route('/admin/service-images/image/<int:image_id>/delete', methods=['DELETE'])
def admin_service_images_delete(image_id):
    if not require_admin():
        return jsonify({"message": "Forbidden"}), 403

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, service_id, filename FROM service_image WHERE id=?", (image_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"message": "Not found"}), 404

    cursor.execute("DELETE FROM service_image WHERE id=?", (image_id,))
    conn.commit()
    conn.close()

    # best-effort delete file
    try:
        p = UPLOAD_ROOT / str(row["service_id"]) / str(row["filename"])
        if p.exists():
            p.unlink()
    except Exception:
        pass

    return jsonify({"message": "Deleted"})

# Xóa dịch vụ
@app.route('/service/delete/<int:id>', methods=['DELETE'])
def delete_service(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT filename FROM service_image WHERE service_id=?", (id,))
    _ = cursor.fetchall()
    cursor.execute("DELETE FROM service_image WHERE service_id=?", (id,))
    cursor.execute("DELETE FROM booking_service WHERE service_id=?", (id,))
    cursor.execute("DELETE FROM restaurant_reservation WHERE service_id=?", (id,))
    cursor.execute("DELETE FROM service WHERE id=?", (id,))
    conn.commit()
    conn.close()
    try:
        service_dir = UPLOAD_ROOT / str(id)
        if service_dir.exists():
            shutil.rmtree(service_dir, ignore_errors=True)
    except Exception:
        pass

    return jsonify({"message": "Deleted"})

# Đăng ký dịch vụ
@app.route('/booking/add', methods=['POST'])
def add_booking():
    data = request.json or {}

    passenger_id = int(data.get('passenger_id'))
    service_id = int(data.get('service_id'))
    quantity = int(data.get('quantity'))
    using_date = (data.get("using_date") or "").strip() or None

    conn = get_db_connection()
    cursor = conn.cursor()

    # lấy giá dịch vụ
    cursor.execute("SELECT price FROM service WHERE id=?", (service_id,))
    service = cursor.fetchone()

    if not service:
        return jsonify({"message": "Service not found"})

    price = float(str(service["price"]).replace(",", ""))
    total_price = price * quantity

    cursor.execute("""
        INSERT INTO booking_service (passenger_id, service_id, quantity, total_price, using_date, order_code)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (passenger_id, service_id, quantity, total_price, using_date, ""))  # order_code filled right after insert

    booking_id = cursor.lastrowid
    order_code = f"ORD{int(booking_id):06d}"
    cursor.execute("UPDATE booking_service SET order_code=? WHERE id=?", (order_code, booking_id))

    conn.commit()
    conn.close()

    return jsonify({"message": "Booked successfully", "booking_id": booking_id, "order_code": order_code})

# ==============================
# BOOKING ROUTES (BUSINESS LOGIC)
# ==============================

# Lấy danh sách booking
@app.route('/booking/list', methods=['GET'])
def get_booking():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT bs.id, p.name as passenger_name, s.name as service_name,
               bs.quantity, bs.total_price
        FROM booking_service bs
        JOIN passenger p ON bs.passenger_id = p.id
        JOIN service s ON bs.service_id = s.id
    """)

    data = cursor.fetchall()
    result = [dict(row) for row in data]

    conn.close()
    return jsonify(result)

# ==============================
#DASHBOARD ROUTES
# ==============================

# Tổng doanh thu
@app.route('/dashboard/revenue')
def get_revenue():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT SUM(total_price) as total FROM booking_service")
    result = cursor.fetchone()

    conn.close()

    return jsonify({"revenue": result["total"] or 0})

# Tổng số booking
@app.route('/dashboard/booking-count')
def booking_count():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM booking_service")
    result = cursor.fetchone()

    conn.close()

    return jsonify({"count": result["count"]})

# Doanh thu theo ngày
@app.route('/dashboard/revenue-by-date')
def revenue_by_date():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DATE(created_at) as date, SUM(total_price) as total
        FROM booking_service
        GROUP BY DATE(created_at)
    """)

    data = cursor.fetchall()
    result = [dict(row) for row in data]

    conn.close()

    return jsonify(result)

@app.route('/dashboard/top-categories')
def dashboard_top_categories():
    """
    Count usage by service category (paid orders + paid reservations).
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # booking_service (paid_at preferred; fallback payment_status on passenger)
    cursor.execute("""
        SELECT s.category AS category, COUNT(*) AS cnt
        FROM booking_service bs
        JOIN service s ON s.id = bs.service_id
        LEFT JOIN passenger p ON p.id = bs.passenger_id
        WHERE bs.paid_at IS NOT NULL OR LOWER(TRIM(COALESCE(p.payment_status, '')))='paid'
        GROUP BY s.category
    """)
    booking_counts = {str(r["category"] or "").strip(): int(r["cnt"] or 0) for r in cursor.fetchall()}

    cursor.execute("""
        SELECT s.category AS category, COUNT(*) AS cnt
        FROM restaurant_reservation rr
        JOIN service s ON s.id = rr.service_id
        WHERE rr.paid_at IS NOT NULL
        GROUP BY s.category
    """)
    res_counts = {str(r["category"] or "").strip(): int(r["cnt"] or 0) for r in cursor.fetchall()}

    conn.close()

    def get_total(cat):
        return int(booking_counts.get(cat, 0)) + int(res_counts.get(cat, 0))

    items = [
        {"category": "lounge", "count": get_total("lounge")},
        {"category": "restaurant", "count": get_total("restaurant")},
        {"category": "sleep", "count": get_total("sleep")}
    ]
    items.sort(key=lambda x: x["count"], reverse=True)
    return jsonify({"items": items})

@app.route('/admin/orders/data')
def admin_orders_data():
    if not require_admin():
        return jsonify({"message": "Forbidden"}), 403

    category = (request.args.get("category") or "").strip()
    q = (request.args.get("q") or "").strip().lower()
    page, page_size, offset = parse_pagination(default_size=20, max_size=100)

    conn = get_db_connection()
    cursor = conn.cursor()
    where_booking = []
    where_reservation = []
    params_count = []
    params_items = []
    if category:
        where_booking.append("LOWER(TRIM(s.category)) = ?")
        where_reservation.append("LOWER(TRIM(s.category)) = ?")
        params_count.append(category.lower())
        params_count.append(category.lower())
        params_items.append(category.lower())
        params_items.append(category.lower())
    if q:
        like = f"%{q}%"
        where_booking.append("(LOWER(TRIM(p.name)) LIKE ? OR LOWER(TRIM(bs.order_code)) LIKE ? OR CAST(bs.id AS TEXT) LIKE ?)")
        where_reservation.append("(LOWER(TRIM(rr.contact_name)) LIKE ? OR CAST(rr.id AS TEXT) LIKE ?)")
        params_count.extend([like, like, like, like, like])
        params_items.extend([like, like, like, like, like])
    wb_sql = ("WHERE " + " AND ".join(where_booking)) if where_booking else ""
    wr_sql = ("WHERE " + " AND ".join(where_reservation)) if where_reservation else ""

    cursor.execute(f"""
        SELECT COUNT(*) AS total FROM (
            SELECT bs.id
            FROM booking_service bs
            JOIN passenger p ON p.id = bs.passenger_id
            LEFT JOIN service s ON s.id = bs.service_id
            {wb_sql}
            UNION ALL
            SELECT rr.id
            FROM restaurant_reservation rr
            LEFT JOIN service s ON s.id = rr.service_id
            {wr_sql}
        ) x
    """, params_count)
    total = int(cursor.fetchone()["total"] or 0)

    cursor.execute(f"""
        SELECT * FROM (
            SELECT
                bs.id AS id,
                bs.order_code AS order_code,
                'booking' AS order_type,
                s.category AS category,
                s.name AS service_name,
                p.name AS customer_name,
                p.phone AS customer_phone,
                bs.quantity AS quantity,
                bs.total_price AS total_price,
                bs.using_date AS using_date,
                bs.paid_at AS paid_at,
                bs.created_at AS created_at,
                COALESCE(p.payment_status, 'Unpaid') AS payment_status,
                COALESCE(bs.paid_at, bs.created_at) AS sort_time
            FROM booking_service bs
            JOIN passenger p ON p.id = bs.passenger_id
            LEFT JOIN service s ON s.id = bs.service_id
            {wb_sql}
            UNION ALL
            SELECT
                rr.id AS id,
                ('RES' || printf('%06d', rr.id)) AS order_code,
                'reservation' AS order_type,
                s.category AS category,
                s.name AS service_name,
                rr.contact_name AS customer_name,
                rr.contact_phone AS customer_phone,
                rr.pax AS quantity,
                NULL AS total_price,
                rr.reserved_date AS using_date,
                rr.paid_at AS paid_at,
                rr.created_at AS created_at,
                CASE WHEN rr.paid_at IS NOT NULL THEN 'Paid' ELSE 'Unpaid' END AS payment_status,
                COALESCE(rr.paid_at, rr.created_at) AS sort_time
            FROM restaurant_reservation rr
            LEFT JOIN service s ON s.id = rr.service_id
            {wr_sql}
        ) t
        ORDER BY sort_time DESC
        LIMIT ? OFFSET ?
    """, params_items + [page_size, offset])
    items = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify({"items": items, "total": total, "page": page, "page_size": page_size})

@app.route('/admin/orders/export')
def admin_orders_export():
    if not require_admin():
        return jsonify({"message": "Forbidden"}), 403

    # export uses the same filters as /admin/orders/data
    category = (request.args.get("category") or "").strip()
    q = (request.args.get("q") or "").strip().lower()

    conn = get_db_connection()
    cursor = conn.cursor()

    params = []
    where = []
    if category:
        where.append("LOWER(TRIM(s.category)) = ?")
        params.append(category.lower())
    if q:
        where.append("(LOWER(TRIM(p.name)) LIKE ? OR LOWER(TRIM(bs.order_code)) LIKE ? OR CAST(bs.id AS TEXT) LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    cursor.execute(f"""
        SELECT
            bs.order_code AS order_code,
            'booking' AS order_type,
            s.category AS category,
            s.name AS service_name,
            p.name AS customer_name,
            p.phone AS customer_phone,
            bs.using_date AS using_date,
            bs.quantity AS quantity,
            bs.total_price AS total_price,
            COALESCE(p.payment_status, 'Unpaid') AS payment_status,
            bs.paid_at AS paid_at,
            bs.created_at AS created_at
        FROM booking_service bs
        JOIN passenger p ON p.id = bs.passenger_id
        LEFT JOIN service s ON s.id = bs.service_id
        {where_sql}
        ORDER BY COALESCE(bs.paid_at, bs.created_at) DESC
        LIMIT 2000
    """, params)
    items = [dict(r) for r in cursor.fetchall()]

    params2 = []
    where2 = []
    if category:
        where2.append("LOWER(TRIM(s.category)) = ?")
        params2.append(category.lower())
    if q:
        where2.append("(LOWER(TRIM(rr.contact_name)) LIKE ? OR CAST(rr.id AS TEXT) LIKE ?)")
        like = f"%{q}%"
        params2.extend([like, like])
    where_sql2 = ("WHERE " + " AND ".join(where2)) if where2 else ""

    cursor.execute(f"""
        SELECT
            ('RES' || printf('%06d', rr.id)) AS order_code,
            'reservation' AS order_type,
            s.category AS category,
            s.name AS service_name,
            rr.contact_name AS customer_name,
            rr.contact_phone AS customer_phone,
            rr.reserved_date AS using_date,
            rr.pax AS quantity,
            NULL AS total_price,
            CASE WHEN rr.paid_at IS NOT NULL THEN 'Paid' ELSE 'Unpaid' END AS payment_status,
            rr.paid_at AS paid_at,
            rr.created_at AS created_at
        FROM restaurant_reservation rr
        LEFT JOIN service s ON s.id = rr.service_id
        {where_sql2}
        ORDER BY COALESCE(rr.paid_at, rr.created_at) DESC
        LIMIT 2000
    """, params2)
    items2 = [dict(r) for r in cursor.fetchall()]

    conn.close()

    all_items = items + items2
    all_items.sort(key=lambda x: str(x.get("paid_at") or x.get("created_at") or ""), reverse=True)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "order_code", "order_type", "category", "service_name",
        "customer_name", "customer_phone", "using_date",
        "quantity", "total_price", "payment_status", "paid_at", "created_at"
    ])
    for it in all_items:
        writer.writerow([
            it.get("order_code") or "",
            it.get("order_type") or "",
            it.get("category") or "",
            it.get("service_name") or "",
            it.get("customer_name") or "",
            it.get("customer_phone") or "",
            it.get("using_date") or "",
            it.get("quantity") or "",
            it.get("total_price") or "",
            it.get("payment_status") or "",
            it.get("paid_at") or "",
            it.get("created_at") or "",
        ])

    csv_text = output.getvalue()
    filename = "orders_export.csv"
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

# Chi tiết khách hàng
@app.route("/passenger/<int:id>/detail")
def passenger_detail(id):
    conn = sqlite3.connect("airport.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.name, b.quantity, b.total_price
        FROM booking_service b
        JOIN service s ON b.service_id = s.id
        WHERE b.passenger_id = ?
    """, (id,))

    services = [
        {"name": row[0], "quantity": row[1], "total": row[2]}
        for row in cursor.fetchall()
    ]

    total_money = sum(float(s["total"]) for s in services)

    conn.close()

    return jsonify({
        "services": services,
        "total": total_money
    })

# 
@app.route('/service/update/<int:id>', methods=['PUT'])
def update_service(id):
    data = request.json

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE service
        SET name=?, price=?, category=?, image=?, open_time=?, phone=?, description=?, location=?, position=?, usage_hours=?, amenities=?
        WHERE id=?
    """, (
        data.get('name'),
        data.get('price'),
        data.get('category'),
        data.get('image'),
        data.get('open_time'),
        data.get('phone'),
        data.get('description'),
        data.get('location'),
        data.get('position'),
        data.get('usage_hours'),
        data.get('amenities'),
        id
    ))

    conn.commit()
    conn.close()

    return jsonify({"message": "Updated successfully"})



if __name__ == '__main__':
    app.run(debug=True)