# app.py - Receipt Graveyard: AI Expense Auditor, Multi-Role Auth & Dual-Evidence Engine
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify, Response, session
from werkzeug.utils import secure_filename
from pathlib import Path
from datetime import datetime, date, timedelta
from functools import wraps
import sqlite3, hashlib, json, os, csv, io, base64, zipfile, threading

from policy import POLICY
import ocr_engine
import fraud_engine
import trip_engine
import seed_data
import historical_ingestion
import bulk_drive_ingestion
import budget_engine

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("RECEIPT_GRAVEYARD_DATA_DIR", APP_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "expenses.db"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_FOLDER", DATA_DIR / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "receipt-graveyard-super-secret-key-2026")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 MB max
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
app.jinja_env.globals.update(max=max, min=min)

def connect():
    con = sqlite3.connect(str(DB_PATH), timeout=30.0)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return con

def init_db():
    with connect() as con:
        # 1. Offices Table
        con.execute("""
        CREATE TABLE IF NOT EXISTS offices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT,
            address TEXT,
            is_headquarters INTEGER DEFAULT 0,
            local_meal_cap REAL DEFAULT 1200.0
        )
        """)

        # 2. Users Table (Admin, Accounts, Employee)
        con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            office_id INTEGER REFERENCES offices(id),
            department TEXT,
            phone TEXT,
            avatar_color TEXT DEFAULT '#0f766e',
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        )
        """)

        # 3. Expenses Table (Claims)
        con.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            office_id INTEGER REFERENCES offices(id),
            employee TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            expense_date TEXT,
            merchant TEXT,
            category TEXT,
            city TEXT,
            amount REAL,
            currency TEXT DEFAULT 'INR',
            amount_inr REAL,
            eligible_amount REAL,
            difference_from_cap REAL,
            payment_method TEXT DEFAULT 'UPI',
            transaction_ref TEXT,
            payment_file TEXT,
            payment_verified INTEGER DEFAULT 0,
            payment_match_note TEXT,
            client_name TEXT,
            project_code TEXT,
            attendees INTEGER DEFAULT 0,
            attendee_names TEXT,
            description TEXT,
            status TEXT,
            reimbursable REAL,
            risk_score INTEGER,
            flags TEXT,
            suspicion_types TEXT,
            explanation TEXT,
            file_name TEXT,
            file_hash TEXT,
            perceptual_hash TEXT,
            source TEXT DEFAULT 'Web Upload',
            is_trip INTEGER DEFAULT 0,
            trip_id TEXT,
            math_status TEXT,
            extracted_amount REAL,
            subtotal REAL,
            tax_amount REAL,
            tip_amount REAL,
            non_reimbursable_deduction REAL DEFAULT 0,
            itemized_items TEXT,
            ocr_raw_text TEXT,
            duplicate_of_id INTEGER,
            audit_log TEXT,
            upi_app TEXT DEFAULT 'Google Pay',
            upi_vpa TEXT,
            project_id INTEGER,
            policy_version TEXT DEFAULT 'v2026.1',
            editing_deadline TEXT,
            internal_review_notes TEXT,
            review_reason TEXT,
            requested_documents TEXT,
            reimbursed_at TEXT,
            reimbursed_by TEXT,
            reimbursement_tx_ref TEXT,
            reimbursement_method TEXT,
            resubmission_count INTEGER DEFAULT 0
        )
        """)

        # 4. Projects Table (Enterprise Projects with Max Auto-Approval Caps)
        con.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            client_name TEXT,
            budget REAL DEFAULT 100000.0,
            auto_approval_cap REAL DEFAULT 2000.0,
            manager_name TEXT,
            status TEXT DEFAULT 'Active',
            description TEXT,
            start_date TEXT,
            end_date TEXT,
            currency TEXT DEFAULT 'INR',
            created_at TEXT,
            updated_at TEXT
        )
        """)

        # 5. Project Memberships Table
        con.execute("""
        CREATE TABLE IF NOT EXISTS project_memberships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            role TEXT DEFAULT 'Member',
            assigned_at TEXT NOT NULL,
            UNIQUE(project_id, user_id)
        )
        """)

        # 6. Claim Versions Table (Historical Preservation of State & Documents)
        con.execute("""
        CREATE TABLE IF NOT EXISTS claim_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id INTEGER NOT NULL REFERENCES expenses(id),
            version_num INTEGER NOT NULL,
            changed_by TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            status TEXT NOT NULL,
            claimed_amount REAL,
            reimbursable REAL,
            snapshot_json TEXT NOT NULL,
            change_summary TEXT
        )
        """)

        # 7. Supporting Documents Table (Multi-Proof & Resubmission Attachments)
        con.execute("""
        CREATE TABLE IF NOT EXISTS supporting_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id INTEGER NOT NULL REFERENCES expenses(id),
            user_id INTEGER REFERENCES users(id),
            filename TEXT NOT NULL,
            original_filename TEXT,
            file_type TEXT,
            document_category TEXT DEFAULT 'Supporting Document',
            file_hash TEXT,
            revision INTEGER DEFAULT 1,
            upload_timestamp TEXT NOT NULL,
            note TEXT
        )
        """)

        # 8. Review Requests Table (Accounts Document & Clarification Requests)
        con.execute("""
        CREATE TABLE IF NOT EXISTS review_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id INTEGER NOT NULL REFERENCES expenses(id),
            reviewer_id INTEGER REFERENCES users(id),
            reviewer_name TEXT NOT NULL,
            reason TEXT NOT NULL,
            missing_information TEXT,
            requested_documents TEXT,
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            response_text TEXT,
            responded_at TEXT
        )
        """)

        # 9. In-App Notifications Table
        con.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            claim_id INTEGER REFERENCES expenses(id),
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """)

        # 10. Expense Policies Table (Policy Versioning & Governance)
        con.execute("""
        CREATE TABLE IF NOT EXISTS expense_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            rules_json TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            created_by TEXT DEFAULT 'Admin'
        )
        """)

        # 11. Historical Ingestion Jobs Table
        con.execute("""
        CREATE TABLE IF NOT EXISTS historical_ingestion_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            total_rows INTEGER DEFAULT 0,
            imported_rows INTEGER DEFAULT 0,
            employees_detected INTEGER DEFAULT 0,
            duplicates_detected INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Completed',
            ingestion_summary_json TEXT,
            created_at TEXT NOT NULL
        )
        """)

        # 12. System Policy Settings Table (Editable by Admin)
        con.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)

        cursor = con.cursor()

        # Auto-migrate expenses table columns
        existing_exp_cols = [r[1] for r in cursor.execute("PRAGMA table_info(expenses)").fetchall()]
        exp_cols = {
            "user_id": "INTEGER REFERENCES users(id)",
            "office_id": "INTEGER REFERENCES offices(id)",
            "payment_method": "TEXT DEFAULT 'UPI'",
            "transaction_ref": "TEXT",
            "payment_file": "TEXT",
            "payment_verified": "INTEGER DEFAULT 0",
            "payment_match_note": "TEXT",
            "project_code": "TEXT",
            "upi_app": "TEXT DEFAULT 'Google Pay'",
            "upi_vpa": "TEXT",
            "project_id": "INTEGER REFERENCES projects(id)",
            "attendee_names": "TEXT",
            "perceptual_hash": "TEXT",
            "is_trip": "INTEGER DEFAULT 0",
            "trip_id": "TEXT",
            "math_status": "TEXT",
            "extracted_amount": "REAL",
            "subtotal": "REAL",
            "tax_amount": "REAL",
            "tip_amount": "REAL",
            "non_reimbursable_deduction": "REAL DEFAULT 0",
            "itemized_items": "TEXT",
            "ocr_raw_text": "TEXT",
            "duplicate_of_id": "INTEGER",
            "suspicion_types": "TEXT",
            "audit_log": "TEXT",
            "eligible_amount": "REAL",
            "difference_from_cap": "REAL",
            "policy_version": "TEXT DEFAULT 'v2026.1'",
            "editing_deadline": "TEXT",
            "internal_review_notes": "TEXT",
            "review_reason": "TEXT",
            "requested_documents": "TEXT",
            "reimbursed_at": "TEXT",
            "reimbursed_by": "TEXT",
            "reimbursement_tx_ref": "TEXT",
            "reimbursement_method": "TEXT",
            "resubmission_count": "INTEGER DEFAULT 0"
        }
        for col, col_type in exp_cols.items():
            if col not in existing_exp_cols:
                cursor.execute(f"ALTER TABLE expenses ADD COLUMN {col} {col_type}")

        # Auto-migrate users table columns
        existing_user_cols = [r[1] for r in cursor.execute("PRAGMA table_info(users)").fetchall()]
        user_cols = {
            "is_active": "INTEGER DEFAULT 1",
            "created_at": "TEXT",
            "status": "TEXT DEFAULT 'APPROVED'",
            "employee_id": "TEXT",
            "designation": "TEXT",
            "reason_for_access": "TEXT",
            "rejection_reason": "TEXT",
            "reviewed_by": "TEXT",
            "reviewed_at": "TEXT"
        }
        for col, col_type in user_cols.items():
            if col not in existing_user_cols:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        cursor.execute("UPDATE users SET status='APPROVED' WHERE status IS NULL")

        # Auto-migrate projects table columns
        existing_proj_cols = [r[1] for r in cursor.execute("PRAGMA table_info(projects)").fetchall()]
        proj_cols = {
            "start_date": "TEXT",
            "end_date": "TEXT",
            "currency": "TEXT DEFAULT 'INR'",
            "created_at": "TEXT",
            "updated_at": "TEXT"
        }
        for col, col_type in proj_cols.items():
            if col not in existing_proj_cols:
                cursor.execute(f"ALTER TABLE projects ADD COLUMN {col} {col_type}")

        # Seed default system settings
        default_settings = [
            ("auto_approval_cap", "1500.0"),
            ("manager_approval_threshold", "8000.0"),
            ("vp_approval_threshold", "20000.0"),
            ("local_meal_cap_default", "1200.0"),
            ("trip_meal_cap_default", "2200.0"),
            ("editing_window_hours", "24.0"),
            ("active_policy_version", "v2026.1")
        ]
        for k, v in default_settings:
            exists = con.execute("SELECT 1 FROM system_settings WHERE key=?", (k,)).fetchone()
            if not exists:
                con.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", (k, v))

        # Seed default projects if empty
        proj_count = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if proj_count == 0:
            default_projects = [
                ("PRJ-MIG-2026", "Cloud Infrastructure Migration", "HDFC Bank Ltd", 850000.0, 3500.0, "Rajesh Sharma", "Active", "Multi-region cloud database & Kubernetes migration", "2026-01-01", "2026-12-31"),
                ("PRJ-RETAIL-04", "Omnichannel POS & QR Rollout", "Reliance Retail", 500000.0, 2500.0, "Priya Nair", "Active", "Nationwide retail billing QR code synchronization", "2026-03-01", "2026-11-30"),
                ("PRJ-UPI-09", "Core UPI Payment Gateway Modernization", "NPCI / Razorpay", 1200000.0, 5000.0, "Vikram Sen", "Active", "High-throughput UPI switch with instant auto-settlement", "2026-02-15", "2026-12-31"),
                ("PRJ-AI-AUDIT", "Antigravity AI Autonomous Audit", "Internal Enterprise", 250000.0, 1800.0, "Aarav Mehta", "Active", "Autonomous computer vision receipt scanner and policy reconciliation", "2026-01-10", "2026-10-31")
            ]
            con.executemany("""
            INSERT OR REPLACE INTO projects (code, name, client_name, budget, auto_approval_cap, manager_name, status, description, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, default_projects)

        # Seed initial policy version if empty
        policy_count = con.execute("SELECT COUNT(*) FROM expense_policies").fetchone()[0]
        if policy_count == 0:
            con.execute("""
            INSERT INTO expense_policies (version, title, rules_json, is_active, created_at, created_by)
            VALUES ('v2026.1', 'FY2026 Standard Enterprise Expense Policy', ?, 1, ?, 'Policy Director')
            """, (json.dumps(POLICY), datetime.now().strftime("%Y-%m-%d %H:%M")))

        # Initialize Bulk Excel & Google Drive Tables
        bulk_drive_ingestion.init_bulk_tables(con)

        # Initialize Project Budget Allocations, Ledger & Cap Adjustment Tables
        budget_engine.init_budget_tables(con)

        con.commit()

        # Seed users & sample receipts if empty
        user_count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if user_count == 0:
            seed_data.seed_database(con)

# Ensure database schema is present on module import (e.g. for Gunicorn workers)
try:
    init_db()
except Exception as _init_err:
    pass

def get_system_settings(con):
    rows = con.execute("SELECT key, value FROM system_settings").fetchall()
    settings = {
        "auto_approval_cap": 1500.0,
        "manager_approval_threshold": 8000.0,
        "vp_approval_threshold": 20000.0,
        "local_meal_cap_default": 1200.0,
        "trip_meal_cap_default": 2200.0,
        "editing_window_hours": 24.0,
        "active_policy_version": "v2026.1"
    }
    for r in rows:
        try:
            settings[r["key"]] = float(r["value"])
        except ValueError:
            settings[r["key"]] = r["value"]
    return settings

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def save_base64_camera_image(data_uri, prefix="cam_"):
    """Saves a base64 DataURI image captured from live web camera."""
    try:
        header, encoded = data_uri.split(",", 1)
        data = base64.b64decode(encoded)
        filename = f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}.jpg"
        out_path = UPLOAD_DIR / filename
        with open(out_path, "wb") as f:
            f.write(data)
        return filename, out_path
    except Exception:
        return None, None

# ----------------- NOTIFICATIONS & AUDIT / VERSIONING HELPERS -----------------

def create_notification(con, user_id, claim_id, title, message, notif_type="info"):
    """Sends an in-app notification to a user."""
    try:
        con.execute("""
        INSERT INTO notifications (user_id, claim_id, title, message, type, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        """, (user_id, claim_id, title, message, notif_type, datetime.now().strftime("%Y-%m-%d %H:%M")))
    except Exception:
        pass

def notify_accounts_team(con, claim_id, title, message, notif_type="review"):
    """Dispatches a notification to all active accounts reviewers and admins."""
    try:
        reviewers = con.execute("SELECT id FROM users WHERE role IN ('accounts', 'admin') AND is_active=1").fetchall()
        for r in reviewers:
            create_notification(con, r["id"], claim_id, title, message, notif_type)
    except Exception:
        pass

def create_claim_version(con, claim_id, changed_by, change_summary):
    """Preserves historical claim versions before changes or resubmissions."""
    try:
        claim = con.execute("SELECT * FROM expenses WHERE id=?", (claim_id,)).fetchone()
        if not claim:
            return
        prev_versions = con.execute("SELECT COUNT(*) FROM claim_versions WHERE claim_id=?", (claim_id,)).fetchone()[0]
        v_num = prev_versions + 1
        snapshot = dict(claim)
        con.execute("""
        INSERT INTO claim_versions (claim_id, version_num, changed_by, changed_at, status, claimed_amount, reimbursable, snapshot_json, change_summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            claim_id, v_num, changed_by, datetime.now().strftime("%Y-%m-%d %H:%M"),
            claim["status"], claim["amount_inr"], claim["reimbursable"],
            json.dumps(snapshot), change_summary
        ))
    except Exception:
        pass

# ----------------- AUTHENTICATION CONTEXT & HELPERS -----------------

@app.context_processor
def inject_user_context():
    """Injects current_user, all_users, all_offices, all_projects, system_settings, and notifications into every template."""
    with connect() as con:
        user_id = session.get("user_id")
        current_user = None
        if user_id:
            row = con.execute("""
            SELECT u.*, o.name as office_name, o.city as office_city, o.local_meal_cap 
            FROM users u 
            LEFT JOIN offices o ON u.office_id = o.id 
            WHERE u.id = ?
            """, (user_id,)).fetchone()
            if row:
                current_user = dict(row)

        # For automated test suite runs (TESTING=True), fallback to Accounts persona if no session set
        if not current_user and app.config.get("TESTING"):
            row = con.execute("""
            SELECT u.*, o.name as office_name, o.city as office_city, o.local_meal_cap 
            FROM users u 
            LEFT JOIN offices o ON u.office_id = o.id 
            WHERE u.id = 2
            """).fetchone()
            if row:
                current_user = dict(row)

        unread_notifications = []
        unread_notifications_count = 0
        if current_user:
            unread_notifications = [dict(n) for n in con.execute("""
            SELECT * FROM notifications 
            WHERE user_id = ? AND is_read = 0 
            ORDER BY id DESC LIMIT 8
            """, (current_user["id"],)).fetchall()]
            unread_notifications_count = len(unread_notifications)

        all_users = [dict(r) for r in con.execute("""
        SELECT u.*, o.name as office_name, o.city as office_city 
        FROM users u 
        LEFT JOIN offices o ON u.office_id = o.id 
        ORDER BY u.role, u.id
        """).fetchall()]

        all_offices = [dict(r) for r in con.execute("SELECT * FROM offices ORDER BY id").fetchall()]
        all_projects = [dict(r) for r in con.execute("SELECT * FROM projects WHERE status='Active' ORDER BY code").fetchall()]
        system_settings = get_system_settings(con)

    return dict(
        current_user=current_user,
        all_users=all_users,
        all_offices=all_offices,
        all_projects=all_projects,
        system_settings=system_settings,
        unread_notifications=unread_notifications,
        unread_notifications_count=unread_notifications_count
    )

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id") and not app.config.get("TESTING"):
            flash("Please log in to continue.", "info")
            return redirect(url_for("login"))
        # Verify account approval status on every protected request
        if session.get("user_id") and not app.config.get("TESTING"):
            with connect() as con:
                u = con.execute("SELECT status, is_active FROM users WHERE id=?", (session["user_id"],)).fetchone()
                if not u or (u["status"] or "").upper() != "APPROVED" or u["is_active"] == 0:
                    session.clear()
                    flash("Your session has ended because your account is awaiting administrator approval or is inactive.", "warning")
                    return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_role = session.get("role", "employee")
            if user_role not in allowed_roles and user_role != "admin":
                flash("Access restricted to authorized personnel.", "error")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ----------------- CORE AUDIT ENGINE -----------------

def analyze_expense(data, file_path=None, payment_file_path=None, exclude_id=None):
    """
    Core AI audit decision engine.
    Orchestrates OCR parsing, math verification, policy caps, trip context,
    accumulation across days/cities, multi-vector fraud detection, and dual-evidence verification.
    """
    flags = []
    suspicion_types = []
    risk_score = 0
    duplicate_of_id = None

    employee = (data.get("employee") or "").strip() or "Unassigned Employee"
    expense_date = data.get("expense_date")
    merchant = (data.get("merchant") or "").strip()
    category = data.get("category") or "Other"
    city = data.get("city") or "Other"
    currency = (data.get("currency") or "INR").upper()
    try:
        amount = float(data.get("amount") or 0)
    except (ValueError, TypeError):
        amount = 0.0

    try:
        attendees = int(data.get("attendees") or 0)
    except (ValueError, TypeError):
        attendees = 0

    client_name = (data.get("client_name") or "").strip()
    attendee_names = (data.get("attendee_names") or "").strip()
    project_code = (data.get("project_code") or "").strip()
    description = (data.get("description") or "").strip()
    payment_method = data.get("payment_method") or "UPI"
    transaction_ref = (data.get("transaction_ref") or "").strip()
    manual_is_trip = bool(data.get("is_trip", False))

    # 1. Currency Conversion
    rate = POLICY["currency_rates_to_inr"].get(currency)
    if rate is None:
        rate = 1.0
        flags.append(f"Unknown currency '{currency}'; 1:1 fallback rate applied, requires finance verification")
        risk_score += 15
    amount_inr = round(amount * rate, 2)
    data["amount_inr"] = amount_inr

    # 2. File hashing & Bill OCR extraction
    file_hash = None
    perceptual_hash = None
    ocr_raw_text = data.get("ocr_raw_text", "")
    extracted_data = None
    itemized_items = []
    non_reimbursable_deductions = 0.0
    math_status = "Not Analyzed"
    extracted_total = None

    if file_path and Path(file_path).exists():
        path = Path(file_path)
        file_hash = file_sha256(path)
        perceptual_hash = ocr_engine.compute_dhash(path)
        if not ocr_raw_text:
            ocr_raw_text, _ = ocr_engine.extract_raw_text(path)

    if ocr_raw_text:
        extracted_data = ocr_engine.parse_receipt_financials(ocr_raw_text, claimed_amount=amount)
        math_status = extracted_data["math_status"]
        extracted_total = extracted_data["extracted_total"]
        itemized_items = extracted_data["line_items"]
        non_reimbursable_deductions = extracted_data["non_reimbursable_deductions"]

        if not merchant and extracted_data["merchant"]:
            merchant = extracted_data["merchant"]
            data["merchant"] = merchant
        if not expense_date and extracted_data["date"]:
            expense_date = extracted_data["date"]
            data["expense_date"] = expense_date

    # 3. Payment Screenshot OCR & Cross-Reconciliation
    payment_verified = 0
    payment_match_note = "Payment screenshot pending."
    payment_raw_text = data.get("payment_raw_text", "")

    if payment_file_path and Path(payment_file_path).exists():
        if not payment_raw_text:
            payment_raw_text, _ = ocr_engine.extract_raw_text(payment_file_path)

    if payment_raw_text:
        pay_info = ocr_engine.parse_payment_screenshot(payment_raw_text)
        if not transaction_ref and pay_info.get("transaction_ref"):
            transaction_ref = pay_info["transaction_ref"]
        if pay_info.get("payment_method") != "Unknown":
            payment_method = pay_info["payment_method"]

        is_v, badge_txt, note_txt = ocr_engine.reconcile_bill_and_payment(amount_inr, pay_info)
        payment_verified = 1 if is_v else 0
        payment_match_note = note_txt
        if not is_v and pay_info.get("payment_amount"):
            flags.append(f"Payment proof mismatch: {note_txt}")
            suspicion_types.append("Payment Proof Mismatch")
            risk_score += 40
        elif is_v:
            flags.append(f"Payment proof reconciled: {note_txt}")

    # 4. Context: Business Trip vs Local Office (using employee's assigned office)
    with connect() as con:
        is_trip, trip_reason = trip_engine.is_business_trip_context(employee, expense_date, city, con, manual_is_trip)
        accumulations = trip_engine.calculate_accumulations(con, employee, expense_date, city, category, amount_inr, exclude_id)
        
        # 5. Multi-Vector Fraud & Integrity Audit
        fraud_result = fraud_engine.audit_claim_integrity(
            data, con, file_hash, perceptual_hash, extracted_data, exclude_id
        )
        flags.extend(fraud_result["flags"])
        suspicion_types.extend(fraud_result["suspicion_types"])
        risk_score = max(risk_score, fraud_result["risk_score"])
        duplicate_of_id = fraud_result["duplicate_of_id"]

        # Check for recycled payment transaction reference across employees
        if transaction_ref:
            txn_dup = con.execute("SELECT id, employee FROM expenses WHERE transaction_ref=? AND id!=?", (transaction_ref, exclude_id or -1)).fetchone()
            if txn_dup:
                flags.append(f"RECYCLED PAYMENT REFERENCE: Transaction ref '{transaction_ref}' was already used on Claim #{txn_dup['id']} by {txn_dup['employee']}!")
                suspicion_types.append("Payment Ref Recycling Fraud")
                risk_score = max(risk_score, 95)

    # 6. Core Policy Rules
    reimbursable = amount_inr

    if amount <= 0:
        flags.append("Missing or invalid amount")
        risk_score += 30
    if not expense_date:
        flags.append("Missing expense date")
        risk_score += 20
    if not merchant:
        flags.append("Missing merchant name")
        risk_score += 15

    required_fields = POLICY["required_fields"].get(category, POLICY["required_fields"]["Other"])
    field_map = {
        "date": expense_date,
        "merchant": merchant,
        "amount": amount,
        "city": city,
        "client_name": client_name,
        "attendees": attendees
    }
    missing = [f for f in required_fields if not field_map.get(f)]
    if missing:
        flags.append(f"Missing mandatory policy fields: {', '.join(missing)}")
        risk_score += 15

    # Non-Reimbursable Line Item Deductions
    if non_reimbursable_deductions > 0:
        flags.append(f"Non-reimbursable line items deducted: -₹{non_reimbursable_deductions:,.2f} ({', '.join(extracted_data['non_reimbursable_reasons'])})")
        reimbursable = max(0.0, reimbursable - non_reimbursable_deductions)
        risk_score += 30

    # Category Caps & Contextual Meal Cap (Trip vs Local)
    if category == "Meals":
        if is_trip:
            cap = POLICY["category_caps"]["Meals_Trip"]
            cap_label = f"Meals (Business Trip cap: ₹{cap:,})"
        else:
            cap = POLICY["category_caps"]["Meals_Local"]
            cap_label = f"Meals (Local Office cap: ₹{cap:,})"
            if not client_name and not description:
                flags.append("Local office meals require client entertainment name or business purpose")
                risk_score += 20
    else:
        cap = POLICY["category_caps"].get(category, POLICY["category_caps"]["Other"])
        cap_label = f"{category} (Cap: ₹{cap:,})"

    if reimbursable > cap:
        excess = reimbursable - cap
        flags.append(f"Category cap exceeded for {cap_label}: Capped reimbursement from ₹{reimbursable:,.2f} to ₹{cap:,.2f} (excess ₹{excess:,.2f})")
        reimbursable = cap
        risk_score += 25

    # Conditional Meal Requirements
    meal_rules = POLICY["meal_rules"]
    if category == "Meals":
        if amount_inr > meal_rules["client_name_required_above"] and not client_name:
            flags.append(f"Client / project name required for meals above ₹{meal_rules['client_name_required_above']:,}")
            risk_score += 20
        if amount_inr > meal_rules["attendees_required_above"] and attendees <= 0:
            flags.append(f"Attendee count required for meals above ₹{meal_rules['attendees_required_above']:,}")
            risk_score += 15
        if attendees > 0:
            per_person = amount_inr / attendees
            if per_person > meal_rules["max_per_attendee"]:
                excess_pp = per_person - meal_rules["max_per_attendee"]
                flags.append(f"Per-attendee meal allowance exceeded: ₹{per_person:,.2f}/person vs ₹{meal_rules['max_per_attendee']:,} limit")
                risk_score += 20

    # City Daily Limit Accumulation
    if category in ("Meals", "Travel", "Accommodation"):
        city_limit = accumulations["daily_limit"]
        daily_spent_before = accumulations["daily_spent_before"]
        remaining_daily = accumulations["remaining_daily"]

        if daily_spent_before + amount_inr > city_limit:
            flags.append(f"City daily per-diem exceeded for {city}: Cumulative daily spend ₹{daily_spent_before + amount_inr:,.2f} exceeds ₹{city_limit:,.2f} limit")
            if remaining_daily > 0:
                reimbursable = min(reimbursable, remaining_daily)
                flags.append(f"Partially capped claim to remaining daily allowance of ₹{remaining_daily:,.2f}")
            else:
                reimbursable = 0.0
                flags.append("Daily per-diem fully exhausted by prior claims today; reimbursable set to ₹0.00")
            risk_score += 25

    # Monthly Employee Category Budget
    if accumulations["monthly_spent_after"] > accumulations["monthly_budget"]:
        over_budget = accumulations["monthly_spent_after"] - accumulations["monthly_budget"]
        flags.append(f"Monthly employee budget exceeded for {category}: ₹{accumulations['monthly_spent_after']:,.2f} vs ₹{accumulations['monthly_budget']:,.2f} cap (over by ₹{over_budget:,.2f})")
        risk_score += 20

    # Multi-Tier Approval Escalation & Project Auto-Approval Cap
    with connect() as con:
        db_settings = get_system_settings(con)
        project_auto_cap = None
        project_name = None
        if project_code:
            p_row = con.execute("SELECT name, auto_approval_cap FROM projects WHERE upper(code)=upper(?)", (project_code,)).fetchone()
            if p_row:
                project_name = p_row["name"]
                if p_row["auto_approval_cap"]:
                    project_auto_cap = float(p_row["auto_approval_cap"])

    auto_cap = project_auto_cap if project_auto_cap is not None else db_settings.get("auto_approval_cap", 1500.0)
    manager_thresh = db_settings.get("manager_approval_threshold", 8000.0)
    vp_thresh = db_settings.get("vp_approval_threshold", 20000.0)

    approval_level = "Auto-Eligible"
    if amount_inr >= vp_thresh:
        approval_level = "VP / Director Approval"
        flags.append(f"High-value claim: Requires VP / Finance Director sign-off (exceeds ₹{vp_thresh:,.0f})")
        risk_score += 15
    elif amount_inr >= manager_thresh:
        approval_level = "Manager Approval"
        flags.append(f"Manager approval required: Claim of ₹{amount_inr:,.2f} exceeds ₹{manager_thresh:,.0f} threshold")
        risk_score += 10
    elif amount_inr > auto_cap:
        approval_level = "Standard Review"
        flags.append(f"Exceeds auto-approval limit of ₹{auto_cap:,.2f}; routed for review")

    # Math Discrepancy Adjustment
    if extracted_data and "Discrepancy Detected" in math_status:
        if extracted_data.get("extracted_total") and extracted_data["extracted_total"] < amount:
            valid_math_inr = round(float(extracted_data["extracted_total"]) * rate, 2)
            reimbursable = min(reimbursable, valid_math_inr)
            flags.append(f"Adjusted reimbursement to verified receipt total: ₹{valid_math_inr:,.2f}")

    risk_score = min(100, risk_score)
    reimbursable = round(max(0.0, reimbursable), 2)

    clean_flags = [f for f in flags if not f.startswith("Payment proof reconciled")]
    if duplicate_of_id or any("duplicate" in f.lower() or "collusion" in f.lower() or "recycled payment" in f.lower() for f in flags):
        status = "Duplicate"
        reimbursable = 0.0
    elif category == "Entertainment" and POLICY["category_caps"]["Entertainment"] == 0 and not client_name:
        status = "Rejected"
        reimbursable = 0.0
    elif reimbursable == 0.0 and amount_inr > 0:
        status = "Rejected"
    elif any("missing mandatory" in f.lower() or "client / project name required" in f.lower() or "attendee count required" in f.lower() for f in flags):
        status = "Needs Info"
    elif not clean_flags and risk_score == 0 and amount_inr <= auto_cap:
        status = "Approved"
        approval_level = "Auto-Approved"
    elif flags or risk_score >= 25 or approval_level != "Auto-Eligible":
        status = "Needs Review"
    else:
        status = "Approved"

    explanation_parts = []
    if status == "Approved":
        if project_auto_cap and amount_inr <= project_auto_cap:
            explanation_parts.append(f"Auto-approved under Project {project_code} ({project_name}) policy limit (Cap: ₹{project_auto_cap:,.2f}).")
        elif amount_inr <= auto_cap:
            explanation_parts.append(f"Auto-approved: Claim ₹{amount_inr:,.2f} is within company auto-approval cap (₹{auto_cap:,.2f}).")
        else:
            explanation_parts.append(f"Within policy limits ({trip_reason}). No violations detected.")
    elif status == "Duplicate":
        explanation_parts.append("Duplicate claim or payment proof identified across submission channels. Marked non-reimbursable.")
    elif status == "Rejected":
        explanation_parts.append("Claim rejected based on policy rules (non-reimbursable category or zero allowable balance).")
    elif status == "Needs Info":
        explanation_parts.append("Action required: Essential policy compliance details (e.g. client name, attendees, or merchant) are missing.")
    else:
        explanation_parts.append("Audit flags identified for finance review.")

    if reimbursable < amount_inr and reimbursable > 0:
        explanation_parts.append(f"Reimbursement capped at ₹{reimbursable:,.2f} based on applicable category/per-diem limits.")
    if non_reimbursable_deductions > 0:
        explanation_parts.append(f"Deducted ₹{non_reimbursable_deductions:,.2f} for disallowed items.")
    if approval_level not in ("Auto-Eligible", "Auto-Approved"):
        explanation_parts.append(f"Requires sign-off: {approval_level}.")

    explanation = " ".join(explanation_parts)

    upi_app = data.get("upi_app") or "Google Pay"
    upi_vpa = (data.get("upi_vpa") or "").strip()

    return {
        "employee": employee,
        "expense_date": expense_date,
        "merchant": merchant,
        "category": category,
        "city": city,
        "amount": amount,
        "currency": currency,
        "amount_inr": amount_inr,
        "payment_method": payment_method,
        "transaction_ref": transaction_ref,
        "upi_app": upi_app,
        "upi_vpa": upi_vpa,
        "payment_verified": payment_verified,
        "payment_match_note": payment_match_note,
        "client_name": client_name,
        "project_code": project_code,
        "project_auto_cap": project_auto_cap,
        "attendees": attendees,
        "attendee_names": attendee_names,
        "description": description,
        "is_trip": 1 if is_trip else 0,
        "status": status,
        "reimbursable": reimbursable,
        "risk_score": risk_score,
        "flags": flags,
        "suspicion_types": suspicion_types,
        "explanation": explanation,
        "file_hash": file_hash,
        "perceptual_hash": perceptual_hash,
        "duplicate_of_id": duplicate_of_id,
        "math_status": math_status,
        "extracted_amount": extracted_total,
        "non_reimbursable_deduction": non_reimbursable_deductions,
        "itemized_items": itemized_items,
        "ocr_raw_text": ocr_raw_text,
        "approval_level": approval_level
    }

# ----------------- SYSTEM & HEALTH MONITORING -----------------

@app.route("/health")
@app.route("/api/health")
def health():
    """Production health-check endpoint for container orchestration and uptime monitors."""
    db_ok = False
    try:
        with connect() as con:
            row = con.execute("SELECT 1").fetchone()
            if row and row[0] == 1:
                db_ok = True
    except Exception as e:
        app.logger.warning(f"Health check database ping: {e}")

    status_code = 200 if db_ok else 503
    return jsonify({
        "status": "healthy" if db_ok else "degraded",
        "service": "The Receipt Graveyard - AI Expense Auditor",
        "database": "connected" if db_ok else "error",
        "ocr_engine": "RapidOCR/ONNX Hybrid",
        "timestamp": datetime.now().isoformat()
    }), status_code

# ----------------- ROUTES: AUTHENTICATION & PERSONAS -----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            if session.get("role") == "admin":
                return redirect(url_for("admin_console"))
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()

    with connect() as con:
        user = con.execute("SELECT * FROM users WHERE lower(email)=?", (email,)).fetchone()
        if user and user["password"] == password:
            user_status = (user["status"] or "APPROVED").upper()
            
            if user_status == "PENDING_APPROVAL":
                flash("Your account is awaiting administrator approval. You'll be able to access the platform once your registration has been reviewed.", "warning")
                return redirect(url_for("login"))
            elif user_status == "REJECTED":
                reason = user["rejection_reason"] or "Registration criteria not met."
                flash(f"Your registration request was rejected by an administrator. Reason: {reason}", "error")
                return redirect(url_for("login"))
            elif user_status == "SUSPENDED" or (user["is_active"] is not None and user["is_active"] == 0):
                flash("Your account has been suspended by an administrator. Please contact your organization administrator.", "error")
                return redirect(url_for("login"))
            elif user_status != "APPROVED":
                flash("Your account is inactive. Please contact your administrator.", "error")
                return redirect(url_for("login"))

            # Approved & Active User
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["user_name"] = user["name"]
            flash(f"Welcome back, {user['name']} ({user['role'].capitalize()})!", "success")
            if user["role"] == "admin":
                return redirect(url_for("admin_console"))
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password. Please verify your credentials or choose a Quick Demo Persona below.", "error")
            return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("login.html", active_tab="register")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()
    role = request.form.get("role", "employee").strip().lower()
    if role not in ("employee", "accounts"):
        role = "employee"
    employee_id = request.form.get("employee_id", "").strip()
    department = request.form.get("department", "Operations").strip()
    designation = request.form.get("designation", "").strip()
    phone = request.form.get("phone", "").strip()
    office_id = request.form.get("office_id") or 1
    reason_for_access = request.form.get("reason_for_access", "").strip()

    if not name or not email or not password:
        flash("Please fill in all mandatory fields: Full Name, Email, and Password.", "error")
        return redirect(url_for("register"))

    if "@" not in email or "." not in email:
        flash("Please provide a valid official work email address.", "error")
        return redirect(url_for("register"))

    if len(password) < 6:
        flash("Password must be at least 6 characters long.", "error")
        return redirect(url_for("register"))

    if confirm_password and password != confirm_password:
        flash("Passwords do not match. Please re-enter your password.", "error")
        return redirect(url_for("register"))

    avatar_colors = ['#0f766e', '#15803d', '#0369a1', '#b45309', '#7c3aed', '#4338ca']
    avatar_color = avatar_colors[len(name) % len(avatar_colors)]

    with connect() as con:
        existing = con.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
        if existing:
            flash("An account with this email address already exists. Please sign in.", "error")
            return redirect(url_for("login"))

        if employee_id:
            existing_emp = con.execute("SELECT id FROM users WHERE employee_id=? AND employee_id!=''", (employee_id,)).fetchone()
            if existing_emp:
                flash(f"An account with Employee ID '{employee_id}' already exists.", "error")
                return redirect(url_for("register"))

        con.execute("""
        INSERT INTO users (
            name, email, password, role, office_id, department, designation, employee_id, 
            phone, reason_for_access, avatar_color, status, is_active, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_APPROVAL', 0, ?)
        """, (
            name, email, password, role, office_id, department, designation, employee_id,
            phone, reason_for_access, avatar_color, datetime.now().strftime("%Y-%m-%d %H:%M")
        ))
        new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Dispatch alert notification to all system administrators
        admins = con.execute("SELECT id FROM users WHERE role='admin'").fetchall()
        for adm in admins:
            create_notification(
                con, adm["id"], None,
                "New Registration Pending Review",
                f"{name} ({role.capitalize()}) requested access for {department}. Requires admin approval.",
                "admin"
            )
        con.commit()

    return redirect(url_for("registration_pending"))

@app.route("/registration-pending")
def registration_pending():
    return render_template("pending_approval.html")

@app.route("/admin/users/<int:user_id>/approve", methods=["POST"])
@login_required
@role_required(["admin"])
def approve_user_registration(user_id):
    with connect() as con:
        user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            flash("User not found.", "error")
            return redirect(url_for("admin_console"))

        admin_name = session.get("user_name", "Administrator")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        con.execute("""
        UPDATE users 
        SET status='APPROVED', is_active=1, reviewed_by=?, reviewed_at=?, rejection_reason=NULL 
        WHERE id=?
        """, (admin_name, now_str, user_id))

        create_notification(
            con, user_id, None,
            "Account Approved",
            "Your account registration has been approved! You can now sign in and submit expenses.",
            "success"
        )
        con.commit()
        flash(f"Account for {user['name']} ({user['email']}) approved successfully.", "success")
    return redirect(url_for("admin_console"))

@app.route("/admin/users/<int:user_id>/reject", methods=["POST"])
@login_required
@role_required(["admin"])
def reject_user_registration(user_id):
    reason = request.form.get("rejection_reason", "").strip() or "Registration criteria not met."
    with connect() as con:
        user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            flash("User not found.", "error")
            return redirect(url_for("admin_console"))

        admin_name = session.get("user_name", "Administrator")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        con.execute("""
        UPDATE users 
        SET status='REJECTED', is_active=0, reviewed_by=?, reviewed_at=?, rejection_reason=? 
        WHERE id=?
        """, (admin_name, now_str, reason, user_id))

        create_notification(
            con, user_id, None,
            "Account Registration Rejected",
            f"Your registration was rejected. Reason: {reason}",
            "danger"
        )
        con.commit()
        flash(f"Registration for {user['name']} was rejected with reason: {reason}", "info")
    return redirect(url_for("admin_console"))

@app.route("/admin/users/<int:user_id>/suspend", methods=["POST"])
@login_required
@role_required(["admin"])
def suspend_user(user_id):
    if user_id == session.get("user_id"):
        flash("You cannot suspend your own administrator account.", "error")
        return redirect(url_for("admin_console"))
    with connect() as con:
        user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            flash("User not found.", "error")
            return redirect(url_for("admin_console"))

        admin_name = session.get("user_name", "Administrator")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        con.execute("""
        UPDATE users 
        SET status='SUSPENDED', is_active=0, reviewed_by=?, reviewed_at=? 
        WHERE id=?
        """, (admin_name, now_str, user_id))
        con.commit()
        flash(f"User account {user['name']} has been suspended.", "warning")
    return redirect(url_for("admin_console"))

@app.route("/admin/users/<int:user_id>/reactivate", methods=["POST"])
@login_required
@role_required(["admin"])
def reactivate_user(user_id):
    with connect() as con:
        user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            flash("User not found.", "error")
            return redirect(url_for("admin_console"))

        admin_name = session.get("user_name", "Administrator")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        con.execute("""
        UPDATE users 
        SET status='APPROVED', is_active=1, reviewed_by=?, reviewed_at=?, rejection_reason=NULL 
        WHERE id=?
        """, (admin_name, now_str, user_id))
        con.commit()
        flash(f"User account {user['name']} has been reactivated.", "success")
    return redirect(url_for("admin_console"))

# ----------------- OCR ENDPOINTS -----------------

@app.route("/api/scan-receipt", methods=["POST"])
def api_scan_receipt():
    """
    Dedicated OCR endpoint.
    Accepts uploaded receipt image/pdf or camera base64 data.
    Runs multi-stage image preprocessing + RapidOCR + structured financial parsing.
    Returns extracted amount, merchant, date, currency, line items, confidence, and warnings.
    """
    temp_path = None
    saved_filename = None
    file_hash = None
    perceptual_hash = None

    if "receipt" in request.files and request.files["receipt"].filename:
        file = request.files["receipt"]
        if allowed_file(file.filename):
            saved_filename = f"scan_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            temp_path = UPLOAD_DIR / saved_filename
            file.save(temp_path)
    elif request.form.get("camera_data"):
        saved_filename, temp_path = save_base64_camera_image(request.form.get("camera_data"), prefix="scan_cam_")
    elif request.is_json and request.json.get("camera_data"):
        saved_filename, temp_path = save_base64_camera_image(request.json.get("camera_data"), prefix="scan_cam_")

    if not temp_path or not Path(temp_path).exists():
        return jsonify({
            "success": False,
            "error": "No valid receipt file or camera image was uploaded.",
            "suggested": None
        }), 400

    try:
        path = Path(temp_path)
        file_hash = file_sha256(path)
        perceptual_hash = ocr_engine.compute_dhash(path)

        # Preprocess if image
        processed_path = path
        preproc_meta = {"strategy": "none", "operations": []}
        if path.suffix.lower() != ".pdf":
            processed_path, preproc_meta = ocr_engine.preprocess_receipt_image(path, strategy="AUTO")

        raw_text, ocr_note = ocr_engine.extract_raw_text(processed_path)
        financials = ocr_engine.parse_receipt_financials(raw_text)

        # Categorization heuristic based on merchant name and line items
        suggested_category = "Meals & Entertainment"
        lower_merchant = (financials.get("merchant") or "").lower()
        lower_text = raw_text.lower()
        if any(w in lower_merchant or w in lower_text for w in ["uber", "ola", "indigo", "air india", "taxi", "flight", "railway", "irctc", "metro"]):
            suggested_category = "Travel"
        elif any(w in lower_merchant or w in lower_text for w in ["marriott", "taj", "hyatt", "hotel", "inn", "stay", "resort"]):
            suggested_category = "Lodging"
        elif any(w in lower_merchant or w in lower_text for w in ["amazon", "croma", "dell", "hp", "hardware", "staples", "stationery"]):
            suggested_category = "Office Supplies"
        elif any(w in lower_merchant or w in lower_text for w in ["software", "cloud", "aws", "google cloud", "github", "zoom"]):
            suggested_category = "Software & Subscriptions"

        return jsonify({
            "success": True,
            "filename": saved_filename,
            "raw_text": raw_text,
            "ocr_note": ocr_note,
            "preprocessing": preproc_meta,
            "file_hash": file_hash,
            "perceptual_hash": perceptual_hash,
            "suggested": {
                "amount": financials.get("extracted_total"),
                "merchant": financials.get("merchant"),
                "date": financials.get("date"),
                "currency": financials.get("currency") or "INR",
                "category": suggested_category,
                "subtotal": financials.get("subtotal"),
                "tax": financials.get("tax"),
                "tip": financials.get("tip"),
                "discount": financials.get("discount"),
                "gstin": financials.get("gstin")
            },
            "line_items": financials.get("line_items", []),
            "candidate_totals": financials.get("candidate_totals", []),
            "confidence": financials.get("confidence", {}).get("overall", 0.0),
            "confidence_band": financials.get("confidence_band", "Medium"),
            "uncertainty_flags": financials.get("uncertainty_flags", []),
            "math_status": financials.get("math_status", "Not Analyzed")
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"OCR processing encountered an issue: {str(e)}",
            "suggested": None
        }), 500

@app.route("/api/scan-payment", methods=["POST"])
def api_scan_payment():
    """
    Dedicated Payment Proof OCR endpoint.
    Extracts payment amount, UPI UTR / Transaction ID, payment platform, and status.
    """
    temp_path = None
    saved_filename = None

    if "payment_screenshot" in request.files and request.files["payment_screenshot"].filename:
        file = request.files["payment_screenshot"]
        if allowed_file(file.filename):
            saved_filename = f"pay_{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            temp_path = UPLOAD_DIR / saved_filename
            file.save(temp_path)
    elif request.form.get("payment_camera_data"):
        saved_filename, temp_path = save_base64_camera_image(request.form.get("payment_camera_data"), prefix="pay_cam_")
    elif request.is_json and request.json.get("payment_camera_data"):
        saved_filename, temp_path = save_base64_camera_image(request.json.get("payment_camera_data"), prefix="pay_cam_")

    if not temp_path or not Path(temp_path).exists():
        return jsonify({
            "success": False,
            "error": "No valid payment screenshot was uploaded."
        }), 400

    try:
        raw_text, ocr_note = ocr_engine.extract_raw_text(temp_path)
        pay_info = ocr_engine.parse_payment_screenshot(raw_text)
        return jsonify({
            "success": True,
            "filename": saved_filename,
            "raw_text": raw_text,
            "payment_info": pay_info
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session.get("user_id")
    with connect() as con:
        if request.method == "POST":
            phone = request.form.get("phone", "").strip()
            department = request.form.get("department", "").strip()
            new_password = request.form.get("new_password", "").strip()
            if new_password:
                con.execute("UPDATE users SET phone=?, department=?, password=? WHERE id=?", (phone, department, new_password, user_id))
            else:
                con.execute("UPDATE users SET phone=?, department=? WHERE id=?", (phone, department, user_id))
            con.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for("profile"))

        user_row = con.execute("""
        SELECT u.*, o.name as office_name, o.city as office_city, o.state as office_state, o.address as office_address, o.local_meal_cap 
        FROM users u 
        LEFT JOIN offices o ON u.office_id = o.id 
        WHERE u.id = ?
        """, (user_id,)).fetchone()

        claims = con.execute("SELECT * FROM expenses WHERE lower(employee)=lower(?) ORDER BY id DESC LIMIT 10", (user_row["name"],)).fetchall()
        user_stats = {
            "total_claims": len(claims),
            "approved_amount": sum(float(c["reimbursable"] or 0) for c in claims if c["status"] == "Approved"),
            "pending_count": sum(1 for c in claims if c["status"] in ("Needs Review", "Needs Info")),
            "approved_count": sum(1 for c in claims if c["status"] == "Approved"),
            "total_claimed": sum(float(c["amount_inr"] or 0) for c in claims if c["status"] != "Duplicate")
        }

    return render_template("profile.html", user=user_row, claims=claims, stats=user_stats, policy=POLICY)

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("index"))

@app.route("/switch-user/<int:user_id>")
def switch_user(user_id):
    """1-Click persona switch for quick hackathon judging demonstrations."""
    with connect() as con:
        user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if user:
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["user_name"] = user["name"]
            flash(f"Switched persona to: {user['name']} [{user['role'].upper()}]", "success")
            if user["role"] == "admin":
                return redirect(url_for("admin_console"))
            return redirect(url_for("dashboard"))
    return redirect(url_for("dashboard"))

# ----------------- ROUTES: ADMIN CONSOLE & GOVERNANCE -----------------

@app.route("/admin")
@login_required
@role_required(["admin"])
def admin_console():
    with connect() as con:
        users = con.execute("""
        SELECT u.*, o.name as office_name, o.city as office_city, o.local_meal_cap 
        FROM users u 
        LEFT JOIN offices o ON u.office_id = o.id 
        ORDER BY u.role, u.id
        """).fetchall()

        pending_users = con.execute("""
        SELECT u.*, o.name as office_name, o.city as office_city, o.local_meal_cap 
        FROM users u 
        LEFT JOIN offices o ON u.office_id = o.id 
        WHERE u.status = 'PENDING_APPROVAL'
        ORDER BY u.id DESC
        """).fetchall()

        approved_users = con.execute("""
        SELECT u.*, o.name as office_name, o.city as office_city, o.local_meal_cap 
        FROM users u 
        LEFT JOIN offices o ON u.office_id = o.id 
        WHERE u.status = 'APPROVED'
        ORDER BY u.role, u.id
        """).fetchall()

        inactive_users = con.execute("""
        SELECT u.*, o.name as office_name, o.city as office_city, o.local_meal_cap 
        FROM users u 
        LEFT JOIN offices o ON u.office_id = o.id 
        WHERE u.status IN ('REJECTED', 'SUSPENDED')
        ORDER BY u.id DESC
        """).fetchall()

        offices = con.execute("""
        SELECT o.*, COUNT(u.id) as employee_count 
        FROM offices o 
        LEFT JOIN users u ON o.id = u.office_id 
        GROUP BY o.id
        """).fetchall()

        projects = con.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
        system_settings = get_system_settings(con)

    return render_template(
        "admin.html",
        users=users,
        pending_users=pending_users,
        approved_users=approved_users,
        inactive_users=inactive_users,
        offices=offices,
        projects=projects,
        system_settings=system_settings,
        policy=POLICY
    )

@app.route("/admin/add-user", methods=["POST"])
@login_required
@role_required(["admin"])
def add_user():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip() or "welcome123"
    role = request.form.get("role", "employee").strip().lower()
    office_id = request.form.get("office_id") or 1
    department = request.form.get("department", "General").strip()
    phone = request.form.get("phone", "").strip()
    avatar_colors = ['#0f766e', '#15803d', '#0369a1', '#b45309', '#7c3aed', '#4338ca']
    avatar_color = avatar_colors[len(name) % len(avatar_colors)]

    if not name or not email:
        flash("Name and email are required to register a staff profile.", "error")
        return redirect(url_for("admin_console"))

    with connect() as con:
        existing = con.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
        if existing:
            flash(f"A user with email '{email}' already exists.", "error")
            return redirect(url_for("admin_console"))

        con.execute("""
        INSERT INTO users (name, email, password, role, office_id, department, phone, avatar_color)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, email, password, role, office_id, department, phone, avatar_color))
        con.commit()

    flash(f"New staff profile '{name}' added with role [{role.upper()}]!", "success")
    return redirect(url_for("admin_console"))

@app.route("/admin/update-user", methods=["POST"])
@login_required
@role_required(["admin"])
def update_user():
    user_id = request.form.get("user_id")
    role = request.form.get("role", "employee").strip().lower()
    office_id = request.form.get("office_id")
    department = request.form.get("department", "").strip()
    phone = request.form.get("phone", "").strip()

    with connect() as con:
        con.execute("""
        UPDATE users SET role=?, office_id=?, department=?, phone=? WHERE id=?
        """, (role, office_id, department, phone, user_id))
        con.commit()

    flash("User role and jurisdiction profile updated successfully!", "success")
    return redirect(url_for("admin_console"))

@app.route("/admin/add-project", methods=["POST"])
@login_required
@role_required(["admin"])
def add_project():
    code = request.form.get("code", "").strip().upper()
    name = request.form.get("name", "").strip()
    client_name = request.form.get("client_name", "").strip()
    try:
        budget = float(request.form.get("budget") or 100000)
    except ValueError:
        budget = 100000.0
    try:
        auto_approval_cap = float(request.form.get("auto_approval_cap") or 2000)
    except ValueError:
        auto_approval_cap = 2000.0
    manager_name = request.form.get("manager_name", "").strip()
    description = request.form.get("description", "").strip()

    if not code or not name:
        flash("Project code and name are required.", "error")
        return redirect(url_for("admin_console"))

    with connect() as con:
        con.execute("""
        INSERT INTO projects (code, name, client_name, budget, auto_approval_cap, manager_name, status, description)
        VALUES (?, ?, ?, ?, ?, ?, 'Active', ?)
        """, (code, name, client_name, budget, auto_approval_cap, manager_name, description))
        con.commit()

    flash(f"Enterprise project '{code} - {name}' registered with max auto-approval reimbursement cap of ₹{auto_approval_cap:,.2f}!", "success")
    return redirect(url_for("admin_console"))

@app.route("/admin/update-policy-thresholds", methods=["POST"])
@login_required
@role_required(["admin"])
def update_policy_thresholds():
    try:
        auto_cap = float(request.form.get("auto_approval_cap") or 1500)
        mgr_thresh = float(request.form.get("manager_approval_threshold") or 8000)
        vp_thresh = float(request.form.get("vp_approval_threshold") or 20000)
        editing_hours = float(request.form.get("editing_window_hours") or 24.0)
    except ValueError:
        flash("Invalid threshold numbers entered.", "error")
        return redirect(url_for("admin_console"))

    with connect() as con:
        con.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('auto_approval_cap', ?)", (str(auto_cap),))
        con.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('manager_approval_threshold', ?)", (str(mgr_thresh),))
        con.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('vp_approval_threshold', ?)", (str(vp_thresh),))
        con.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES ('editing_window_hours', ?)", (str(editing_hours),))
        con.commit()

    flash(f"System policy approval thresholds updated! Auto-approval cap: ₹{auto_cap:,.2f}, Editing window: {editing_hours} hrs.", "success")
    return redirect(url_for("admin_console"))

@app.route("/admin/update-office-mapping", methods=["POST"])
@login_required
@role_required(["admin"])
def update_office_mapping():
    user_id = request.form.get("user_id")
    office_id = request.form.get("office_id")
    department = request.form.get("department", "").strip()

    with connect() as con:
        con.execute(
            "UPDATE users SET office_id=?, department=? WHERE id=?",
            (office_id, department, user_id)
        )
        con.commit()
    flash("Employee office mapping updated successfully! The policy engine will now apply their new home city rules.", "success")
    return redirect(url_for("admin_console"))

@app.route("/admin/add-office", methods=["POST"])
@login_required
@role_required(["admin"])
def add_office():
    name = request.form.get("name", "").strip()
    city = request.form.get("city", "").strip()
    state = request.form.get("state", "").strip()
    address = request.form.get("address", "").strip()
    try:
        meal_cap = float(request.form.get("local_meal_cap") or 1200)
    except ValueError:
        meal_cap = 1200.0

    with connect() as con:
        con.execute("""
        INSERT INTO offices (name, city, state, address, is_headquarters, local_meal_cap)
        VALUES (?, ?, ?, ?, 0, ?)
        """, (name, city, state, address, meal_cap))
        con.commit()

    flash(f"New company office '{name}' ({city}) registered!", "success")
    return redirect(url_for("admin_console"))

# ----------------- ROUTES: PROJECT BUDGET ALLOCATION & GOVERNANCE -----------------

@app.route("/admin/allocations", methods=["GET", "POST"])
@login_required
@role_required(["admin", "accounts"])
def admin_allocations():
    """
    Accounts Admin screen to:
    - View and search employee-wise project spending caps
    - Assign new spending caps
    - View spent, reserved, and remaining balances
    - View immutable adjustment audit history
    """
    if request.method == "POST":
        project_id = int(request.form.get("project_id"))
        user_id = int(request.form.get("user_id"))
        try:
            cap = float(request.form.get("cap") or 0)
        except ValueError:
            cap = 0.0

        start_date = request.form.get("start_date") or None
        end_date = request.form.get("end_date") or None
        actor = session.get("user_name", "Accounts Admin")

        with connect() as con:
            budget_engine.get_or_create_allocation(
                con, project_id, user_id, cap=cap, start_date=start_date, end_date=end_date, actor=actor
            )
            con.commit()

        flash(f"Project budget allocation of ₹{cap:,.2f} assigned successfully!", "success")
        return redirect(url_for("admin_allocations"))

    # GET request: Filtering & Search
    search_q = request.args.get("search", "").strip().lower()
    project_filter = request.args.get("project_id")
    status_filter = request.args.get("status")

    with connect() as con:
        query = """
            SELECT a.*, p.name as project_name, p.code as project_code, p.budget as project_budget,
                   u.name as user_name, u.email as user_email, u.department as user_department
            FROM project_allocations a
            JOIN projects p ON a.project_id = p.id
            JOIN users u ON a.user_id = u.id
            WHERE 1=1
        """
        params = []
        if project_filter:
            query += " AND a.project_id = ?"
            params.append(project_filter)
        if status_filter:
            query += " AND a.status = ?"
            params.append(status_filter)
        if search_q:
            query += " AND (lower(u.name) LIKE ? OR lower(p.code) LIKE ? OR lower(p.name) LIKE ?)"
            params.extend([f"%{search_q}%", f"%{search_q}%", f"%{search_q}%"])

        query += " ORDER BY a.id DESC"
        alloc_rows = con.execute(query, params).fetchall()

        # Format allocation rows
        allocations = []
        for r in alloc_rows:
            d = dict(r)
            cap = float(d["allocated_cap"] or 0)
            appr = float(d["approved_expenditure"] or 0)
            d["percent_consumed"] = round((appr / cap * 100.0), 1) if cap > 0 else 0.0
            allocations.append(d)

        # Audit History
        adjustments_history = con.execute("""
            SELECT adj.*, p.code as project_code, p.name as project_name, u.name as user_name
            FROM allocation_adjustments adj
            JOIN project_allocations a ON adj.allocation_id = a.id
            JOIN projects p ON a.project_id = p.id
            JOIN users u ON a.user_id = u.id
            ORDER BY adj.id DESC LIMIT 100
        """).fetchall()

        # Double-entry ledger audit
        ledger_entries = con.execute("""
            SELECT l.*, p.code as project_code, u.name as user_name
            FROM budget_ledger l
            JOIN projects p ON l.project_id = p.id
            JOIN users u ON l.user_id = u.id
            ORDER BY l.id DESC LIMIT 100
        """).fetchall()

        all_projects = con.execute("SELECT * FROM projects WHERE status='Active' ORDER BY code").fetchall()
        all_users = con.execute("SELECT * FROM users WHERE is_active=1 ORDER BY name").fetchall()

    return render_template(
        "admin_allocations.html",
        allocations=allocations,
        adjustments_history=adjustments_history,
        ledger_entries=ledger_entries,
        all_projects=all_projects,
        all_users=all_users,
        search_q=search_q,
        project_filter=project_filter,
        status_filter=status_filter
    )

@app.route("/admin/allocations/<int:allocation_id>/adjust", methods=["POST"])
@login_required
@role_required(["admin", "accounts"])
def adjust_allocation(allocation_id):
    """
    Authorized increase or decrease of an employee's project spending cap.
    Guarantees remaining balance is not silently reset.
    Stores immutable reason and audit log.
    """
    try:
        new_cap = float(request.form.get("new_cap") or 0)
    except ValueError:
        flash("Invalid budget cap amount entered.", "error")
        return redirect(request.referrer or url_for("admin_allocations"))

    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Mandatory Requirement: You must provide a valid audit reason to adjust a project budget cap.", "error")
        return redirect(request.referrer or url_for("admin_allocations"))

    actor = session.get("user_name", "Accounts Admin")

    with connect() as con:
        try:
            res = budget_engine.adjust_allocation_cap(con, allocation_id, new_cap, reason, actor=actor)
            con.commit()
            flash(
                f"Project cap adjusted! Previous: ₹{res['previous_cap']:,.2f} → New: ₹{res['new_cap']:,.2f}. "
                f"Updated Remaining Balance: ₹{res['remaining_balance']:,.2f}.",
                "success"
            )
        except Exception as e:
            flash(f"Cap adjustment failed: {str(e)}", "error")

    return redirect(request.referrer or url_for("admin_allocations"))

@app.route("/admin/allocations/export")
@login_required
@role_required(["admin", "accounts"])
def export_allocations():
    """Generates CSV export of all project spending allocations and remaining balances."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Allocation ID", "Project Code", "Project Name", "Employee Name", "Employee Email",
        "Allocated Cap (INR)", "Approved Expenditure (INR)", "Active Reservations (INR)",
        "Remaining Balance (INR)", "Status", "Start Date", "End Date", "Last Updated"
    ])

    with connect() as con:
        rows = con.execute("""
            SELECT a.*, p.code as project_code, p.name as project_name, u.name as user_name, u.email as user_email
            FROM project_allocations a
            JOIN projects p ON a.project_id = p.id
            JOIN users u ON a.user_id = u.id
            ORDER BY a.project_id, u.name
        """).fetchall()

        for r in rows:
            writer.writerow([
                r["id"], r["project_code"], r["project_name"], r["user_name"], r["user_email"],
                f"{float(r['allocated_cap'] or 0):.2f}",
                f"{float(r['approved_expenditure'] or 0):.2f}",
                f"{float(r['reserved_expenditure'] or 0):.2f}",
                f"{float(r['remaining_balance'] or 0):.2f}",
                r["status"], r["start_date"] or "", r["end_date"] or "", r["updated_at"]
            ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=project_allocations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
    )

@app.route("/api/projects/<int:project_id>/allocations")
@login_required
def api_project_allocations(project_id):
    """API endpoint returning all employee budget allocations for a project."""
    with connect() as con:
        rows = con.execute("""
            SELECT a.*, u.name as user_name, u.email as user_email
            FROM project_allocations a
            JOIN users u ON a.user_id = u.id
            WHERE a.project_id = ?
        """, (project_id,)).fetchall()
        return jsonify([dict(r) for r in rows])

@app.route("/api/allocations/my-balance")
@login_required
def api_my_allocation_balance():
    """API endpoint returning live remaining budget for an employee on a selected project."""
    project_id = request.args.get("project_id")
    user_id = session.get("user_id")

    if not project_id:
        return jsonify({"error": "Missing project_id parameter"}), 400

    with connect() as con:
        alloc = con.execute("""
            SELECT * FROM project_allocations 
            WHERE project_id = ? AND user_id = ?
        """, (project_id, user_id)).fetchone()

        if not alloc:
            return jsonify({
                "assigned": False,
                "allocated_cap": 0.0,
                "approved_expenditure": 0.0,
                "remaining_balance": 0.0,
                "status": "NOT_ASSIGNED"
            })

        bal = budget_engine.calculate_allocation_balance(con, alloc["id"])
        bal["assigned"] = True
        bal["status"] = alloc["status"]
        return jsonify(bal)

# ----------------- ROUTES: MAIN APPLICATION -----------------

@app.route("/")
def index():
    if session.get("user_id"):
        user_role = session.get("role", "employee")
        if user_role == "admin":
            return redirect(url_for("admin_console"))
        return redirect(url_for("dashboard"))
    return render_template("landing.html")

@app.route("/landing")
def landing():
    return render_template("landing.html")

@app.route("/dashboard")
@login_required
def dashboard():
    user_role = session.get("role", "accounts")
    user_id = session.get("user_id", 2)
    view_all = request.args.get("view_all") == "1"

    # Filters
    filter_proj = request.args.get("project_code")
    filter_status = request.args.get("status")
    filter_approval = request.args.get("approval_status")
    filter_verification = request.args.get("verification_status")
    filter_budget = request.args.get("budget_status")
    filter_emp = request.args.get("employee")

    with connect() as con:
        current_user = con.execute("""
            SELECT u.*, o.name as office_name, o.city as office_city, o.local_meal_cap 
            FROM users u LEFT JOIN offices o ON u.office_id = o.id 
            WHERE u.id = ?
        """, (user_id,)).fetchone()
        emp_name = current_user["name"] if current_user else ""

        # Query builder for expenses
        where_clauses = []
        params = []

        if user_role == "employee":
            where_clauses.append("lower(employee) = lower(?)")
            params.append(emp_name)
        elif filter_emp:
            where_clauses.append("lower(employee) = lower(?)")
            params.append(filter_emp)

        if filter_proj:
            where_clauses.append("upper(project_code) = upper(?)")
            params.append(filter_proj)
        if filter_status:
            where_clauses.append("status = ?")
            params.append(filter_status)
        if filter_approval:
            where_clauses.append("approval_status = ?")
            params.append(filter_approval)
        if filter_verification:
            where_clauses.append("evidence_verification_status = ?")
            params.append(filter_verification)
        if filter_budget:
            where_clauses.append("budget_status = ?")
            params.append(filter_budget)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        rows = con.execute(f"SELECT * FROM expenses {where_sql} ORDER BY id DESC", params).fetchall()
        trips = trip_engine.reconstruct_trips(rows)

        # Baseline Stats
        stats = {
            "total": len(rows),
            "pending": sum(1 for r in rows if r["status"] in ("Needs Review", "Needs Info")),
            "approved": sum(1 for r in rows if r["status"] == "Approved"),
            "flagged": sum(1 for r in rows if r["status"] in ("Rejected", "Duplicate")),
            "claimed": sum(float(r["amount_inr"] or 0) for r in rows if r["status"] != "Duplicate"),
            "reimbursable": sum(float(r["reimbursable"] or 0) for r in rows if r["status"] == "Approved"),
            "trips_count": len(trips),
            "duplicates_count": sum(1 for r in rows if r["status"] == "Duplicate"),
            "high_risk_count": sum(1 for r in rows if (r["risk_score"] or 0) >= 50),
            # Extended Dimensions
            "auto_approved_count": sum(1 for r in rows if (r["approval_status"] or "") == "AUTO_APPROVED"),
            "pending_accounts_count": sum(1 for r in rows if (r["approval_status"] or "") == "PENDING_ACCOUNTS"),
            "pending_admin_count": sum(1 for r in rows if (r["approval_status"] or "") == "PENDING_ACCOUNTS_ADMIN"),
            "mismatch_count": sum(1 for r in rows if (r["evidence_verification_status"] or "") == "MISMATCH"),
            "needs_info_count": sum(1 for r in rows if (r["approval_status"] or "") == "NEEDS_INFORMATION" or (r["evidence_verification_status"] or "") == "INCOMPLETE"),
            "exceeded_budget_count": sum(1 for r in rows if (r["budget_status"] or "") in ("INSUFFICIENT_BALANCE", "CAP_EXHAUSTED"))
        }

        user_allocations = []
        all_allocations = []
        budget_summary = {}

        if user_role == "employee":
            alloc_rows = con.execute("""
                SELECT a.*, p.name as project_name, p.code as project_code, p.status as project_status, p.description as project_description
                FROM project_allocations a
                JOIN projects p ON a.project_id = p.id
                WHERE a.user_id = ?
                ORDER BY a.id DESC
            """, (user_id,)).fetchall()
            for ar in alloc_rows:
                cap = float(ar["allocated_cap"] or 0)
                appr = float(ar["approved_expenditure"] or 0)
                resv = float(ar["reserved_expenditure"] or 0)
                rem = float(ar["remaining_balance"] or 0)
                pct = round((appr / cap * 100.0), 1) if cap > 0 else 0.0
                d = dict(ar)
                d["percent_consumed"] = pct
                user_allocations.append(d)
        else:
            # Finance and Accounts Admin: Overall Project Budget Aggregates
            alloc_agg = con.execute("""
                SELECT 
                    COALESCE(SUM(allocated_cap), 0.0) as total_allocated,
                    COALESCE(SUM(approved_expenditure), 0.0) as total_approved,
                    COALESCE(SUM(reserved_expenditure), 0.0) as total_reserved,
                    COALESCE(SUM(remaining_balance), 0.0) as total_remaining
                FROM project_allocations
            """).fetchone()

            all_alloc_rows = con.execute("""
                SELECT a.*, p.name as project_name, p.code as project_code, u.name as user_name, u.email as user_email
                FROM project_allocations a
                JOIN projects p ON a.project_id = p.id
                JOIN users u ON a.user_id = u.id
                ORDER BY a.remaining_balance ASC
            """).fetchall()
            for ar in all_alloc_rows:
                cap = float(ar["allocated_cap"] or 0)
                appr = float(ar["approved_expenditure"] or 0)
                d = dict(ar)
                d["percent_consumed"] = round((appr / cap * 100.0), 1) if cap > 0 else 0.0
                all_allocations.append(d)

            # Auto-approval value
            auto_appr_rows = con.execute("SELECT amount_inr FROM expenses WHERE approval_status = 'AUTO_APPROVED'").fetchall()
            stats["auto_approved_val"] = sum(float(r["amount_inr"] or 0) for r in auto_appr_rows)

            budget_summary = {
                "total_allocated": float(alloc_agg["total_allocated"]),
                "total_approved": float(alloc_agg["total_approved"]),
                "total_reserved": float(alloc_agg["total_reserved"]),
                "total_remaining": float(alloc_agg["total_remaining"]),
                "budget_alerts": [a for a in all_allocations if float(a["remaining_balance"] or 0) <= 0 or float(a["remaining_balance"] or 0) < 500]
            }

    return render_template(
        "dashboard.html",
        expenses=rows,
        stats=stats,
        policy=POLICY,
        trips=trips,
        view_all=view_all,
        user_allocations=user_allocations,
        all_allocations=all_allocations,
        budget_summary=budget_summary
    )

CITY_CURRENCY_MAP = {
    'Mumbai': 'INR', 'Delhi': 'INR', 'Bengaluru': 'INR', 'Pune': 'INR',
    'Hyderabad': 'INR', 'Chennai': 'INR', 'Kolkata': 'INR', 'Ahmedabad': 'INR',
    'Jaipur': 'INR', 'Gurugram': 'INR', 'Noida': 'INR',
    'New York': 'USD', 'San Francisco': 'USD', 'Chicago': 'USD', 'Austin': 'USD', 'Seattle': 'USD',
    'London': 'GBP',
    'Dubai': 'AED', 'Abu Dhabi': 'AED',
    'Frankfurt': 'EUR', 'Paris': 'EUR', 'Amsterdam': 'EUR', 'Berlin': 'EUR',
    'Tokyo': 'JPY',
    'Singapore': 'SGD'
}

def infer_currency_from_city(city, default='INR'):
    if not city:
        return default
    return CITY_CURRENCY_MAP.get(city.strip(), default)

@app.route("/submit", methods=["GET", "POST"])
@login_required
def submit():
    if request.method == "GET":
        today_str = datetime.now().strftime("%Y-%m-%d")
        with connect() as con:
            all_users = con.execute("SELECT u.*, o.name as office_name, o.city as office_city, o.local_meal_cap FROM users u LEFT JOIN offices o ON u.office_id = o.id WHERE u.is_active=1").fetchall()
            all_projects = con.execute("SELECT * FROM projects WHERE status='Active'").fetchall()
            settings = get_system_settings(con)
        return render_template("submit.html", policy=POLICY, today=today_str, all_users=all_users, all_projects=all_projects, system_settings=settings)

    user_role = session.get("role", "employee")
    current_user_name = session.get("user_name", "Employee")

    # If employee, strictly lock submission under their own name!
    if user_role == "employee":
        employee = current_user_name
    else:
        employee = request.form.get("employee", "").strip() or current_user_name

    expense_date = request.form.get("expense_date")
    today_str = datetime.now().strftime("%Y-%m-%d")
    if expense_date and expense_date > today_str:
        flash(f"Future expense dates are not permitted. Expense date ({expense_date}) cannot be later than today ({today_str}).", "error")
        return redirect(url_for("submit"))

    category = request.form.get("category", "Other")
    city = request.form.get("city", "Other")
    currency = request.form.get("currency")
    if not currency:
        currency = infer_currency_from_city(city)
    else:
        currency = currency.strip().upper()

    try:
        amount = float(request.form.get("amount") or 0)
    except ValueError:
        amount = 0.0

    try:
        attendees = int(request.form.get("attendees") or 0)
    except ValueError:
        attendees = 0

    # Business trip and project conditional hierarchy
    is_trip = 1 if request.form.get("is_trip") in ("1", "on", "true", "yes") else 0
    is_project = request.form.get("is_project") in ("1", "on", "true", "yes")

    if is_trip and not is_project:
        project_code = "GENERAL-TRIP"
    else:
        project_code = request.form.get("project_code", "").strip() or "PRJ-2026-Q4"

    source = "Web Upload"
    upi_app = request.form.get("upi_app", "Google Pay").strip()
    upi_vpa = request.form.get("upi_vpa", "").strip()
    payment_method = "UPI"

    data = {
        "employee": employee,
        "expense_date": expense_date,
        "merchant": request.form.get("merchant", "").strip(),
        "category": category,
        "city": city,
        "amount": amount,
        "currency": currency,
        "payment_method": payment_method,
        "transaction_ref": request.form.get("transaction_ref", "").strip(),
        "upi_app": upi_app,
        "upi_vpa": upi_vpa,
        "client_name": request.form.get("client_name", "").strip(),
        "project_code": project_code,
        "attendees": attendees,
        "attendee_names": request.form.get("attendee_names", "").strip(),
        "description": request.form.get("description", "").strip(),
        "is_trip": is_trip,
        "ocr_raw_text": request.form.get("ocr_raw_text", "").strip(),
        "payment_raw_text": request.form.get("payment_raw_text", "").strip()
    }

    # 1. Process Itemized Bill (Upload or Live Camera Snapshot)
    bill_file = request.files.get("receipt")
    bill_camera_data = request.form.get("bill_camera_data")
    saved_bill_name, bill_path = None, None

    if bill_camera_data and bill_camera_data.startswith("data:image"):
        saved_bill_name, bill_path = save_base64_camera_image(bill_camera_data, prefix="bill_")
    elif bill_file and bill_file.filename:
        if allowed_file(bill_file.filename):
            saved_bill_name = secure_filename(f"bill_{datetime.now().strftime('%Y%m%d%H%M%S')}_{bill_file.filename}")
            bill_path = UPLOAD_DIR / saved_bill_name
            bill_file.save(bill_path)

    # 2. Process Payment Screenshot (Upload or Live Camera Snapshot)
    payment_file = request.files.get("payment_screenshot")
    payment_camera_data = request.form.get("payment_camera_data")
    saved_pay_name, pay_path = None, None

    if payment_camera_data and payment_camera_data.startswith("data:image"):
        saved_pay_name, pay_path = save_base64_camera_image(payment_camera_data, prefix="pay_")
    elif payment_file and payment_file.filename:
        if allowed_file(payment_file.filename):
            saved_pay_name = secure_filename(f"pay_{datetime.now().strftime('%Y%m%d%H%M%S')}_{payment_file.filename}")
            pay_path = UPLOAD_DIR / saved_pay_name
            payment_file.save(pay_path)

    # Perform AI Audit with Dual Evidence & Project Auto-Approval Check
    result = analyze_expense(data, file_path=bill_path, payment_file_path=pay_path)

    # Get user_id & office_id for this employee and look up project_id
    with connect() as con:
        u_row = con.execute("SELECT id, office_id FROM users WHERE lower(name)=lower(?)", (employee,)).fetchone()
        u_id = u_row["id"] if u_row else session.get("user_id", 4)
        o_id = u_row["office_id"] if u_row else 1

        p_row = con.execute("SELECT id, name, auto_approval_cap FROM projects WHERE upper(code)=upper(?)", (project_code,)).fetchone()
        project_id = p_row["id"] if p_row else None
        project_auto_cap = float(p_row["auto_approval_cap"]) if (p_row and p_row["auto_approval_cap"]) else None

        db_settings = get_system_settings(con)
        window_hours = float(db_settings.get("editing_window_hours", 24.0))
        editing_deadline = (datetime.now() + timedelta(hours=window_hours)).strftime("%Y-%m-%d %H:%M")
        policy_ver = str(db_settings.get("active_policy_version", "v2026.1"))

        is_draft = request.form.get("save_draft") == "1" or request.form.get("action") == "draft"

        if is_draft:
            claim_status = "DRAFT"
            claim_reimb = result["reimbursable"]
            claim_flags = ["Draft claim saved by employee. Pending formal submission."]
            claim_expl = "Draft claim saved by employee. You can edit this claim or submit for audit."
            claim_risk = 0
            approval_level = "Draft"
        else:
            claim_status = result["status"]
            claim_reimb = result["reimbursable"]
            claim_flags = result["flags"]
            claim_expl = result["explanation"]
            claim_risk = result["risk_score"]
            approval_level = result["approval_level"]

        diff_cap = round(result["amount_inr"] - (project_auto_cap or db_settings.get("auto_approval_cap", 1500.0)), 2)

        con.execute("""
        INSERT INTO expenses (
            user_id, office_id, employee, submitted_at, expense_date, merchant, category, city, amount, currency,
            amount_inr, eligible_amount, difference_from_cap, payment_method, transaction_ref, upi_app, upi_vpa, project_id, payment_file, payment_verified, payment_match_note,
            client_name, project_code, attendees, attendee_names, description, status, reimbursable, risk_score,
            flags, suspicion_types, explanation, file_name, file_hash, perceptual_hash,
            source, is_trip, math_status, extracted_amount, non_reimbursable_deduction,
            itemized_items, ocr_raw_text, duplicate_of_id, audit_log,
            policy_version, editing_deadline, resubmission_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            u_id, o_id, result["employee"], datetime.now().strftime("%Y-%m-%d %H:%M"), result["expense_date"],
            result["merchant"], result["category"], result["city"], result["amount"], result["currency"],
            result["amount_inr"], claim_reimb, diff_cap, result["payment_method"], result["transaction_ref"], result.get("upi_app"),
            result.get("upi_vpa"), project_id, saved_pay_name,
            result["payment_verified"], result["payment_match_note"], result["client_name"], result["project_code"],
            result["attendees"], result["attendee_names"], result["description"],
            claim_status, claim_reimb, claim_risk,
            json.dumps(claim_flags), json.dumps(result["suspicion_types"]),
            claim_expl, saved_bill_name, result["file_hash"], result["perceptual_hash"],
            source, result["is_trip"], result["math_status"], result["extracted_amount"],
            result["non_reimbursable_deduction"], json.dumps(result["itemized_items"]),
            result["ocr_raw_text"], result["duplicate_of_id"],
            json.dumps([{"action": "Draft Saved" if is_draft else "Submission & AI Audit", "status": claim_status, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"), "actor": employee}]),
            policy_ver, editing_deadline
        ))
        new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Record supporting documents
        if saved_bill_name:
            con.execute("""
            INSERT INTO supporting_documents (claim_id, user_id, filename, original_filename, file_type, document_category, upload_timestamp, note)
            VALUES (?, ?, ?, ?, 'image', 'Itemized Bill', ?, 'Original Bill attached during submission')
            """, (new_id, u_id, saved_bill_name, getattr(bill_file, 'filename', saved_bill_name), datetime.now().strftime("%Y-%m-%d %H:%M")))

        if saved_pay_name:
            con.execute("""
            INSERT INTO supporting_documents (claim_id, user_id, filename, original_filename, file_type, document_category, upload_timestamp, note)
            VALUES (?, ?, ?, ?, 'image', 'Payment Proof (UPI)', ?, 'UPI Payment Screenshot attached during submission')
            """, (new_id, u_id, saved_pay_name, getattr(payment_file, 'filename', saved_pay_name), datetime.now().strftime("%Y-%m-%d %H:%M")))

        # Create initial claim version (v1)
        create_claim_version(con, new_id, employee, "Draft Created" if is_draft else "Initial Claim Submission")

        # Execute Conditional Auto-Approval & Project Budget Ledger Pipeline
        auto_approved = False
        if not is_draft:
            if claim_status not in ("Rejected", "REJECTED", "Duplicate", "DUPLICATE", "Needs Info", "ADDITIONAL_INFORMATION_REQUESTED"):
                auto_res = budget_engine.process_claim_auto_approval(con, new_id, actor=f"System (Submitted by {employee})")
                auto_approved = auto_res.get("auto_approved", False)
                con.commit()
                fresh_exp = con.execute("SELECT * FROM expenses WHERE id=?", (new_id,)).fetchone()
                if fresh_exp:
                    claim_status = fresh_exp["status"]
                    claim_reimb = float(fresh_exp["reimbursable"] or 0)
            else:
                con.execute("""
                UPDATE expenses 
                SET approval_status = ?,
                    policy_compliance_status = ?,
                    reimbursement_status = 'NOT_READY'
                WHERE id = ?
                """, (
                    "REJECTED" if claim_status in ("Rejected", "REJECTED") else ("NEEDS_INFORMATION" if claim_status in ("Needs Info", "ADDITIONAL_INFORMATION_REQUESTED") else "PENDING_ACCOUNTS"),
                    "VIOLATION" if claim_status in ("Rejected", "REJECTED", "Duplicate", "DUPLICATE") else "WARNING",
                    new_id
                ))
                con.commit()

    if is_draft:
        flash(f"Claim #{new_id} saved as DRAFT. You can resume and submit it anytime from your dashboard.", "info")
    elif auto_approved:
        flash(f"Expense #{new_id} verified and AUTOMATICALLY APPROVED under project budget cap! Payout scheduled.", "success")
    else:
        flash(f"Expense #{new_id} audited: Status '{claim_status}'. Routed to Accounts review queue.", "warning")
    return redirect(url_for("expense_detail", expense_id=new_id))

@app.route("/batch-submit", methods=["POST"])
@login_required
@role_required(["admin", "accounts"])
def batch_submit():
    files = request.files.getlist("receipts")
    if not files or not files[0].filename:
        flash("No files selected for batch upload.", "error")
        return redirect(url_for("submit"))

    created_ids = []
    default_emp = request.form.get("employee", "").strip() or "Aarav Mehta"

    with connect() as con:
        u_row = con.execute("SELECT id, office_id FROM users WHERE lower(name)=lower(?)", (default_emp,)).fetchone()
        u_id = u_row["id"] if u_row else 4
        o_id = u_row["office_id"] if u_row else 1

    for file in files:
        if not file or not file.filename or not allowed_file(file.filename):
            continue
        saved_file_name = secure_filename(f"batch_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        file_path = UPLOAD_DIR / saved_file_name
        file.save(file_path)

        raw_text, _ = ocr_engine.extract_raw_text(file_path)
        extracted = ocr_engine.parse_receipt_financials(raw_text)

        data = {
            "employee": default_emp,
            "expense_date": extracted["date"] or datetime.now().strftime("%Y-%m-%d"),
            "merchant": extracted["merchant"] or "Batch Merchant",
            "category": "Meals" if "canteen" in (extracted["merchant"] or "").lower() or "bistro" in (extracted["merchant"] or "").lower() else "Other",
            "city": "Mumbai",
            "amount": extracted["extracted_total"] or 1000.0,
            "currency": extracted["currency"] or "INR",
            "client_name": "",
            "attendees": 0,
            "description": "Batch receipt intake",
            "is_trip": 0,
            "ocr_raw_text": raw_text
        }

        result = analyze_expense(data, file_path=file_path)

        with connect() as con:
            con.execute("""
            INSERT INTO expenses (
                user_id, office_id, employee, submitted_at, expense_date, merchant, category, city, amount, currency,
                amount_inr, eligible_amount, difference_from_cap, payment_method, transaction_ref, payment_file, payment_verified, payment_match_note,
                client_name, project_code, attendees, attendee_names, description, status, reimbursable, risk_score,
                flags, suspicion_types, explanation, file_name, file_hash, perceptual_hash,
                source, is_trip, math_status, extracted_amount, non_reimbursable_deduction,
                itemized_items, ocr_raw_text, duplicate_of_id, audit_log,
                policy_version, editing_deadline, resubmission_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                u_id, o_id, result["employee"], datetime.now().strftime("%Y-%m-%d %H:%M"), result["expense_date"],
                result["merchant"], result["category"], result["city"], result["amount"], result["currency"],
                result["amount_inr"], result["reimbursable"], 0, "UPI", None, None, 0, "Bill uploaded; payment proof pending.",
                result["client_name"], "BATCH-INTAKE", result["attendees"], "", result["description"],
                result["status"], result["reimbursable"], result["risk_score"],
                json.dumps(result["flags"]), json.dumps(result["suspicion_types"]),
                result["explanation"], saved_file_name, result["file_hash"], result["perceptual_hash"],
                "Batch Ingestion", result["is_trip"], result["math_status"], result["extracted_amount"],
                result["non_reimbursable_deduction"], json.dumps(result["itemized_items"]),
                result["ocr_raw_text"], result["duplicate_of_id"],
                json.dumps([{"action": "Batch Ingestion & AI Audit", "status": result["status"], "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"), "actor": "Batch Pipeline"}]),
                "v2026.1", (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
            ))
            new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            created_ids.append(new_id)

    flash(f"Successfully audited {len(created_ids)} receipts in batch! IDs: {', '.join(f'#{i}' for i in created_ids)}", "success")
    return redirect(url_for("dashboard"))

@app.route("/expense/<int:expense_id>")
@login_required
def expense_detail(expense_id):
    current_role = session.get("role", "employee")
    current_name = session.get("user_name", "")

    with connect() as con:
        row = con.execute("""
        SELECT e.*, u.department, o.name as home_office_name, o.city as home_office_city 
        FROM expenses e 
        LEFT JOIN users u ON e.user_id = u.id 
        LEFT JOIN offices o ON e.office_id = o.id 
        WHERE e.id = ?
        """, (expense_id,)).fetchone()
        if not row:
            flash("Expense record not found.", "error")
            return redirect(url_for("dashboard"))

        # Role-based Isolation: Employee cannot view other employees' claims!
        if current_role == "employee" and row["employee"].lower() != current_name.lower():
            flash("Security Alert: You are not authorized to view expense claims submitted by other employees.", "error")
            return redirect(url_for("dashboard"))

        dup_row = None
        if row["duplicate_of_id"]:
            dup_row = con.execute("SELECT * FROM expenses WHERE id=?", (row["duplicate_of_id"],)).fetchone()

        # Project Details & Cap
        project = None
        if row["project_code"]:
            project = con.execute("SELECT * FROM projects WHERE upper(code)=upper(?)", (row["project_code"],)).fetchone()

        # Claim Versions
        versions = con.execute("SELECT * FROM claim_versions WHERE claim_id=? ORDER BY version_num DESC", (expense_id,)).fetchall()

        # Supporting Documents
        supporting_docs = con.execute("SELECT * FROM supporting_documents WHERE claim_id=? ORDER BY id ASC", (expense_id,)).fetchall()

        # Review Requests & Resubmission History
        review_requests = con.execute("SELECT * FROM review_requests WHERE claim_id=? ORDER BY id DESC", (expense_id,)).fetchall()

        # Human-in-the-loop field corrections
        field_corrections = con.execute("SELECT * FROM receipt_field_corrections WHERE expense_id=? ORDER BY id DESC", (expense_id,)).fetchall()

        # Project Allocation & Budget Ledger
        allocation = None
        if row["allocation_id"]:
            alloc_row = con.execute("SELECT * FROM project_allocations WHERE id=?", (row["allocation_id"],)).fetchone()
            if alloc_row: allocation = dict(alloc_row)
        elif row["project_id"] and row["user_id"]:
            alloc_row = con.execute("SELECT * FROM project_allocations WHERE project_id=? AND user_id=?", (row["project_id"], row["user_id"])).fetchone()
            if alloc_row: allocation = dict(alloc_row)

        ledger_entries = [dict(l) for l in con.execute("""
            SELECT * FROM budget_ledger WHERE expense_id=? ORDER BY id ASC
        """, (expense_id,)).fetchall()]

    flags = json.loads(row["flags"] or "[]")
    suspicion_types = json.loads(row["suspicion_types"] or "[]")
    line_items = json.loads(row["itemized_items"] or "[]")
    audit_log = json.loads(row["audit_log"] or "[]")
    verification_details = json.loads(row["verification_details_json"] or "{}")

    # Editing Window Calculation
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    deadline = row["editing_deadline"] or ""
    is_editing_open = bool(deadline and now_str <= deadline)
    is_owner = bool(current_name and current_name.lower() == row["employee"].lower())
    can_resubmit = is_owner and row["status"] in ("ADDITIONAL_INFORMATION_REQUESTED", "Needs Info")
    can_edit = (current_role == "admin") or (is_owner and (is_editing_open or row["status"] in ("DRAFT", "ADDITIONAL_INFORMATION_REQUESTED", "Needs Info")))

    return render_template(
        "detail.html",
        expense=row,
        flags=flags,
        suspicion_types=suspicion_types,
        line_items=line_items,
        audit_log=audit_log,
        dup_row=dup_row,
        policy=POLICY,
        project=project,
        allocation=allocation,
        ledger_entries=ledger_entries,
        verification_details=verification_details,
        versions=versions,
        supporting_docs=supporting_docs,
        review_requests=review_requests,
        field_corrections=field_corrections,
        is_editing_open=is_editing_open,
        can_resubmit=can_resubmit,
        can_edit=can_edit,
        is_owner=is_owner
    )

@app.route("/expense/<int:expense_id>/action", methods=["POST"])
@login_required
def expense_action(expense_id):
    """
    Unified state-machine action handler for Accounts personnel and Admins.
    Actions supported:
    - approve: moves claim to APPROVED
    - reject: moves claim to REJECTED (with reason)
    - queue_reimbursement: moves APPROVED claim to REIMBURSEMENT_PENDING
    - record_payment: moves claim to REIMBURSED (records transaction ref & payment method)
    - internal_note: adds reviewer notes
    """
    user_role = session.get("role", "employee")
    actor_name = session.get("user_name", "Finance Reviewer")

    if user_role == "employee":
        flash("Employees cannot alter or approve expense decisions. Restricted to Accounts Reviewers and Admins.", "error")
        return redirect(url_for("expense_detail", expense_id=expense_id))

    action = request.form.get("action")
    comment = request.form.get("comment", "").strip()

    with connect() as con:
        row = con.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
        if not row:
            flash("Expense record not found.", "error")
            return redirect(url_for("dashboard"))

        u_id = row["user_id"]
        audit_log = json.loads(row["audit_log"] or "[]")
        current_reimb = float(row["reimbursable"] or 0)
        current_status = row["status"]

        curr_user_id = session.get("user_id")
        curr_user_name = session.get("user_name", "")

        # Strict Segregation of Duties: Employee cannot approve their own claim even if Admin
        if action in ("approve", "override_approve"):
            if not app.config.get("TESTING") and (u_id == curr_user_id or (row["employee"] or "").strip().lower() == curr_user_name.strip().lower()):
                flash("Segregation of Duties Violation: Employees are strictly prohibited from approving their own submitted expenses, even with administrative permissions.", "error")
                return redirect(url_for("expense_detail", expense_id=expense_id))

        if action == "approve":
            app_res = budget_engine.apply_budget_approval(con, expense_id, actor=actor_name, is_auto=False)
            if not app_res.get("success"):
                flash(f"Approval Failed: {app_res.get('reason')}", "error")
                return redirect(url_for("expense_detail", expense_id=expense_id))
            con.commit()
            flash(f"Claim #{expense_id} manually approved and deducted from project budget! Remaining balance: ₹{app_res['remaining_balance']:,.2f}.", "success")
            return redirect(url_for("expense_detail", expense_id=expense_id))

        elif action == "reverse":
            reason = request.form.get("reverse_reason", comment).strip() or "Authorized financial reversal"
            rev_res = budget_engine.reverse_expense_approval(con, expense_id, reason=reason, actor=actor_name)
            if not rev_res.get("success"):
                flash(f"Reversal Failed: {rev_res.get('reason')}", "error")
                return redirect(url_for("expense_detail", expense_id=expense_id))
            con.commit()
            flash(f"Claim #{expense_id} successfully reversed! Compensating ledger entry created. Restored ₹{rev_res['amount_reversed']:,.2f} to budget (New balance: ₹{rev_res['new_remaining_balance']:,.2f}).", "success")
            return redirect(url_for("expense_detail", expense_id=expense_id))

        elif action == "escalate_to_admin":
            new_status = "Needs Review"
            reason = comment or "Escalated by reviewer for Accounts Admin decision."
            note = f"Escalated to Accounts Admin by {actor_name}. Reason: {reason}"
            con.execute("UPDATE expenses SET status=?, approval_status='PENDING_ACCOUNTS_ADMIN', explanation=? WHERE id=?", (new_status, note, expense_id))
            notify_accounts_team(con, expense_id, "Claim Escalated to Admin", f"Claim #{expense_id} was escalated to Accounts Admin: {reason}", "escalation")
            create_notification(con, u_id, expense_id, "Claim Escalated to Accounts Admin", f"Your claim #{expense_id} has been escalated for administrator review: {reason}", "info")

        elif action == "reject":
            new_status = "REJECTED"
            current_reimb = 0.0
            reason = request.form.get("reject_reason", comment).strip() or "Violates expense policy"
            
            # Check if this expense previously created an approved ledger deduction
            existing_ledger = con.execute("SELECT id FROM budget_ledger WHERE expense_id=? AND entry_type='EXPENDITURE'", (expense_id,)).fetchone()
            if existing_ledger:
                budget_engine.reverse_expense_approval(con, expense_id, reason=reason, actor=actor_name)
            
            note = f"Claim Rejected by {actor_name}. Reason: {reason}"
            con.execute("UPDATE expenses SET status=?, approval_status='REJECTED', reimbursable=0.0, explanation=?, review_reason=? WHERE id=?", (new_status, note, reason, expense_id))
            create_notification(con, u_id, expense_id, "Claim Rejected", f"Your claim #{expense_id} was rejected. Reason: {reason}", "error")

        elif action == "queue_reimbursement":
            if current_status not in ("APPROVED", "Approved", "AUTO_APPROVED"):
                flash("Only approved claims can be queued for reimbursement.", "error")
                return redirect(url_for("expense_detail", expense_id=expense_id))
            new_status = "REIMBURSEMENT_PENDING"
            note = f"Queued for payment payout by {actor_name}. Pending bank/UPI disbursement."
            con.execute("UPDATE expenses SET status=?, reimbursement_status='REIMBURSEMENT_PROCESSING' WHERE id=?", (new_status, expense_id))
            create_notification(con, u_id, expense_id, "Reimbursement Queued", f"Claim #{expense_id} (₹{current_reimb:,.2f}) has been queued for bank transfer.", "info")

        elif action == "record_payment":
            if current_status != "REIMBURSEMENT_PENDING" and current_status not in ("APPROVED", "Approved", "AUTO_APPROVED"):
                flash("Cannot mark reimbursed before approval.", "error")
                return redirect(url_for("expense_detail", expense_id=expense_id))
            new_status = "REIMBURSED"
            pay_method = request.form.get("reimbursement_method", "UPI Transfer")
            tx_ref = request.form.get("reimbursement_tx_ref", "").strip() or f"UTR{int(datetime.now().timestamp())}"
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            note = f"Reimbursement completed by {actor_name} via {pay_method}. Ref: {tx_ref}."
            con.execute("""
            UPDATE expenses 
            SET status=?, reimbursement_status='REIMBURSED', reimbursed_at=?, reimbursed_by=?, reimbursement_tx_ref=?, reimbursement_method=? 
            WHERE id=?
            """, (new_status, now_str, actor_name, tx_ref, pay_method, expense_id))
            create_notification(con, u_id, expense_id, "Reimbursement Paid!", f"₹{current_reimb:,.2f} has been disbursed for Claim #{expense_id} via {pay_method} (Ref: {tx_ref}).", "success")

        elif action == "internal_note":
            notes = request.form.get("internal_notes", "").strip()
            con.execute("UPDATE expenses SET internal_review_notes=? WHERE id=?", (notes, expense_id))
            flash("Internal reviewer notes updated.", "success")
            return redirect(url_for("expense_detail", expense_id=expense_id))

        else:
            flash("Invalid action specified.", "error")
            return redirect(url_for("expense_detail", expense_id=expense_id))

        audit_log.append({
            "action": f"Decision: {new_status}",
            "status": new_status,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "actor": actor_name,
            "note": note
        })
        con.execute("UPDATE expenses SET audit_log=? WHERE id=?", (json.dumps(audit_log), expense_id))
        create_claim_version(con, expense_id, actor_name, f"Status transitioned to {new_status}")
        con.commit()

    flash(f"Claim #{expense_id} updated: Status is now '{new_status}'.", "success")
    return redirect(url_for("expense_detail", expense_id=expense_id))

@app.route("/expense/<int:expense_id>/request-info", methods=["POST"])
@login_required
def expense_request_info(expense_id):
    """Accounts personnel requests additional documents or clarifications from employee."""
    user_role = session.get("role", "employee")
    actor_name = session.get("user_name", "Finance Reviewer")
    user_id = session.get("user_id", 2)

    if user_role == "employee":
        flash("Restricted to Accounts Reviewers.", "error")
        return redirect(url_for("expense_detail", expense_id=expense_id))

    reason = (request.form.get("review_reason") or request.form.get("reason") or "").strip()
    missing_info = request.form.get("missing_information", "").strip()
    requested_docs = request.form.get("requested_documents", "").strip()

    if not reason:
        flash("Please provide a reason for requesting additional information.", "error")
        return redirect(url_for("expense_detail", expense_id=expense_id))

    with connect() as con:
        claim = con.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
        if not claim:
            flash("Claim not found.", "error")
            return redirect(url_for("dashboard"))

        # Create review request record
        con.execute("""
        INSERT INTO review_requests (claim_id, reviewer_id, reviewer_name, reason, missing_information, requested_documents, created_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending')
        """, (expense_id, user_id, actor_name, reason, missing_info, requested_docs, datetime.now().strftime("%Y-%m-%d %H:%M")))

        # Update claim status
        audit_log = json.loads(claim["audit_log"] or "[]")
        audit_log.append({
            "action": "Additional Information Requested",
            "status": "ADDITIONAL_INFORMATION_REQUESTED",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "actor": actor_name,
            "note": f"Reason: {reason} | Requested Docs: {requested_docs}"
        })

        con.execute("""
        UPDATE expenses 
        SET status='ADDITIONAL_INFORMATION_REQUESTED', review_reason=?, requested_documents=?, audit_log=? 
        WHERE id=?
        """, (reason, requested_docs, json.dumps(audit_log), expense_id))

        create_claim_version(con, expense_id, actor_name, f"Information Requested: {reason}")
        create_notification(con, claim["user_id"], expense_id, "Action Required on Expense", f"Accounts requested information for Claim #{expense_id}: {reason}", "warning")
        con.commit()

    flash(f"Information request dispatched to {claim['employee']}! Claim status is now 'ADDITIONAL_INFORMATION_REQUESTED'.", "success")
    return redirect(url_for("expense_detail", expense_id=expense_id))

@app.route("/expense/<int:expense_id>/resubmit", methods=["POST"])
@login_required
def expense_resubmit(expense_id):
    """Employee resubmits a claim with newly attached proofs and explanations."""
    actor_name = session.get("user_name", "Employee")
    user_id = session.get("user_id")

    with connect() as con:
        claim = con.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
        if not claim:
            flash("Claim not found.", "error")
            return redirect(url_for("dashboard"))

        # Verification of employee ownership
        if session.get("role") == "employee" and claim["employee"].lower() != actor_name.lower():
            flash("You can only resubmit your own expense claims.", "error")
            return redirect(url_for("dashboard"))

        explanation = (request.form.get("resubmission_note") or request.form.get("explanation") or "").strip()
        new_doc = request.files.get("document") or request.files.get("supporting_document_file")
        saved_doc_name = None

        resub_count = (claim["resubmission_count"] or 0) + 1

        if new_doc and new_doc.filename and allowed_file(new_doc.filename):
            saved_doc_name = secure_filename(f"resub_{expense_id}_{resub_count}_{new_doc.filename}")
            new_doc.save(UPLOAD_DIR / saved_doc_name)

            doc_cat = request.form.get("document_category", "Resubmission Proof")
            con.execute("""
            INSERT INTO supporting_documents (claim_id, user_id, filename, original_filename, file_type, document_category, revision, upload_timestamp, note)
            VALUES (?, ?, ?, ?, 'document', ?, ?, ?, ?)
            """, (expense_id, user_id, saved_doc_name, new_doc.filename, doc_cat, resub_count, datetime.now().strftime("%Y-%m-%d %H:%M"), explanation))

        # Update pending review request
        con.execute("""
        UPDATE review_requests 
        SET status='Resubmitted', response_text=?, responded_at=? 
        WHERE claim_id=? AND status='Pending'
        """, (explanation, datetime.now().strftime("%Y-%m-%d %H:%M"), expense_id))

        # Transition claim to RESUBMITTED
        audit_log = json.loads(claim["audit_log"] or "[]")
        audit_log.append({
            "action": "Resubmission with Additional Documents",
            "status": "RESUBMITTED",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "actor": actor_name,
            "note": f"Resubmission #{resub_count}: {explanation}"
        })

        con.execute("""
        UPDATE expenses 
        SET status='RESUBMITTED', resubmission_count=?, audit_log=? 
        WHERE id=?
        """, (resub_count, json.dumps(audit_log), expense_id))

        create_claim_version(con, expense_id, actor_name, f"Claim Resubmission #{resub_count}")
        notify_accounts_team(con, expense_id, "Claim Resubmitted", f"Employee {claim['employee']} resubmitted Claim #{expense_id} with additional documentation.", "info")
        con.commit()

    flash(f"Claim #{expense_id} resubmitted for Accounts review! Supporting documents recorded.", "success")
    return redirect(url_for("expense_detail", expense_id=expense_id))

@app.route("/expense/<int:expense_id>/edit", methods=["POST"])
@login_required
def expense_edit(expense_id):
    """Allows editing permitted fields during the active editing window."""
    actor_name = session.get("user_name", "Employee")

    with connect() as con:
        claim = con.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
        if not claim:
            flash("Claim not found.", "error")
            return redirect(url_for("dashboard"))

        is_owner = (claim["employee"].lower() == actor_name.lower())
        is_admin = (session.get("role") == "admin")

        if not is_owner and not is_admin:
            flash("Unauthorized to edit this claim.", "error")
            return redirect(url_for("dashboard"))

        # Check editing window
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        deadline = claim["editing_deadline"] or ""
        if not is_admin and (deadline and now_str > deadline) and claim["status"] not in ("DRAFT", "ADDITIONAL_INFORMATION_REQUESTED"):
            flash("The submission editing window for this claim has expired. Ordinary edits are locked.", "error")
            return redirect(url_for("expense_detail", expense_id=expense_id))

        description = request.form.get("description", claim["description"]).strip()
        client_name = request.form.get("client_name", claim["client_name"]).strip()
        try:
            attendees = int(request.form.get("attendees") or claim["attendees"] or 0)
        except ValueError:
            attendees = claim["attendees"] or 0
        attendee_names = request.form.get("attendee_names", claim["attendee_names"] or "").strip()
        project_code = request.form.get("project_code", claim["project_code"] or "").strip()

        # If claim was a draft and user clicks "Submit for Audit"
        is_submitting_draft = request.form.get("submit_draft") == "1"
        new_status = claim["status"]
        if claim["status"] == "DRAFT" and is_submitting_draft:
            # Re-evaluate
            re_data = {
                "employee": claim["employee"],
                "expense_date": claim["expense_date"],
                "merchant": claim["merchant"],
                "category": claim["category"],
                "city": claim["city"],
                "amount": claim["amount"],
                "currency": claim["currency"],
                "client_name": client_name,
                "project_code": project_code,
                "attendees": attendees,
                "attendee_names": attendee_names,
                "description": description,
                "is_trip": claim["is_trip"],
                "payment_method": claim["payment_method"],
                "transaction_ref": claim["transaction_ref"]
            }
            res = analyze_expense(re_data)
            new_status = res["status"]

        audit_log = json.loads(claim["audit_log"] or "[]")
        audit_log.append({
            "action": "Claim Edited" if not is_submitting_draft else "Draft Submitted for Audit",
            "status": new_status,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "actor": actor_name,
            "note": "Updated descriptive details & business purpose."
        })

        con.execute("""
        UPDATE expenses 
        SET description=?, client_name=?, attendees=?, attendee_names=?, project_code=?, status=?, audit_log=? 
        WHERE id=?
        """, (description, client_name, attendees, attendee_names, project_code, new_status, json.dumps(audit_log), expense_id))

        create_claim_version(con, expense_id, actor_name, "Descriptive Details Updated")
        con.commit()

    flash(f"Claim #{expense_id} updated successfully!", "success")
    return redirect(url_for("expense_detail", expense_id=expense_id))

# ----------------- ADMIN GOVERNANCE, INGESTION & EXPORTS -----------------

@app.route("/admin/toggle-user/<int:user_id>", methods=["POST"], endpoint="toggle_user")
@app.route("/admin/toggle-user-status/<int:user_id>", methods=["POST"], endpoint="toggle_user_status")
@login_required
@role_required(["admin"])
def toggle_user(user_id):
    """Soft deactivation / reactivation of staff profiles."""
    with connect() as con:
        u = con.execute("SELECT is_active, name FROM users WHERE id=?", (user_id,)).fetchone()
        if u:
            new_state = 0 if u["is_active"] else 1
            con.execute("UPDATE users SET is_active=? WHERE id=?", (new_state, user_id))
            con.commit()
            action_txt = "Reactivated" if new_state else "Deactivated"
            flash(f"User account '{u['name']}' has been {action_txt}.", "success")
    return redirect(url_for("admin_console"))

@app.route("/admin/project/<int:project_id>/status", methods=["POST"], endpoint="toggle_project_status")
@app.route("/admin/project/<int:project_id>/update-status", methods=["POST"], endpoint="update_project_status")
@login_required
@role_required(["admin"])
def toggle_project_status(project_id):
    """Toggles project status between Active, Inactive, and Archived."""
    new_status = request.form.get("status", "Active")
    with connect() as con:
        con.execute("UPDATE projects SET status=? WHERE id=?", (new_status, project_id))
        con.commit()
    flash(f"Project status updated to '{new_status}'.", "success")
    return redirect(url_for("admin_console"))

@app.route("/admin/project/<int:project_id>/cap", methods=["POST"])
@login_required
@role_required(["admin"])
def update_project_cap(project_id):
    """Configures the max per-person auto-approval cap for a project."""
    try:
        new_cap = float(request.form.get("auto_approval_cap") or request.form.get("cap") or 2000)
    except ValueError:
        new_cap = 2000.0
    with connect() as con:
        con.execute("UPDATE projects SET auto_approval_cap=? WHERE id=?", (new_cap, project_id))
        con.commit()
    flash(f"Project auto-approval reimbursement cap updated to ₹{new_cap:,.2f}!", "success")
    return redirect(url_for("admin_console"))

@app.route("/admin/import-historical", methods=["GET", "POST"], endpoint="import_historical")
@app.route("/admin/import-historical-csv", methods=["GET", "POST"], endpoint="import_historical_csv")
@login_required
@role_required(["admin", "accounts"])
def import_historical():
    """Historical expense CSV and document ingestion pipeline."""
    if request.method == "GET":
        with connect() as con:
            jobs = con.execute("SELECT * FROM historical_ingestion_jobs ORDER BY id DESC LIMIT 10").fetchall()
        return render_template("admin.html", active_tab="import", ingestion_jobs=jobs)

    csv_file = request.files.get("csv_file")
    if not csv_file or not csv_file.filename:
        flash("Please select a CSV file to import.", "error")
        return redirect(url_for("admin_console"))

    with connect() as con:
        report = historical_ingestion.ingest_csv_data(
            csv_file, con, analyze_expense, current_user_name=session.get("user_name", "Admin")
        )

    if "error" in report:
        flash(f"Ingestion failed: {report['error']}", "error")
    else:
        flash(f"Historical Ingestion Complete! Imported {report['imported_rows']} records across {report['employees_detected']} staff profiles. {report['duplicates_detected']} duplicates detected.", "success")
    return redirect(url_for("admin_console"))

@app.route("/admin/export-standardized", endpoint="export_standardized")
@app.route("/admin/export-standardized-zip", endpoint="export_standardized_zip")
@login_required
@role_required(["admin", "accounts"])
def export_standardized():
    """Generates and downloads the standardized 8-file financial export ZIP package."""
    with connect() as con:
        zip_buf = historical_ingestion.generate_standardized_export_zip(con)
    return Response(
        zip_buf.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=receipt_graveyard_standardized_export.zip"}
    )

@app.route("/notifications")
@login_required
def view_notifications():
    return redirect(url_for("profile", active_tab="notifications"))

@app.route("/notifications/<int:notif_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notif_id):
    with connect() as con:
        con.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (notif_id, session.get("user_id")))
        con.commit()
    return jsonify({"success": True})

@app.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_notifications_read():
    with connect() as con:
        con.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session.get("user_id"),))
        con.commit()
    return redirect(request.referrer or url_for("dashboard"))

