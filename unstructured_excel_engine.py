# unstructured_excel_engine.py - Smart Unstructured Excel Ledger Ingestion & Auto-User Provisioning Engine
import io
import re
import csv
import json
import logging
from datetime import datetime, date
from pathlib import Path

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

logger = logging.getLogger("unstructured_excel_engine")

COLUMN_VARIATIONS = {
    "employee": [
        "employee", "employee name", "staff name", "staff", "claimant", "user",
        "name", "worker", "submitted by", "employee id", "emp name", "spender",
        "person", "team member", "who", "resource name", "consultant"
    ],
    "email": [
        "employee email", "email", "email address", "staff email", "user email",
        "mail", "work email", "official email", "corporate email"
    ],
    "expense_date": [
        "expense date", "date", "transaction date", "txn date", "bill date",
        "receipt date", "spend date", "spent on", "invoice date", "when", "day", "payment date", "date of expense"
    ],
    "merchant": [
        "merchant", "vendor", "store", "payee", "establishment", "shop",
        "service provider", "merchant name", "supplier", "seller", "place",
        "hotel", "airline", "restaurant", "biller", "company"
    ],
    "amount": [
        "amount", "claimed amount", "total", "cost", "expense amount", "gross amount",
        "total amount", "grand total", "net amount", "sum", "price", "bill amount",
        "inr", "amount spent", "total spent", "value", "subtotal"
    ],
    "currency": [
        "currency", "curr", "currency code", "iso currency", "fx"
    ],
    "category": [
        "category", "expense category", "type", "expense type", "cost type",
        "classification", "head", "spend type", "cost center", "expense head"
    ],
    "city": [
        "city", "location", "destination", "expense city", "town", "place", "site"
    ],
    "project_code": [
        "project code", "project", "cost center", "project id", "prj code",
        "prj", "client code", "wbs code", "client", "project name", "account"
    ],
    "description": [
        "description", "business purpose", "purpose", "notes", "memo",
        "justification", "details", "comments", "reason", "item details", "remarks"
    ],
    "payment_method": [
        "payment method", "payment mode", "mode", "payment type", "paid via",
        "paid by", "payment instrument"
    ],
    "transaction_ref": [
        "transaction ref", "utr", "upi ref", "ref no", "reference",
        "txn id", "transaction id", "rrn", "auth code", "receipt no", "invoice no"
    ],
    "department": [
        "department", "dept", "division", "team", "unit", "business unit"
    ],
    "designation": [
        "designation", "role", "title", "position", "job title"
    ],
    "phone": [
        "phone", "mobile", "contact", "cell", "telephone"
    ]
}

CATEGORY_MAP = {
    "meal": "Meals",
    "food": "Meals",
    "dining": "Meals",
    "lunch": "Meals",
    "dinner": "Meals",
    "breakfast": "Meals",
    "snack": "Meals",
    "coffee": "Meals",
    "cafe": "Meals",
    "restaurant": "Meals",
    "travel": "Travel",
    "flight": "Travel",
    "train": "Travel",
    "railway": "Travel",
    "cab": "Travel",
    "taxi": "Travel",
    "uber": "Travel",
    "ola": "Travel",
    "metro": "Travel",
    "commute": "Travel",
    "air": "Travel",
    "hotel": "Lodging",
    "stay": "Lodging",
    "lodge": "Lodging",
    "resort": "Lodging",
    "accommodation": "Lodging",
    "office": "Office Supplies",
    "supplies": "Office Supplies",
    "stationery": "Office Supplies",
    "hardware": "Office Supplies",
    "software": "Software",
    "subscription": "Software",
    "saas": "Software",
    "cloud": "Software",
    "license": "Software",
    "client": "Client Entertainment",
    "entertainment": "Client Entertainment",
    "customer": "Client Entertainment"
}

def clean_amount(val):
    """Parses arbitrary amounts like '₹ 1,450.50', '$200', '1400', etc."""
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    s = re.sub(r"[₹$,€£\s]", "", s)
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0

def clean_date(val):
    """Normalizes Excel datetime objects, serial numbers, and varied date strings to YYYY-MM-DD."""
    if not val:
        return datetime.now().strftime("%Y-%m-%d")
    
    # If already date or datetime object
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
        
    s = str(val).strip()
    # Check if excel serial number (e.g. 45579)
    try:
        if s.isdigit() and int(s) > 30000:
            dt = datetime.fromordinal(datetime(1899, 12, 30).toordinal() + int(s))
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass

    s = s.replace("/", "-").replace(".", "-")
    # Try common formats
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y", "%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s.split(" ")[0], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
            
    # Fallback to parts splitting
    parts = s.split("-")
    if len(parts) == 3:
        if len(parts[0]) == 4:
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        elif len(parts[2]) == 4:
            return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"

    return datetime.now().strftime("%Y-%m-%d")

