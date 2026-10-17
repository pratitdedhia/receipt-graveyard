# historical_ingestion.py - Historical Expense Dataset Ingestion & Standardized Export Module
import csv
import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
import budget_engine

def identify_columns(headers):
    """
    Intelligently maps inconsistent CSV column names to standardized fields.
    Supports many variations found in enterprise expense reports.
    """
    col_map = {}
    lower_headers = [h.strip().lower().replace("_", " ").replace("-", " ") for h in headers]

    variations = {
        "employee": ["employee name", "employee", "staff name", "staff", "claimant", "user", "name", "worker", "submitted by", "employee id", "emp name"],
        "email": ["employee email", "email", "email address", "staff email", "user email", "mail"],
        "expense_date": ["expense date", "date", "transaction date", "txn date", "bill date", "receipt date", "spend date"],
        "merchant": ["merchant", "vendor", "store", "payee", "establishment", "shop", "service provider", "merchant name", "supplier"],
        "amount": ["amount", "claimed amount", "total", "cost", "expense amount", "gross amount", "total amount", "grand total", "net amount", "sum", "price"],
        "currency": ["currency", "curr", "currency code", "iso currency", "fx"],
        "category": ["category", "expense category", "type", "expense type", "cost type", "classification"],
        "city": ["city", "location", "destination", "expense city", "town", "place"],
        "project_code": ["project code", "project", "cost center", "project id", "prj code", "prj", "client code", "wbs code"],
        "description": ["description", "business purpose", "purpose", "notes", "memo", "justification", "details", "comments", "reason"],
        "payment_method": ["payment method", "payment mode", "mode", "payment type", "paid via", "paid by"],
        "client_name": ["client name", "client", "customer", "account name", "organization"],
        "attendees": ["attendees", "attendee count", "pax", "number of attendees", "guests", "participants"],
        "transaction_ref": ["transaction ref", "utr", "upi ref", "ref no", "reference", "txn id", "transaction id", "rrn", "auth code"]
    }

    used_indices = set()
    for field, var_list in variations.items():
        matched_idx = None
        # Try exact match first
        for idx, h in enumerate(lower_headers):
            if idx in used_indices:
                continue
            if h in var_list:
                matched_idx = idx
                break
        # Fallback to substring match
        if matched_idx is None:
            for idx, h in enumerate(lower_headers):
                if idx in used_indices:
                    continue
                if any(v in h for v in var_list):
                    matched_idx = idx
                    break

        if matched_idx is not None:
            col_map[field] = matched_idx
            used_indices.add(matched_idx)

    return col_map