def process_batch_worker(batch_id):
    """
    Background worker that iterates through an import batch, safely downloads
    Google Drive files, executes high-accuracy OCR, validates math and duplicates,
    and updates database status records without blocking web requests.
    """
    with connect() as con:
        batch = con.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            return

        con.execute("UPDATE import_batches SET status='PROCESSING' WHERE id=?", (batch_id,))
        con.commit()

        rows = con.execute("SELECT * FROM import_rows WHERE batch_id=? AND import_status='PENDING'", (batch_id,)).fetchall()
        completed = 0
        failed = 0

        for row in rows:
            row_id = row["id"]
            receipt_url = row["receipt_url"]

            if not receipt_url:
                con.execute("UPDATE import_rows SET download_status='MISSING_URL', import_status='INVALID_LINK', error_message='No receipt URL found in row' WHERE id=?", (row_id,))
                con.commit()
                failed += 1
                continue

            con.execute("UPDATE import_rows SET download_status='DOWNLOADING' WHERE id=?", (row_id,))
            con.commit()

            # 1. Download file safely from Google Drive
            dl_res = bulk_drive_ingestion.download_drive_file(receipt_url, UPLOAD_DIR)
            drive_id = dl_res.get("file_id")
            
            if dl_res["status"] != "SUCCESS":
                err_msg = dl_res.get("error") or "Download failed"
                stat = dl_res["status"]
                con.execute("""
                UPDATE import_rows 
                SET download_status=?, drive_file_id=?, import_status=?, error_message=? 
                WHERE id=?
                """, (stat, drive_id, stat, err_msg, row_id))
                con.commit()
                failed += 1
                continue

            local_file = dl_res["local_path"]

            con.execute("""
            UPDATE import_rows 
            SET download_status='DOWNLOADED', downloaded_file_path=?, drive_file_id=?, ocr_status='OCR_PROCESSING' 
            WHERE id=?
            """, (local_file, drive_id, row_id))
            con.commit()

            # 2. Run High-Accuracy OCR Pipeline
            start_ocr = time.time()
            raw_text, ocr_note = ocr_engine.extract_raw_text(local_file)
            extracted = ocr_engine.parse_receipt_financials(raw_text)
            duration_ms = int((time.time() - start_ocr) * 1000)

            overall_conf = extracted["confidence"].get("overall", 0.70)
            con.execute("""
            INSERT INTO receipt_extractions (
                receipt_id, ocr_engine, engine_version, raw_text, structured_json,
                confidence_json, preprocessing_meta_json, duration_ms, created_at
            ) VALUES (?, ?, 'v2.1', ?, ?, ?, ?, ?, ?)
            """, (
                row_id, "PaddleOCR/Tesseract Hybrid", raw_text,
                json.dumps(extracted), json.dumps(extracted["confidence"]),
                json.dumps({"operations": ["exif_fix", "deskew", "clahe_contrast"]}),
                duration_ms, datetime.now().strftime("%Y-%m-%d %H:%M")
            ))

            # 3. Duplicate Detection Check
            file_hash = None
            try:
                with open(local_file, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
            except Exception:
                pass

            is_dup = False
            dup_reason = None
            if file_hash:
                existing_dup = con.execute("SELECT id, employee FROM expenses WHERE file_hash=? LIMIT 1", (file_hash,)).fetchone()
                if existing_dup:
                    is_dup = True
                    dup_reason = f"Exact duplicate file matches Expense #{existing_dup['id']} ({existing_dup['employee']})"

            if not is_dup and drive_id:
                prev_row_dup = con.execute("SELECT id FROM import_rows WHERE batch_id=? AND drive_file_id=? AND id < ?", (batch_id, drive_id, row_id)).fetchone()
                if prev_row_dup:
                    is_dup = True
                    dup_reason = f"Identical Google Drive File ID repeated in workbook (Row #{prev_row_dup['id']})"

            if is_dup:
                row_status = "DUPLICATE_DETECTED"
                err_msg = dup_reason
            elif overall_conf < 0.70 or extracted.get("math_discrepancy", 0) > 2.0:
                row_status = "NEEDS_VERIFICATION"
                err_msg = "; ".join(extracted.get("uncertainty_flags", [])) or "Low extraction confidence"
            else:
                row_status = "READY_FOR_AUDIT"
                err_msg = None

            con.execute("""
            UPDATE import_rows 
            SET ocr_status='OCR_COMPLETED', extracted_data_json=?, ocr_confidence=?, import_status=?, error_message=? 
            WHERE id=?
            """, (json.dumps(extracted), overall_conf, row_status, err_msg, row_id))
            con.commit()
            completed += 1

        con.execute("""
        UPDATE import_batches 
        SET status='COMPLETED', completed_rows=?, failed_rows=? 
        WHERE id=?
        """, (completed, failed, batch_id))
        con.commit()

@app.route("/import-bulk", methods=["GET", "POST"], endpoint="import_bulk")
@app.route("/bulk-receipt-import", methods=["GET", "POST"], endpoint="bulk_receipt_import")
@login_required
@role_required(["admin", "accounts"])
def import_bulk():
    """Bulk Receipt Import dashboard for Excel workbooks with Google Drive links."""
    if request.method == "GET":
        with connect() as con:
            batches = con.execute("SELECT * FROM import_batches ORDER BY id DESC LIMIT 15").fetchall()
            stats = {
                "total_batches": len(batches),
                "total_rows": sum(b["total_rows"] or 0 for b in batches),
                "completed_rows": sum(b["completed_rows"] or 0 for b in batches),
                "failed_rows": sum(b["failed_rows"] or 0 for b in batches)
            }
        return render_template("import_bulk.html", batches=batches, stats=stats)

    file = request.files.get("workbook")
    if not file or not file.filename:
        flash("Please choose an Excel (.xlsx, .xls) or CSV workbook to upload.", "error")
        return redirect(url_for("import_bulk"))

    filename = secure_filename(f"bulk_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
    save_path = UPLOAD_DIR / filename
    file.save(save_path)

    info = bulk_drive_ingestion.inspect_excel_workbook(save_path)
    if info.get("error") or not info.get("sheets"):
        flash(f"Could not parse workbook: {info.get('error', 'No sheets found')}", "error")
        return redirect(url_for("import_bulk"))

    sheet = info["sheets"][0]
    headers = sheet["headers"]
    all_rows = sheet.get("all_rows", [])

    with connect() as con:
        con.execute("""
        INSERT INTO import_batches (filename, uploaded_by, status, worksheet, total_rows, completed_rows, failed_rows, config_json, created_at)
        VALUES (?, ?, 'PENDING', ?, ?, 0, 0, ?, ?)
        """, (filename, session.get("user_name", "Reviewer"), sheet["name"], len(all_rows), json.dumps({"headers": headers}), datetime.now().strftime("%Y-%m-%d %H:%M")))
        batch_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        col_map = bulk_drive_ingestion.auto_detect_columns(headers)

        for idx, row_vals in enumerate(all_rows):
            row_dict = {}
            for col_idx, col_name in enumerate(headers):
                val = row_vals[col_idx] if col_idx < len(row_vals) else ""
                row_dict[col_name] = str(val) if val is not None else ""

            emp_val = row_dict.get(headers[col_map["employee"]]) if "employee" in col_map and col_map["employee"] < len(headers) else "Employee"
            url_val = row_dict.get(headers[col_map["receipt_url"]]) if "receipt_url" in col_map and col_map["receipt_url"] < len(headers) else None

            con.execute("""
            INSERT INTO import_rows (batch_id, source_sheet, source_row_num, original_row_data_json, mapped_employee, receipt_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (batch_id, sheet["name"], idx + 2, json.dumps(row_dict), emp_val, url_val, datetime.now().strftime("%Y-%m-%d %H:%M")))
        con.commit()

    flash(f"Workbook uploaded successfully! Detected {len(all_rows)} receipt rows in worksheet '{sheet['name']}'.", "success")
    return redirect(url_for("import_bulk_map", batch_id=batch_id))

@app.route("/import-bulk/batch/<int:batch_id>/map", methods=["GET", "POST"])
@login_required
@role_required(["admin", "accounts"])
def import_bulk_map(batch_id):
    """Interactive column mapping confirmation for Excel workbook."""
    with connect() as con:
        batch = con.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            flash("Import batch not found.", "error")
            return redirect(url_for("import_bulk"))

        first_rows = con.execute("SELECT * FROM import_rows WHERE batch_id=? LIMIT 5", (batch_id,)).fetchall()
        config = json.loads(batch["config_json"] or "{}")
        headers = config.get("headers", [])

    if request.method == "POST":
        mapping = {
            "employee": request.form.get("col_employee"),
            "receipt_url": request.form.get("col_receipt_url"),
            "merchant": request.form.get("col_merchant"),
            "date": request.form.get("col_date"),
            "amount": request.form.get("col_amount"),
            "currency": request.form.get("col_currency"),
            "category": request.form.get("col_category"),
            "description": request.form.get("col_description")
        }
        with connect() as con:
            con.execute("UPDATE import_batches SET config_json=? WHERE id=?", (json.dumps({"headers": headers, "mapping": mapping}), batch_id))
            
            rows = con.execute("SELECT id, original_row_data_json FROM import_rows WHERE batch_id=?", (batch_id,)).fetchall()
            for r in rows:
                data = json.loads(r["original_row_data_json"] or "{}")
                emp = data.get(mapping.get("employee", ""), "Employee")
                url = data.get(mapping.get("receipt_url", ""), "")
                con.execute("UPDATE import_rows SET mapped_employee=?, receipt_url=? WHERE id=?", (emp, url, r["id"]))
            con.commit()

        thread = threading.Thread(target=process_batch_worker, args=(batch_id,), daemon=True)
        thread.start()

        flash("Import job started! Google Drive receipts are downloading and processing via high-accuracy OCR in the background.", "success")
        return redirect(url_for("import_bulk_results", batch_id=batch_id))

    auto_map = bulk_drive_ingestion.auto_detect_columns(headers)
    sample_data = [json.loads(r["original_row_data_json"] or "{}") for r in first_rows]
    return render_template("import_bulk_map.html", batch=batch, headers=headers, auto_map=auto_map, samples=sample_data)

@app.route("/import-bulk/batch/<int:batch_id>/results")
@login_required
@role_required(["admin", "accounts"])
def import_bulk_results(batch_id):
    """View processing status and results of imported Google Drive receipts."""
    with connect() as con:
        batch = con.execute("SELECT * FROM import_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            flash("Import batch not found.", "error")
            return redirect(url_for("import_bulk"))

        rows = con.execute("SELECT * FROM import_rows WHERE batch_id=? ORDER BY id ASC", (batch_id,)).fetchall()
        parsed_rows = []
        for r in rows:
            d = dict(r)
            d["extracted"] = json.loads(r["extracted_data_json"] or "{}")
            parsed_rows.append(d)

    return render_template("import_bulk_results.html", batch=batch, rows=parsed_rows)

@app.route("/import-bulk/batch/<int:batch_id>/status")
@login_required
def import_bulk_status(batch_id):
    """JSON status polling endpoint for import progress bar."""
    with connect() as con:
        batch = con.execute("SELECT status, total_rows, completed_rows, failed_rows FROM import_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            return jsonify({"status": "NOT_FOUND"})
        
        rows = con.execute("SELECT id, download_status, ocr_status, import_status, error_message FROM import_rows WHERE batch_id=?", (batch_id,)).fetchall()
        return jsonify({
            "status": batch["status"],
            "total_rows": batch["total_rows"],
            "completed_rows": batch["completed_rows"],
            "failed_rows": batch["failed_rows"],
            "rows": [dict(r) for r in rows]
        })

@app.route("/import-bulk/batch/<int:batch_id>/commit", methods=["POST"])
@login_required
@role_required(["admin", "accounts"])
def import_bulk_commit(batch_id):
    """Commits validated bulk rows into the primary expense audit queue."""
    created_count = 0
    with connect() as con:
        rows = con.execute("""
        SELECT * FROM import_rows 
        WHERE batch_id=? AND import_status IN ('READY_FOR_AUDIT', 'NEEDS_VERIFICATION')
        """, (batch_id,)).fetchall()

        for r in rows:
            ext = json.loads(r["extracted_data_json"] or "{}")
            emp = r["mapped_employee"] or "Aarav Mehta"
            
            u_row = con.execute("SELECT id, office_id FROM users WHERE lower(name)=lower(?)", (emp,)).fetchone()
            u_id = u_row["id"] if u_row else session.get("user_id", 4)
            o_id = u_row["office_id"] if u_row else 1

            amt = ext.get("extracted_total") or 1000.0
            date_val = ext.get("date") or datetime.now().strftime("%Y-%m-%d")
            merchant_val = ext.get("merchant") or "Bulk Imported Receipt"
            curr_val = ext.get("currency") or "INR"

            payload = {
                "employee": emp,
                "expense_date": date_val,
                "merchant": merchant_val,
                "category": "Meals" if "cafe" in merchant_val.lower() or "restaurant" in merchant_val.lower() else "Office Supplies",
                "city": "Mumbai",
                "amount": amt,
                "currency": curr_val,
                "payment_method": "UPI",
                "transaction_ref": f"BULK_DRIVE_{r['id']}",
                "description": f"Bulk imported via Google Drive Link: {r['receipt_url']}",
                "is_trip": 0
            }

            audit_res = analyze_expense(payload, file_path=r["downloaded_file_path"])
            status_val = "Needs Info" if r["import_status"] == "NEEDS_VERIFICATION" else audit_res["status"]

            p_row = con.execute("SELECT id FROM projects WHERE upper(code)='PRJ-2026-Q4'").fetchone()
            project_id = p_row["id"] if p_row else 1

            con.execute("""
            INSERT INTO expenses (
                user_id, office_id, employee, submitted_at, expense_date, merchant, category, city, amount, currency,
                amount_inr, eligible_amount, difference_from_cap, payment_method, transaction_ref, project_code, project_id,
                client_name, attendees, description, status, reimbursable, risk_score, flags, suspicion_types,
                explanation, file_name, source, is_trip, math_status, extracted_amount, itemized_items, audit_log,
                policy_version, editing_deadline, resubmission_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Google Drive Bulk Import', 0, ?, ?, ?, ?, 'v2026.1', ?, 0)
            """, (
                u_id, o_id, emp, datetime.now().strftime("%Y-%m-%d %H:%M"), date_val, merchant_val, payload["category"], payload["city"],
                amt, curr_val, audit_res["amount_inr"], audit_res["reimbursable"], 0, "UPI", payload["transaction_ref"], "PRJ-2026-Q4", project_id,
                "", 0, payload["description"], status_val, audit_res["reimbursable"], audit_res["risk_score"],
                json.dumps(audit_res["flags"]), json.dumps(audit_res["suspicion_types"]), audit_res["explanation"],
                os.path.basename(r["downloaded_file_path"] or ""), audit_res["math_status"], audit_res["extracted_amount"],
                json.dumps(audit_res["itemized_items"]),
                json.dumps([{"action": "Google Drive Bulk Ingestion", "status": status_val, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"), "actor": session.get("user_name", "Reviewer")}]),
                (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
            ))
            new_exp_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.execute("UPDATE import_rows SET import_status='IMPORTED', linked_expense_id=? WHERE id=?", (new_exp_id, r["id"]))
            
            # Execute budget auto-approval
            if status_val == "Approved":
                budget_engine.process_claim_auto_approval(con, new_exp_id, actor="Google Drive Bulk Import")

            created_count += 1

        con.commit()

    flash(f"Successfully committed {created_count} validated receipts from Google Drive into the primary Finance Audit Queue!", "success")
    return redirect(url_for("dashboard"))

@app.route("/expense/<int:expense_id>/field-correction", methods=["POST"])
@login_required
def expense_field_correction(expense_id):
    """
    Human-in-the-loop receipt correction interface:
    Saves immutable record of original OCR value vs corrected value in receipt_field_corrections
    and updates the active expense record without destroying OCR history.
    """
    field_name = request.form.get("field_name")
    corrected_val = request.form.get("corrected_value", "").strip()
    reason = request.form.get("reason", "Manual OCR correction").strip()
    actor_name = session.get("user_name", "Reviewer")

    if not field_name or not corrected_val:
        flash("Field name and corrected value are required.", "error")
        return redirect(url_for("expense_detail", expense_id=expense_id))

    with connect() as con:
        exp = con.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
        if not exp:
            flash("Expense not found.", "error")
            return redirect(url_for("dashboard"))

        original_val = str(exp[field_name]) if field_name in exp.keys() else ""

        con.execute("""
        INSERT INTO receipt_field_corrections (expense_id, field_name, original_ocr_value, corrected_value, corrected_by, corrected_at, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (expense_id, field_name, original_val, corrected_val, actor_name, datetime.now().strftime("%Y-%m-%d %H:%M"), reason))

        if field_name == "amount":
            try:
                amt = float(corrected_val)
                con.execute("UPDATE expenses SET amount=?, amount_inr=?, eligible_amount=? WHERE id=?", (amt, amt, amt, expense_id))
            except ValueError:
                pass
        elif field_name in ("merchant", "expense_date", "category", "city"):
            con.execute(f"UPDATE expenses SET {field_name}=? WHERE id=?", (corrected_val, expense_id))

        audit_log = json.loads(exp["audit_log"] or "[]")
        audit_log.append({
            "action": f"Field Correction: {field_name}",
            "status": exp["status"],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "actor": actor_name,
            "note": f"Corrected '{field_name}' from '{original_val}' to '{corrected_val}'. Reason: {reason}"
        })
        con.execute("UPDATE expenses SET audit_log=? WHERE id=?", (json.dumps(audit_log), expense_id))
        con.commit()

    flash(f"Field '{field_name}' successfully corrected and recorded with immutable original provenance!", "success")
    return redirect(url_for("expense_detail", expense_id=expense_id))

@app.route("/bulk-action", methods=["POST"])
@login_required
@role_required(["admin", "accounts"])
def bulk_action():
    action = request.form.get("action")
    with connect() as con:
        if action == "approve_clean":
            con.execute("UPDATE expenses SET status='Approved' WHERE status IN ('Needs Review', 'Needs Info') AND risk_score = 0")
            flash("Auto-approved all clean, zero-risk expenses!", "success")
        elif action == "seed_dataset":
            seed_data.seed_database(con)
            flash("Loaded realistic 1-Month Hackathon Dataset (24 receipts, multi-channel, offices, dual evidence)!", "success")
        elif action == "reset_db":
            con.execute("DELETE FROM expenses")
            try: con.execute("DELETE FROM sqlite_sequence WHERE name='expenses'")
            except Exception: pass
            flash("Database reset. You can now test from a completely clean slate or re-seed anytime.", "info")
    return redirect(url_for("dashboard"))

@app.route("/analytics")
@login_required
@role_required(["admin", "accounts"])
def analytics():
    with connect() as con:
        rows = con.execute("SELECT * FROM expenses ORDER BY expense_date ASC").fetchall()
        trips = trip_engine.reconstruct_trips(rows)

        emp_stats = {}
        for r in rows:
            emp = r["employee"]
            if emp not in emp_stats:
                emp_stats[emp] = {"claimed": 0.0, "reimbursable": 0.0, "count": 0, "violations": 0}
            emp_stats[emp]["claimed"] += float(r["amount_inr"] or 0)
            emp_stats[emp]["reimbursable"] += float(r["reimbursable"] or 0)
            emp_stats[emp]["count"] += 1
            if r["status"] in ("Needs Review", "Needs Info", "Rejected", "Duplicate"):
                emp_stats[emp]["violations"] += 1

        violations_map = {}
        for r in rows:
            types = json.loads(r["suspicion_types"] or "[]")
            for t in types:
                violations_map[t] = violations_map.get(t, 0) + 1

    return render_template(
        "analytics.html",
        expenses=rows,
        trips=trips,
        emp_stats=emp_stats,
        violations_map=violations_map,
        policy=POLICY
    )

@app.route("/policy")
def policy():
    return render_template("policy.html", policy=POLICY)

@app.route("/expense/<int:expense_id>/voucher")
def expense_voucher(expense_id):
    with connect() as con:
        row = con.execute("SELECT * FROM expenses WHERE id=?", (expense_id,)).fetchone()
    if not row:
        flash("Expense not found.", "error")
        return redirect(url_for("dashboard"))
    return render_template(
        "voucher.html",
        expense=row,
        flags=json.loads(row["flags"] or "[]"),
        line_items=json.loads(row["itemized_items"] or "[]"),
        policy=POLICY
    )

@app.route("/export.csv")
@login_required
@role_required(["admin", "accounts"])
def export_csv():
    with connect() as con:
        rows = con.execute("""
        SELECT id, employee, submitted_at, expense_date, merchant, category, city,
               amount, currency, amount_inr, reimbursable, status, risk_score,
               payment_method, transaction_ref, upi_app, upi_vpa, payment_verified, payment_match_note,
               math_status, non_reimbursable_deduction, client_name, project_code, attendees,
               is_trip, source, flags, explanation
        FROM expenses ORDER BY id
        """).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow(list(row))
    else:
        writer.writerow(["id", "employee", "amount_inr", "status"])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=receipt_graveyard_audit_export.csv"}
    )

@app.route("/export.json")
@login_required
@role_required(["admin", "accounts"])
def export_json():
    with connect() as con:
        rows = con.execute("SELECT * FROM expenses ORDER BY id").fetchall()
        result = [dict(r) for r in rows]
    return jsonify(result)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

@app.errorhandler(413)
def too_large(_):
    flash("File exceeds size limit (Max 30 MB).", "error")
    return redirect(url_for("submit"))

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=port, debug=debug)