def standardize_category(raw_cat):
    """Maps varied category text to standard portal categories."""
    if not raw_cat:
        return "Other"
    lower = str(raw_cat).lower().strip()
    for kw, std in CATEGORY_MAP.items():
        if kw in lower:
            return std
    return str(raw_cat).strip().title()

def find_best_header_row(rows):
    """
    Scans the first 10 rows of an unstructured sheet to locate the true header row,
    skipping title/logo rows and empty lines.
    """
    best_row_idx = 0
    max_matches = -1

    for row_idx, r in enumerate(rows[:12]):
        if not r or not any(r):
            continue
        row_str_cells = [str(c).lower().strip() for c in r if c is not None and str(c).strip()]
        if not row_str_cells:
            continue
        
        matches = 0
        for cell_txt in row_str_cells:
            for field, variations in COLUMN_VARIATIONS.items():
                if any(v in cell_txt for v in variations):
                    matches += 1
                    break
        if matches > max_matches:
            max_matches = matches
            best_row_idx = row_idx

    return best_row_idx

def map_headers(headers):
    """Matches raw headers to portal attributes with priority ordering."""
    mapping = {}
    lower_headers = [str(h).strip().lower().replace("_", " ").replace("-", " ") if h is not None else "" for h in headers]
    used_indices = set()

    priority_order = [
        "expense_date", "email", "amount", "employee", "merchant", 
        "category", "project_code", "city", "description", 
        "payment_method", "transaction_ref", "department", "designation", "phone"
    ]

    # Pass 1: Exact matches across all prioritized fields
    for field in priority_order:
        var_list = COLUMN_VARIATIONS.get(field, [])
        for idx, h in enumerate(lower_headers):
            if idx in used_indices or not h:
                continue
            if h in var_list:
                mapping[field] = idx
                used_indices.add(idx)
                break

    # Pass 2: Substring matches for unmapped fields
    for field in priority_order:
        if field in mapping:
            continue
        var_list = COLUMN_VARIATIONS.get(field, [])
        for idx, h in enumerate(lower_headers):
            if idx in used_indices or not h:
                continue
            if any(v in h for v in var_list):
                mapping[field] = idx
                used_indices.add(idx)
                break

    return mapping

def parse_unstructured_file(file_bytes, filename="ledger.xlsx"):
    """
    Reads an unstructured Excel or CSV file and extracts raw data matrix.
    """
    is_csv = filename.lower().endswith(".csv")
    rows = []

    if not is_csv and HAS_OPENPYXL:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            # Find the sheet with the most non-empty rows
            best_sheet = None
            max_r = 0
            for name in wb.sheetnames:
                ws = wb[name]
                r_count = ws.max_row or 0
                if r_count > max_r:
                    max_r = r_count
                    best_sheet = ws
            if best_sheet:
                for r in best_sheet.iter_rows(values_only=True):
                    rows.append(list(r))
        except Exception as e:
            logger.warning(f"openpyxl failed to parse {filename}: {e}. Trying CSV fallback.")
            rows = []

    if not rows:
        # Fallback to CSV / text parsing
        text = file_bytes.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader]

    if not rows:
        return {"error": "No readable tabular data found in the uploaded file.", "rows": []}

    # Find the header row
    header_idx = find_best_header_row(rows)
    raw_headers = rows[header_idx]
    data_rows = rows[header_idx + 1:]

    # Clean headers
    headers = [str(h).strip() if h is not None and str(h).strip() else f"Col_{i+1}" for i, h in enumerate(raw_headers)]
    col_map = map_headers(headers)

    return {
        "error": None,
        "headers": headers,
        "col_map": col_map,
        "header_row_index": header_idx + 1,
        "data_rows": data_rows,
        "total_rows": len(data_rows)
    }