def normalize_date_str(val):
    if not val:
        return datetime.now().strftime("%Y-%m-%d")
    val = val.strip().replace("/", "-")
    parts = val.split("-")
    if len(parts) == 3:
        # Check if YYYY-MM-DD
        if len(parts[0]) == 4:
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        # Check if DD-MM-YYYY
        elif len(parts[2]) == 4:
            return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
        # Check if MM-DD-YYYY
        elif len(parts[2]) == 4 and int(parts[0]) <= 12 and int(parts[1]) > 12:
            return f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
    try:
        dt = datetime.strptime(val, "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

def ingest_historical_csv(con, csv_text_or_file, current_user_name="Admin"):
    """Convenience wrapper for test suites and scripts."""
    import app
    return ingest_csv_data(csv_text_or_file, con, app.analyze_expense, current_user_name)

def ingest_csv_data(csv_text_or_file, con, analyze_func, current_user_name="Admin"):
    """
    Parses a historical expense CSV, verifies/creates employee profiles,
    normalizes data, audits expenses, and returns an ingestion summary.
    """
    if isinstance(csv_text_or_file, bytes):
        csv_text = csv_text_or_file.decode("utf-8", errors="replace")
    elif hasattr(csv_text_or_file, "read"):
        content = csv_text_or_file.read()
        csv_text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    else:
        csv_text = str(csv_text_or_file)

    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return {"error": "Empty CSV file provided"}

    headers = rows[0]
    data_rows = rows[1:]
    col_map = identify_columns(headers)

    total_rows = len(data_rows)
    imported_rows = 0
    employees_detected = set()
    duplicates_detected = 0
    created_expense_ids = []
    error_list = []

    # Cache existing users
    existing_users = {r["name"].lower(): dict(r) for r in con.execute("SELECT * FROM users").fetchall()}
    existing_emails = {r["email"].lower(): dict(r) for r in con.execute("SELECT * FROM users").fetchall()}

    for line_num, row in enumerate(data_rows, 2):
        if not row or not any(row):
            continue

        def get_val(field, default=""):
            idx = col_map.get(field)
            if idx is not None and idx < len(row):
                return row[idx].strip()
            return default

        emp_raw = get_val("employee", "")
        email_raw = get_val("email", "")

        # Fallback employee identification
        if not emp_raw and email_raw:
            emp_raw = email_raw.split("@")[0].replace(".", " ").title()
        elif not emp_raw:
            emp_raw = f"Imported Staff #{line_num}"

        emp_name = emp_raw.strip()
        employees_detected.add(emp_name)

        # Employee Identity Resolution
        user_record = existing_users.get(emp_name.lower())
        if not user_record and email_raw:
            user_record = existing_emails.get(email_raw.lower())

        if not user_record:
            # Create a verified employee account for this imported staff member
            safe_email = email_raw or f"{emp_name.lower().replace(' ', '.')}@company.com"
            if safe_email.lower() in existing_emails:
                safe_email = f"{emp_name.lower().replace(' ', '.')}.{line_num}@company.com"

            avatar_colors = ['#0f766e', '#15803d', '#0369a1', '#b45309', '#7c3aed', '#4338ca']
            avatar_col = avatar_colors[len(emp_name) % len(avatar_colors)]

            con.execute("""
            INSERT INTO users (name, email, password, role, office_id, department, phone, avatar_color, is_active, created_at)
            VALUES (?, ?, 'welcome123', 'employee', 1, 'Historical Ingestion', '+91 98000 00000', ?, 1, ?)
            """, (emp_name, safe_email, avatar_col, datetime.now().strftime("%Y-%m-%d %H:%M")))
            new_u_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.commit()

            user_record = {
                "id": new_u_id,
                "name": emp_name,
                "email": safe_email,
                "role": "employee",
                "office_id": 1
            }
            existing_users[emp_name.lower()] = user_record
            existing_emails[safe_email.lower()] = user_record

        u_id = user_record["id"]
        o_id = user_record.get("office_id") or 1

        # Financial values
        raw_amount = get_val("amount", "0").replace(",", "").replace("₹", "").replace("$", "").replace("€", "").replace("£", "")
        try:
            amount_val = float(raw_amount)
        except ValueError:
            amount_val = 0.0

        currency_val = get_val("currency", "INR").upper()
        date_val = normalize_date_str(get_val("expense_date"))
        merchant_val = get_val("merchant", "Historical Vendor")
        cat_val = get_val("category", "Other")
        city_val = get_val("city", "Mumbai")
        desc_val = get_val("description", "Historical batch imported transaction")
        proj_val = get_val("project_code", "PRJ-2026-Q4")
        client_val = get_val("client_name", "")
        try:
            attendees_val = int(get_val("attendees", "0"))
        except ValueError:
            attendees_val = 0
        payment_method_val = get_val("payment_method", "UPI")
        txn_ref_val = get_val("transaction_ref", "")

        # Prepare payload for policy evaluation
        data_payload = {
            "employee": emp_name,
            "expense_date": date_val,
            "merchant": merchant_val,
            "category": cat_val,
            "city": city_val,
            "amount": amount_val,
            "currency": currency_val,
            "payment_method": payment_method_val,
            "transaction_ref": txn_ref_val,
            "client_name": client_val,
            "project_code": proj_val,
            "attendees": attendees_val,
            "attendee_names": emp_name,
            "description": desc_val,
            "is_trip": 0
        }

        # Run Audit Decision
        result = analyze_func(data_payload)
        if result["status"] == "Duplicate":
            duplicates_detected += 1

        # Look up project_id if project exists
        p_row = con.execute("SELECT id FROM projects WHERE upper(code)=upper(?)", (proj_val,)).fetchone()
        project_id = p_row["id"] if p_row else None

        submitted_at_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        con.execute("""
        INSERT INTO expenses (
            user_id, office_id, employee, submitted_at, expense_date, merchant, category, city, amount, currency,
            amount_inr, payment_method, transaction_ref, upi_app, upi_vpa, project_id, payment_file, payment_verified, payment_match_note,
            client_name, project_code, attendees, attendee_names, description, status, reimbursable, risk_score,
            flags, suspicion_types, explanation, file_name, file_hash, perceptual_hash,
            source, is_trip, math_status, extracted_amount, non_reimbursable_deduction,
            itemized_items, ocr_raw_text, duplicate_of_id, audit_log
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            u_id, o_id, emp_name, submitted_at_str, date_val,
            merchant_val, cat_val, city_val, amount_val, currency_val,
            result["amount_inr"], payment_method_val, txn_ref_val, "Google Pay", "",
            project_id, None, 1 if result["status"] == "Approved" else 0, "Historical import record.",
            client_val, proj_val, attendees_val, emp_name, desc_val,
            result["status"], result["reimbursable"], result["risk_score"],
            json.dumps(result["flags"]), json.dumps(result["suspicion_types"]),
            result["explanation"], None, None, None,
            "Historical CSV Ingestion", result["is_trip"], "Imported Record", result["extracted_amount"],
            result["non_reimbursable_deduction"], json.dumps(result["itemized_items"]),
            "", result["duplicate_of_id"],
            json.dumps([{"action": "Historical CSV Ingestion", "status": result["status"], "timestamp": submitted_at_str, "actor": current_user_name}])
        ))
        new_exp_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        created_expense_ids.append(new_exp_id)
        imported_rows += 1

        if project_id and result["status"] == "Approved":
            budget_engine.process_claim_auto_approval(con, new_exp_id, actor=f"Historical CSV Import ({current_user_name})")

    con.commit()

    summary = {
        "status": "Success",
        "total_rows": total_rows,
        "imported_rows": imported_rows,
        "employees_detected": len(employees_detected),
        "employee_names": sorted(list(employees_detected)),
        "duplicates_detected": duplicates_detected,
        "created_ids_count": len(created_expense_ids),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Record job in database
    con.execute("""
    INSERT INTO historical_ingestion_jobs (filename, total_rows, imported_rows, employees_detected, duplicates_detected, status, ingestion_summary_json, created_at)
    VALUES (?, ?, ?, ?, ?, 'Completed', ?, ?)
    """, ("historical_upload.csv", total_rows, imported_rows, len(employees_detected), duplicates_detected, json.dumps(summary), datetime.now().strftime("%Y-%m-%d %H:%M")))
    con.commit()

    return summary

def generate_standardized_export_zip(con):
    """
    Generates a standardized ZIP package containing the 8 canonical export files:
    1. employees.csv
    2. expenses.csv
    3. receipts.csv
    4. expense_items.csv
    5. policy_evaluations.csv
    6. duplicate_candidates.csv
    7. risk_flags.csv
    8. ingestion_summary.json
    """
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. employees.csv
        users = con.execute("SELECT id, name, email, role, office_id, department, phone, is_active FROM users ORDER BY id").fetchall()
        emp_io = io.StringIO()
        w = csv.writer(emp_io)
        w.writerow(["employee_id", "full_name", "email", "role", "office_id", "department", "phone", "status"])
        for u in users:
            w.writerow([u["id"], u["name"], u["email"], u["role"], u["office_id"], u["department"], u["phone"], "Active" if u["is_active"] else "Inactive"])
        zf.writestr("employees.csv", emp_io.getvalue())

        # 2. expenses.csv
        expenses = con.execute("SELECT * FROM expenses ORDER BY id").fetchall()
        exp_io = io.StringIO()
        w = csv.writer(exp_io)
        w.writerow([
            "claim_id", "user_id", "employee", "expense_date", "merchant", "category", "city",
            "amount", "currency", "amount_inr", "eligible_amount", "reimbursable", "status",
            "project_code", "payment_method", "transaction_ref", "upi_app", "upi_vpa",
            "risk_score", "source", "submitted_at"
        ])
        for e in expenses:
            w.writerow([
                e["id"], e["user_id"], e["employee"], e["expense_date"], e["merchant"], e["category"], e["city"],
                e["amount"], e["currency"], e["amount_inr"], e["reimbursable"], e["reimbursable"], e["status"],
                e["project_code"], e["payment_method"], e["transaction_ref"], e["upi_app"] or "", e["upi_vpa"] or "",
                e["risk_score"], e["source"], e["submitted_at"]
            ])
        zf.writestr("expenses.csv", exp_io.getvalue())

        # 3. receipts.csv
        rec_io = io.StringIO()
        w = csv.writer(rec_io)
        w.writerow(["claim_id", "file_name", "file_hash", "perceptual_hash", "payment_file", "payment_verified", "math_status"])
        for e in expenses:
            w.writerow([
                e["id"], e["file_name"] or "", e["file_hash"] or "", e["perceptual_hash"] or "",
                e["payment_file"] or "", e["payment_verified"], e["math_status"] or ""
            ])
        zf.writestr("receipts.csv", rec_io.getvalue())

        # 4. expense_items.csv
        item_io = io.StringIO()
        w = csv.writer(item_io)
        w.writerow(["claim_id", "item_name", "price", "is_deducted", "deduction_category"])
        for e in expenses:
            items = json.loads(e["itemized_items"] or "[]")
            for itm in items:
                w.writerow([
                    e["id"],
                    itm.get("item", itm.get("description", "Item")),
                    itm.get("price", itm.get("amount", 0)),
                    1 if itm.get("deducted") else 0,
                    itm.get("deduction_category", "")
                ])
        zf.writestr("expense_items.csv", item_io.getvalue())

        # 5. policy_evaluations.csv
        eval_io = io.StringIO()
        w = csv.writer(eval_io)
        w.writerow(["claim_id", "status", "risk_score", "flags_count", "flags_summary", "explanation"])
        for e in expenses:
            flags = json.loads(e["flags"] or "[]")
            w.writerow([
                e["id"], e["status"], e["risk_score"], len(flags),
                " | ".join(flags), e["explanation"] or ""
            ])
        zf.writestr("policy_evaluations.csv", eval_io.getvalue())

        # 6. duplicate_candidates.csv
        dup_io = io.StringIO()
        w = csv.writer(dup_io)
        w.writerow(["claim_id", "duplicate_of_id", "employee", "merchant", "amount_inr", "suspicion_type"])
        for e in expenses:
            if e["duplicate_of_id"] or e["status"] == "Duplicate":
                stypes = json.loads(e["suspicion_types"] or "[]")
                w.writerow([
                    e["id"], e["duplicate_of_id"] or "", e["employee"], e["merchant"],
                    e["amount_inr"], " | ".join(stypes)
                ])
        zf.writestr("duplicate_candidates.csv", dup_io.getvalue())

        # 7. risk_flags.csv
        risk_io = io.StringIO()
        w = csv.writer(risk_io)
        w.writerow(["claim_id", "risk_score", "suspicion_types", "flags_detail"])
        for e in expenses:
            if (e["risk_score"] or 0) > 0:
                stypes = json.loads(e["suspicion_types"] or "[]")
                flags = json.loads(e["flags"] or "[]")
                w.writerow([
                    e["id"], e["risk_score"], " | ".join(stypes), " | ".join(flags)
                ])
        zf.writestr("risk_flags.csv", risk_io.getvalue())

        # 8. ingestion_summary.json
        summary = {
            "system": "Receipt Graveyard",
            "version": "v2026.1",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_expenses": len(expenses),
            "total_employees": len(users),
            "approved_claims": sum(1 for e in expenses if e["status"] in ("Approved", "AUTO_APPROVED")),
            "pending_claims": sum(1 for e in expenses if e["status"] in ("Needs Review", "Needs Info", "PENDING_ACCOUNTS_REVIEW", "ADDITIONAL_INFORMATION_REQUESTED")),
            "rejected_claims": sum(1 for e in expenses if e["status"] in ("Rejected", "Duplicate")),
            "reimbursed_claims": sum(1 for e in expenses if e["status"] == "REIMBURSED"),
            "total_gross_claimed": sum(float(e["amount_inr"] or 0) for e in expenses if e["status"] != "Duplicate"),
            "total_approved_net": sum(float(e["reimbursable"] or 0) for e in expenses if e["status"] in ("Approved", "AUTO_APPROVED", "REIMBURSED")),
            "dataset_files": [
                "employees.csv", "expenses.csv", "receipts.csv", "expense_items.csv",
                "policy_evaluations.csv", "duplicate_candidates.csv", "risk_flags.csv",
                "ingestion_summary.json"
            ]
        }
        zf.writestr("ingestion_summary.json", json.dumps(summary, indent=2))

    zip_buffer.seek(0)
    return zip_buffer
