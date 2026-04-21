from flask import Flask, request, jsonify, render_template, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from datetime import timedelta

import sqlite3
import os
from dotenv import load_dotenv

print("SMTP_HOST =", os.getenv("SMTP_HOST"))

import base64
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

app = Flask(__name__)
app.secret_key = "123456"
app.permanent_session_lifetime = timedelta(days=30)
CORS(app)

# Hàm kết nối DB
def get_db_connection():
    conn = sqlite3.connect('airport.db')
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
    if 'role' not in session or session['role'] != 'admin':
        return "Không có quyền truy cập!"
    return render_template("admin/index_admin.html")

# Quản lý dịch vụ
@app.route('/admin/service')
def admin_service():
    if 'role' not in session or session['role'] != 'admin':
        return "Không có quyền!"
    return render_template("admin/service.html")

# Dashboard
@app.route('/admin/dashboard')
def dashboard():
    if 'role' not in session or session['role'] != 'admin':
        return "Không có quyền!"
    return render_template("admin/dashboard.html")

# user
@app.route('/user')
def user():
    return render_template("user/index.html")

# đăng nhập
@app.route('/login')
def login_page():
    return render_template("user/login.html")

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
            "SELECT username, email, fullname, dob, role FROM user WHERE username=?",
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
                "dob": user["dob"]
            })

        return jsonify({
            "user": session['user'],
            "role": session.get('role'),
            "email": "",
            "fullname": "",
            "dob": ""
        })
    return jsonify({"user": None})

# Logout
@app.route('/auth/logout')
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})

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
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM service")
    services = cursor.fetchall()

    result = [dict(row) for row in services]

    conn.close()
    return jsonify(result)

# Xóa dịch vụ
@app.route('/service/delete/<int:id>', methods=['DELETE'])
def delete_service(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM service WHERE id=?", (id,))

    conn.commit()
    conn.close()

    return jsonify({"message": "Deleted"})

# Đăng ký dịch vụ
@app.route('/booking/add', methods=['POST'])
def add_booking():
    data = request.json

    passenger_id = int(data.get('passenger_id'))
    service_id = int(data.get('service_id'))
    quantity = int(data.get('quantity'))

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
        INSERT INTO booking_service (passenger_id, service_id, quantity, total_price)
        VALUES (?, ?, ?, ?)
    """, (passenger_id, service_id, quantity, total_price))

    conn.commit()
    conn.close()

    return jsonify({"message": "Booked successfully"})

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