def process_unstructured_ledger(con, file_bytes, filename, current_user_id=1, analyze_func=None):
    """
    Main orchestration function:
    1. Parses unstructured Excel file.
    2. Identifies or automatically registers newly detected employees (creates login credentials).
    3. Normalizes and structures records to portal requirements.
    4. Audits compliance, budget allocations, and saves claims into database.
    5. Returns an executive ingestion report with user credentials and arranged claims.
    """
    parse_result = parse_unstructured_file(file_bytes, filename)
    if parse_result.get("error"):
        return {"success": False, "error": parse_result["error"]}

    col_map = parse_result["col_map"]
    data_rows = parse_result["data_rows"]

    if not data_rows:
        return {"success": False, "error": "The uploaded workbook does not contain any data rows."}

    # Caches for users, offices, and projects
    existing_users_by_name = {r["name"].strip().lower(): dict(r) for r in con.execute("SELECT * FROM users").fetchall()}
    existing_users_by_email = {r["email"].strip().lower(): dict(r) for r in con.execute("SELECT * FROM users").fetchall()}
    
    offices = con.execute("SELECT id, name FROM offices").fetchall()
    default_office_id = offices[0]["id"] if offices else 1

    projects = con.execute("SELECT id, code, name FROM projects WHERE status='Active'").fetchall()
    default_project = dict(projects[0]) if projects else {"id": 1, "code": "PRJ-MIG-2026"}

    new_users_created = []
    arranged_expenses = []
    total_amount_sum = 0.0
    category_counts = {}

    import budget_engine

    for row_idx, row in enumerate(data_rows, start=parse_result["header_row_index"] + 1):
        if not row or not any(row):
            continue

        def get_field(name, fallback=""):
            idx = col_map.get(name)
            if idx is not None and idx < len(row):
                val = row[idx]
                return str(val).strip() if val is not None else fallback
            return fallback

        # 1. Identify Employee & Create Login if doesn't exist
        raw_emp = get_field("employee")
        raw_email = get_field("email")
        raw_dept = get_field("department", "Operations")
        raw_desig = get_field("designation", "Staff Associate")
        raw_phone = get_field("phone", "+91 98000 00000")

        if not raw_emp and raw_email:
            raw_emp = raw_email.split("@")[0].replace(".", " ").replace("_", " ").title()
        elif not raw_emp:
            raw_emp = f"Team Member #{row_idx}"

        emp_name = " ".join([part.capitalize() for part in raw_emp.split()])
        
        user_record = existing_users_by_name.get(emp_name.lower())
        if not user_record and raw_email:
            user_record = existing_users_by_email.get(raw_email.lower())

        if not user_record:
            # CREATE NEW LOGIN FOR THIS PERSON
            safe_slug = re.sub(r"[^a-z0-9]", ".", emp_name.lower())
            safe_email = raw_email.lower() if raw_email else f"{safe_slug}@receiptgraveyard.com"
            if safe_email in existing_users_by_email:
                safe_email = f"{safe_slug}.{row_idx}@receiptgraveyard.com"

            default_password = f"Welcome@{datetime.now().year}"
            avatar_colors = ['#0f766e', '#15803d', '#0369a1', '#b45309', '#7c3aed', '#4338ca']
            avatar_color = avatar_colors[len(emp_name) % len(avatar_colors)]

            con.execute("""
            INSERT INTO users (
                name, email, password, role, office_id, department, designation, phone, 
                avatar_color, status, is_active, created_at
            ) VALUES (?, ?, ?, 'employee', ?, ?, ?, ?, ?, 'APPROVED', 1, ?)
            """, (
                emp_name, safe_email, default_password, default_office_id, 
                raw_dept, raw_desig, raw_phone, avatar_color,
                datetime.now().strftime("%Y-%m-%d %H:%M")
            ))
            new_u_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

            user_record = {
                "id": new_u_id,
                "name": emp_name,
                "email": safe_email,
                "password": default_password,
                "role": "employee",
                "office_id": default_office_id,
                "department": raw_dept,
                "designation": raw_desig
            }
            existing_users_by_name[emp_name.lower()] = user_record
            existing_users_by_email[safe_email.lower()] = user_record

            new_users_created.append({
                "id": new_u_id,
                "name": emp_name,
                "email": safe_email,
                "password": default_password,
                "role": "employee",
                "department": raw_dept,
                "designation": raw_desig
            })

            # Auto-assign to default active project allocation so user has a spending cap immediately
            try:
                con.execute("""
                INSERT OR IGNORE INTO project_memberships (project_id, user_id, role, assigned_at)
                VALUES (?, ?, 'Member', ?)
                """, (default_project["id"], new_u_id, datetime.now().strftime("%Y-%m-%d %H:%M")))

                con.execute("""
                INSERT OR IGNORE INTO project_allocations (
                    project_id, user_id, allocated_cap, approved_expenditure, reserved_expenditure, 
                    remaining_balance, start_date, end_date, status, created_by, created_at, updated_at
                ) VALUES (?, ?, 25000.0, 0.0, 0.0, 25000.0, '2026-01-01', '2026-12-31', 'Active', 'Accounts Auto-Provisioning', ?, ?)
                """, (default_project["id"], new_u_id, datetime.now().strftime("%Y-%m-%d %H:%M"), datetime.now().strftime("%Y-%m-%d %H:%M")))
            except Exception as e:
                logger.warning(f"Could not assign default allocation to new user {new_u_id}: {e}")

        user_id = user_record["id"]
        office_id = user_record.get("office_id") or default_office_id

        # 2. Normalize and Arrange Expense Attributes
        amount_val = clean_amount(get_field("amount", "0"))
        if amount_val <= 0:
            continue

        total_amount_sum += amount_val
        date_val = clean_date(get_field("expense_date"))
        merchant_val = get_field("merchant", "General Vendor").strip().title() or "General Vendor"
        raw_cat = get_field("category", "General")
        cat_val = standardize_category(raw_cat)
        category_counts[cat_val] = category_counts.get(cat_val, 0) + 1

        city_val = get_field("city", "Mumbai").strip().title() or "Mumbai"
        desc_val = get_field("description", f"Imported claim: {merchant_val} ({cat_val})").strip()
        proj_code_val = get_field("project_code", default_project["code"]).strip().upper()
        
        # Match project or assign default
        matched_proj = None
        for p in projects:
            if p["code"].upper() == proj_code_val or proj_code_val in p["name"].upper():
                matched_proj = dict(p)
                break
        if not matched_proj:
            matched_proj = default_project
        proj_id_val = matched_proj["id"]
        proj_code_val = matched_proj["code"]

        payment_method_val = get_field("payment_method", "Corporate Card / UPI").strip()
        txn_ref_val = get_field("transaction_ref", f"TXN-EXCEL-{row_idx}-{datetime.now().strftime('%M%S')}").strip()

        # 3. Policy & Budget Cap Evaluation
        eligible_amount = amount_val
        status = "Approved"
        risk_score = 0
        flags = [f"Imported via Unstructured Excel Ledger ({filename})"]

        # Run budget check against allocation
        alloc = con.execute("SELECT * FROM project_allocations WHERE user_id=? AND project_id=?", (user_id, proj_id_val)).fetchone()
        if not alloc:
            alloc = budget_engine.get_or_create_allocation(con, proj_id_val, user_id, cap=25000.0, actor="Accounts Auto-Provisioning")

        if alloc:
            rem = float(alloc["remaining_balance"] or 0)
            if amount_val > rem:
                diff = amount_val - rem
                flags.append(f"Expense exceeds allocated cap by ₹{diff:,.2f}; escalated to Accounts.")
                status = "Needs Review"
                risk_score += 35

        # 4. Insert Arranged Claim into Portal Database
        con.execute("""
        INSERT INTO expenses (
            user_id, office_id, employee, submitted_at, expense_date, merchant,
            category, city, amount, currency, amount_inr, eligible_amount, difference_from_cap,
            project_id, project_code, description, payment_method, transaction_ref,
            status, reimbursable, risk_score, flags, explanation, source, math_status
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, 'INR', ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, 'Excel Ledger Ingestion', 'Verified'
        )
        """, (
            user_id, office_id, emp_name, datetime.now().strftime("%Y-%m-%d %H:%M"),
            date_val, merchant_val, cat_val, city_val, amount_val, amount_val,
            eligible_amount, max(0.0, amount_val - eligible_amount),
            proj_id_val, proj_code_val, desc_val, payment_method_val, txn_ref_val,
            status, eligible_amount, risk_score, json.dumps(flags),
            f"Successfully parsed and arranged from unstructured sheet row #{row_idx}"
        ))
        expense_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Log into version history
        snapshot = {
            "id": expense_id,
            "employee": emp_name,
            "merchant": merchant_val,
            "amount": amount_val,
            "category": cat_val,
            "date": date_val,
            "status": status,
            "project_code": proj_code_val
        }
        con.execute("""
        INSERT INTO claim_versions (claim_id, version_num, changed_by, changed_at, status, claimed_amount, reimbursable, snapshot_json, change_summary)
        VALUES (?, 1, 'Accounts Ingestion Engine', ?, ?, ?, ?, ?, 'Parsed from unstructured Excel workbook')
        """, (expense_id, datetime.now().strftime("%Y-%m-%d %H:%M"), status, amount_val, eligible_amount, json.dumps(snapshot)))

        # Update budget ledger if approved
        if status == "Approved":
            try:
                budget_engine.apply_budget_approval(
                    con, expense_id, actor="Accounts Ledger Ingestion", is_auto=False
                )
            except Exception as e:
                logger.warning(f"Could not deduct budget for expense {expense_id}: {e}")

        arranged_expenses.append({
            "id": expense_id,
            "row_num": row_idx,
            "employee": emp_name,
            "date": date_val,
            "merchant": merchant_val,
            "category": cat_val,
            "amount": amount_val,
            "eligible": eligible_amount,
            "project_code": proj_code_val,
            "status": status,
            "user_id": user_id
        })

    con.commit()

    return {
        "success": True,
        "filename": filename,
        "total_rows_processed": len(arranged_expenses),
        "total_amount_inr": total_amount_sum,
        "new_users_created": new_users_created,
        "existing_users_count": len(existing_users_by_name) - len(new_users_created),
        "arranged_expenses": arranged_expenses,
        "category_counts": category_counts,
        "headers_detected": list(col_map.keys())
    }
