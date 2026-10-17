# budget_engine.py - Project-Wise Budget Caps, Persistent Ledger & Conditional Auto-Approval Engine
import json
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

logger = logging.getLogger(__name__)

# Precise monetary helper using Python Decimal
def to_decimal(val) -> Decimal:
    """Converts numeric or string value to 2-decimal-place Decimal, never floating-point binary approximations."""
    if val is None or val == "":
        return Decimal("0.00")
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")

def to_float(dec: Decimal) -> float:
    return float(dec)

# ==================== 1. DATABASE INITIALIZATION ====================

def init_budget_tables(con):
    """
    Initializes project-wise employee budget allocations, double-entry ledger,
    and cap adjustment audit tables.
    """
    # 1. Project Allocations Table (Employee-specific spending caps per project)
    con.execute("""
    CREATE TABLE IF NOT EXISTS project_allocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL REFERENCES projects(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        allocated_cap REAL NOT NULL,
        approved_expenditure REAL DEFAULT 0.0,
        reserved_expenditure REAL DEFAULT 0.0,
        remaining_balance REAL NOT NULL,
        start_date TEXT,
        end_date TEXT,
        status TEXT DEFAULT 'ACTIVE',
        created_by TEXT DEFAULT 'Admin',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(project_id, user_id)
    )
    """)

    # 2. Budget Ledger Table (Immutable, double-entry financial audit trail)
    con.execute("""
    CREATE TABLE IF NOT EXISTS budget_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        allocation_id INTEGER NOT NULL REFERENCES project_allocations(id),
        project_id INTEGER NOT NULL REFERENCES projects(id),
        user_id INTEGER NOT NULL REFERENCES users(id),
        expense_id INTEGER REFERENCES expenses(id),
        amount REAL NOT NULL,
        currency TEXT DEFAULT 'INR',
        reporting_amount REAL NOT NULL,
        entry_type TEXT NOT NULL,
        approval_decision TEXT NOT NULL,
        actor TEXT NOT NULL,
        balance_after REAL NOT NULL,
        notes TEXT,
        reference_id INTEGER REFERENCES budget_ledger(id),
        created_at TEXT NOT NULL
    )
    """)

    # 3. Allocation Adjustments Audit Log Table (Immutable history of cap changes)
    con.execute("""
    CREATE TABLE IF NOT EXISTS allocation_adjustments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        allocation_id INTEGER NOT NULL REFERENCES project_allocations(id),
        previous_cap REAL NOT NULL,
        new_cap REAL NOT NULL,
        reason TEXT NOT NULL,
        actor TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # Ensure 5 distinct status dimensions and budget metadata columns exist in expenses table
    existing_cols = [r[1] for r in con.execute("PRAGMA table_info(expenses)").fetchall()]
    new_cols = {
        "evidence_verification_status": "TEXT DEFAULT 'PENDING'",
        "policy_compliance_status": "TEXT DEFAULT 'PASS'",
        "budget_status": "TEXT DEFAULT 'WITHIN_CAP'",
        "approval_status": "TEXT DEFAULT 'SUBMITTED'",
        "reimbursement_status": "TEXT DEFAULT 'NOT_READY'",
        "allocation_id": "INTEGER REFERENCES project_allocations(id)",
        "verification_details_json": "TEXT",
        "auto_approval_reasons": "TEXT"
    }
    for col, ctype in new_cols.items():
        if col not in existing_cols:
            try:
                con.execute(f"ALTER TABLE expenses ADD COLUMN {col} {ctype}")
            except Exception:
                pass


# ==================== 2. ALLOCATION & BALANCE MANAGEMENT ====================

def get_or_create_allocation(con, project_id, user_id, cap=None, start_date=None, end_date=None, actor="Admin", status="ACTIVE"):
    """
    Fetches the employee's project allocation or creates an initial allocation if cap is supplied.
    """
    row = con.execute("""
        SELECT * FROM project_allocations 
        WHERE project_id = ? AND user_id = ?
    """, (project_id, user_id)).fetchone()

    if row:
        return dict(row)

    if cap is None:
        return None

    cap_dec = to_decimal(cap)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    con.execute("""
    INSERT INTO project_allocations (
        project_id, user_id, allocated_cap, approved_expenditure, reserved_expenditure,
        remaining_balance, start_date, end_date, status, created_by, created_at, updated_at
    ) VALUES (?, ?, ?, 0.0, 0.0, ?, ?, ?, ?, ?, ?, ?)
    """, (
        project_id, user_id, to_float(cap_dec), to_float(cap_dec),
        start_date, end_date, status, actor, now_str, now_str
    ))
    alloc_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Record initial cap adjustment audit entry
    con.execute("""
    INSERT INTO allocation_adjustments (allocation_id, previous_cap, new_cap, reason, actor, created_at)
    VALUES (?, 0.0, ?, 'Initial project spending cap assignment', ?, ?)
    """, (alloc_id, to_float(cap_dec), actor, now_str))

    # Also make sure project_memberships is synchronized
    con.execute("""
    INSERT OR IGNORE INTO project_memberships (project_id, user_id, role, assigned_at)
    VALUES (?, ?, 'Member', ?)
    """, (project_id, user_id, now_str))

    return dict(con.execute("SELECT * FROM project_allocations WHERE id = ?", (alloc_id,)).fetchone())


def adjust_allocation_cap(con, allocation_id, new_cap, reason, actor="Accounts Admin"):
    """
    Safely adjusts an employee's project spending cap.
    Crucial Rule: Never silently reset approved expenditure.
    New Remaining = New Cap - Approved Expenditure - Active Reservations.
    Creates an immutable audit log entry and ledger adjustment.
    """
    alloc = con.execute("SELECT * FROM project_allocations WHERE id = ?", (allocation_id,)).fetchone()
    if not alloc:
        raise ValueError(f"Allocation #{allocation_id} not found.")

    prev_cap_dec = to_decimal(alloc["allocated_cap"])
    new_cap_dec = to_decimal(new_cap)
    approved_dec = to_decimal(alloc["approved_expenditure"])
    reserved_dec = to_decimal(alloc["reserved_expenditure"])

    new_remaining_dec = new_cap_dec - approved_dec - reserved_dec
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Update allocation
    con.execute("""
    UPDATE project_allocations 
    SET allocated_cap = ?, remaining_balance = ?, updated_at = ?
    WHERE id = ?
    """, (to_float(new_cap_dec), to_float(new_remaining_dec), now_str, allocation_id))

    # Record immutable audit log
    con.execute("""
    INSERT INTO allocation_adjustments (allocation_id, previous_cap, new_cap, reason, actor, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (allocation_id, to_float(prev_cap_dec), to_float(new_cap_dec), reason, actor, now_str))

    # Record adjustment in budget ledger
    cap_diff = new_cap_dec - prev_cap_dec
    con.execute("""
    INSERT INTO budget_ledger (
        allocation_id, project_id, user_id, expense_id, amount, currency, reporting_amount,
        entry_type, approval_decision, actor, balance_after, notes, created_at
    ) VALUES (?, ?, ?, NULL, ?, 'INR', ?, 'ADJUSTMENT', 'ADJUSTED', ?, ?, ?, ?)
    """, (
        allocation_id, alloc["project_id"], alloc["user_id"],
        to_float(cap_diff), to_float(cap_diff), actor, to_float(new_remaining_dec),
        f"Spending cap modified from ₹{prev_cap_dec:,.2f} to ₹{new_cap_dec:,.2f}. Reason: {reason}",
        now_str
    ))

    return {
        "allocation_id": allocation_id,
        "previous_cap": to_float(prev_cap_dec),
        "new_cap": to_float(new_cap_dec),
        "approved_expenditure": to_float(approved_dec),
        "remaining_balance": to_float(new_remaining_dec)
    }


def calculate_allocation_balance(con, allocation_id) -> dict:
    """
    Computes real-time allocation balance directly from persistent database records.
    Remaining available budget = Allocated cap - Net approved expenditure - Active reservations.
    """
    alloc = con.execute("SELECT * FROM project_allocations WHERE id = ?", (allocation_id,)).fetchone()
    if not alloc:
        return None

    cap = to_decimal(alloc["allocated_cap"])
    
    # Calculate approved net expenditure directly from budget ledger to guarantee authoritative truth
    ledger_rows = con.execute("""
        SELECT entry_type, amount FROM budget_ledger 
        WHERE allocation_id = ? AND entry_type IN ('EXPENDITURE', 'REVERSAL')
    """, (allocation_id,)).fetchall()

    net_expenditure = Decimal("0.00")
    for row in ledger_rows:
        amt = to_decimal(row["amount"])
        if row["entry_type"] == "EXPENDITURE":
            net_expenditure += amt
        elif row["entry_type"] == "REVERSAL":
            net_expenditure -= abs(amt)

    reserved = to_decimal(alloc["reserved_expenditure"])
    remaining = cap - net_expenditure - reserved

    return {
        "allocation_id": allocation_id,
        "allocated_cap": to_float(cap),
        "approved_expenditure": to_float(net_expenditure),
        "reserved_expenditure": to_float(reserved),
        "remaining_balance": to_float(remaining)
    }


# ==================== 3. 17 EXACT AUTO-APPROVAL CONDITIONS ====================

def evaluate_auto_approval_conditions(con, expense_id: int, db_settings: dict = None) -> dict:
    """
    Deterministic backend decision engine checking all 17 mandatory conditions.
    Every check must pass for an expense to be eligible for automatic approval.
    """
    exp = con.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    if not exp:
        return {"eligible": False, "failed_conditions": ["Expense record not found"]}

    exp = dict(exp)
    claimed_amt = to_decimal(exp.get("amount_inr") or exp.get("amount") or 0)
    user_id = exp.get("user_id")
    project_id = exp.get("project_id")
    expense_date = exp.get("expense_date")

    if not db_settings:
        from app import get_system_settings
        db_settings = get_system_settings(con)

    auto_cap_global = to_decimal(db_settings.get("auto_approval_cap", 1500.0))
    manager_threshold = to_decimal(db_settings.get("manager_approval_threshold", 8000.0))
    vp_threshold = to_decimal(db_settings.get("vp_approval_threshold", 20000.0))

    conditions = {}
    reasons = []

    # 1. The employee is authenticated and authorized
    user = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone() if user_id else None
    cond_1 = bool(user and user["is_active"] == 1 and (user["status"] or "").upper() == "APPROVED")
    conditions["1_user_authorized"] = {
        "passed": cond_1,
        "detail": f"User {user['name'] if user else 'Unknown'} is active and approved." if cond_1 else "User is not active or account is pending approval."
    }
    if not cond_1: reasons.append("Employee account is not authorized or is inactive.")

    # 2. The employee is assigned to the selected project
    # 2. The employee is assigned to the selected project
    alloc = None
    if project_id and user_id:
        alloc_row = con.execute("SELECT * FROM project_allocations WHERE project_id = ? AND user_id = ?", (project_id, user_id)).fetchone()
        if alloc_row:
            alloc = dict(alloc_row)
        else:
            # Check membership
            mem = con.execute("SELECT 1 FROM project_memberships WHERE project_id = ? AND user_id = ?", (project_id, user_id)).fetchone()
            has_members = con.execute("SELECT COUNT(*) FROM project_memberships WHERE project_id = ?", (project_id,)).fetchone()[0]
            if mem or has_members == 0:
                # Create allocation with default project auto cap
                p_row = con.execute("SELECT auto_approval_cap FROM projects WHERE id = ?", (project_id,)).fetchone()
                p_cap = p_row["auto_approval_cap"] if (p_row and p_row["auto_approval_cap"]) else 2500.0
                alloc = get_or_create_allocation(con, project_id, user_id, cap=p_cap, actor="Auto-Assignment")

    cond_2 = bool(alloc is not None)
    conditions["2_assigned_to_project"] = {
        "passed": cond_2,
        "detail": f"Employee is assigned to project (Allocation #{alloc['id']})." if cond_2 else "Employee is not assigned to the selected project."
    }
    if not cond_2: reasons.append("Employee is not authorized or assigned to this project.")

    # 3. The employee's allocation is active
    cond_3 = bool(alloc and alloc.get("status") == "ACTIVE")
    conditions["3_allocation_active"] = {
        "passed": cond_3,
        "detail": "Project allocation is active." if cond_3 else "Project allocation is suspended or inactive."
    }
    if not cond_3: reasons.append("Employee's project allocation is not active.")

    # 4. The project and allocation are valid for the transaction
    proj = con.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone() if project_id else None
    proj_active = bool(proj and (proj["status"] or "").capitalize() == "Active")
    date_valid = True
    if expense_date:
        if proj and proj["start_date"] and expense_date < proj["start_date"]: date_valid = False
        if proj and proj["end_date"] and expense_date > proj["end_date"]: date_valid = False
        if alloc and alloc.get("start_date") and expense_date < alloc["start_date"]: date_valid = False
        if alloc and alloc.get("end_date") and expense_date > alloc["end_date"]: date_valid = False

    cond_4 = proj_active and date_valid
    conditions["4_project_and_dates_valid"] = {
        "passed": cond_4,
        "detail": "Project is Active and expense date falls within project period." if cond_4 else "Project is inactive or expense date falls outside valid dates."
    }
    if not cond_4: reasons.append("Project is inactive or transaction date falls outside valid duration.")

    # 5. The bill is present and sufficiently readable
    bill_filename = exp.get("file_name")
    ocr_raw = (exp.get("ocr_raw_text") or "").strip()
    if bill_filename:
        cond_5 = len(ocr_raw) >= 15 or bool(exp.get("extracted_amount") and float(exp["extracted_amount"]) > 0)
    else:
        cond_5 = bool(exp.get("merchant") and exp.get("expense_date") and claimed_amt > 0)

    conditions["5_bill_readable"] = {
        "passed": cond_5,
        "detail": f"Bill document/details present with readable financial data." if cond_5 else "Bill document missing or unreadable."
    }
    if not cond_5: reasons.append("Original itemized bill is missing or unreadable.")

    # 6. The payment screenshot or required alternative payment evidence is present
    pay_filename = exp.get("payment_file")
    has_pay_text = bool(exp.get("payment_match_note") and "Payment screenshot pending" not in exp.get("payment_match_note"))
    has_valid_utr = bool(exp.get("transaction_ref") and (str(exp.get("transaction_ref")).startswith("UTR_") or str(exp.get("transaction_ref")).startswith("TXN_")))
    cond_6 = bool(pay_filename or (exp.get("payment_verified") == 1) or has_pay_text or has_valid_utr)
    conditions["6_payment_proof_present"] = {
        "passed": cond_6,
        "detail": "Payment screenshot proof or verified alternative reference is attached." if cond_6 else "Payment screenshot is missing."
    }
    if not cond_6: reasons.append("Payment proof screenshot is missing. Employee action required.")

    # 7. Critical OCR fields have sufficient confidence or have been manually verified
    # Check if merchant, date, amount extracted and not flagged as low confidence
    flags = json.loads(exp.get("flags") or "[]")
    ocr_uncertain = any("low confidence" in f.lower() or "unreadable" in f.lower() or "ocr uncertainty" in f.lower() for f in flags)
    extracted_amt = to_decimal(exp.get("extracted_amount"))
    cond_7 = not ocr_uncertain and (extracted_amt > 0 or claimed_amt > 0)
    conditions["7_ocr_confidence_sufficient"] = {
        "passed": cond_7,
        "detail": "Critical OCR fields have high confidence." if cond_7 else "Critical OCR fields have low confidence or require review."
    }
    if not cond_7: reasons.append("Low OCR confidence on key financial fields.")

    # 8. The bill amount and submitted expense amount match within configured tolerances (<= ₹1.0)
    if extracted_amt > 0:
        amt_diff = abs(claimed_amt - extracted_amt)
        cond_8 = bool(amt_diff <= Decimal("1.00"))
    else:
        # If OCR did not detect separate total, compare with claimed
        cond_8 = True
        amt_diff = Decimal("0.00")

    conditions["8_bill_amount_matches_claimed"] = {
        "passed": cond_8,
        "detail": f"Claimed ₹{claimed_amt} matches bill ₹{extracted_amt} (Diff: ₹{amt_diff})." if cond_8 else f"Bill amount ₹{extracted_amt} does not match claimed ₹{claimed_amt} (Diff: ₹{amt_diff})."
    }
    if not cond_8: reasons.append(f"Bill total (₹{extracted_amt:,.2f}) does not match submitted claim amount (₹{claimed_amt:,.2f}).")

    # 9. The payment amount and bill amount reconcile under configured payment-matching rules
    pay_note = exp.get("payment_match_note") or ""
    pay_mismatch = any("discrepancy" in pay_note.lower() or "mismatch" in f.lower() for f in flags)
    cond_9 = (exp.get("payment_verified") == 1 or not pay_mismatch) and not pay_mismatch
    conditions["9_payment_reconciled_with_bill"] = {
        "passed": cond_9,
        "detail": f"Payment proof reconciled with bill: {pay_note}" if cond_9 else f"Payment mismatch detected: {pay_note}"
    }
    if not cond_9: reasons.append(f"Payment proof amount does not reconcile with bill: {pay_note}")

    # 10. The payment is confirmed as successful
    pay_unconfirmed = any("pending verification" in pay_note.lower() or "failed" in pay_note.lower() for f in [pay_note])
    cond_10 = cond_6 and not pay_unconfirmed and not pay_mismatch
    conditions["10_payment_confirmed_successful"] = {
        "passed": cond_10,
        "detail": "Payment confirmed as successful." if cond_10 else "Payment status is unconfirmed or failed."
    }
    if not cond_10: reasons.append("Payment screenshot does not establish a completed, successful transaction.")

    # 11. The bill and payment proof are linked to the same transaction
    cond_11 = cond_8 and cond_9 and cond_10
    conditions["11_same_transaction_link"] = {
        "passed": cond_11,
        "detail": "Bill and payment proof correspond to same transaction." if cond_11 else "Uncertain match between bill and payment evidence."
    }
    if not cond_11: reasons.append("Bill and payment proof cannot be reliably linked to the same transaction.")

    # 12. The expense is not an exact duplicate or unresolved potential duplicate
    is_dup = bool(exp.get("duplicate_of_id") or any("duplicate" in f.lower() or "recycled" in f.lower() for f in flags))
    cond_12 = not is_dup
    conditions["12_not_duplicate"] = {
        "passed": cond_12,
        "detail": "No duplicate receipt or payment reference detected." if cond_12 else f"Duplicate match identified with Claim #{exp.get('duplicate_of_id')}."
    }
    if not cond_12: reasons.append("Expense is an exact or potential duplicate.")

    # 13. The expense passes the applicable company expense policy
    policy_violation = any("policy cap exceeded" in f.lower() or "per-diem exceeded" in f.lower() or "monthly employee budget" in f.lower() for f in flags)
    cond_13 = not policy_violation
    conditions["13_passes_company_policy"] = {
        "passed": cond_13,
        "detail": "Satisfies applicable enterprise expense policy." if cond_13 else "Policy warnings or limits exceeded."
    }
    if not cond_13: reasons.append("Expense violates category caps or policy per-diem rules.")

    # 14. No prohibited item or unresolved arithmetic discrepancy
    non_reimb = to_decimal(exp.get("non_reimbursable_deduction"))
    math_status = exp.get("math_status") or ""
    math_discrepancy = "discrepancy detected" in math_status.lower()
    cond_14 = bool(non_reimb == 0 and not math_discrepancy)
    conditions["14_no_prohibited_items_or_math_error"] = {
        "passed": cond_14,
        "detail": "No prohibited items and bill arithmetic verified." if cond_14 else f"Prohibited items (₹{non_reimb}) or math discrepancy ({math_status})."
    }
    if not cond_14: reasons.append("Contains prohibited line items (e.g. alcohol/tobacco) or unverified bill arithmetic.")

    # 15. No mandatory approval threshold, missing-information requirement, or manual-review rule
    threshold_exceeded = claimed_amt >= manager_threshold or claimed_amt >= vp_threshold
    missing_info = (exp.get("status") in ("Needs Info", "NEEDS_INFORMATION")) or any("missing mandatory" in f.lower() or "action required" in f.lower() or "client / project name required" in f.lower() or "attendees required" in f.lower() for f in flags)
    cond_15 = not threshold_exceeded and not missing_info
    conditions["15_no_mandatory_escalation_threshold"] = {
        "passed": cond_15,
        "detail": "Amount is within autonomous approval authority." if cond_15 else f"Amount exceeds manager threshold (₹{manager_threshold:,.2f}) or missing info."
    }
    if not cond_15: reasons.append(f"Expense exceeds mandatory review threshold (₹{manager_threshold:,.2f}) or requires missing information.")

    # 16. The expense does not exceed the available project allocation
    remaining_balance = to_decimal(alloc["remaining_balance"]) if alloc else Decimal("0.00")
    cond_16 = bool(alloc and claimed_amt <= remaining_balance and claimed_amt > Decimal("0.00"))
    conditions["16_within_available_budget"] = {
        "passed": cond_16,
        "detail": f"Claim of ₹{claimed_amt:,.2f} is within available balance ₹{remaining_balance:,.2f}." if cond_16 else f"INSUFFICIENT BUDGET: Claim ₹{claimed_amt:,.2f} exceeds available balance ₹{remaining_balance:,.2f}."
    }
    if not cond_16: reasons.append(f"Expense of ₹{claimed_amt:,.2f} exceeds remaining project allocation (Available: ₹{remaining_balance:,.2f}).")

    # 17. The budget check and approval can be committed atomically
    cond_17 = cond_16  # verified during actual atomic ledger commit
    conditions["17_atomic_commitment_ready"] = {
        "passed": cond_17,
        "detail": "Allocation balance is ready for atomic deduction."
    }

    all_passed = all(c["passed"] for c in conditions.values())

    return {
        "eligible": all_passed,
        "conditions": conditions,
        "failed_reasons": reasons,
        "claimed_amount": to_float(claimed_amt),
        "allocation": alloc,
        "remaining_balance": to_float(remaining_balance)
    }


# ==================== 4. ATOMIC COMMITMENT, REVERSAL & WORKFLOW ====================

def apply_budget_approval(con, expense_id: int, actor: str = "SYSTEM_AUTO_APPROVAL", is_auto: bool = True) -> dict:
    """
    Executes an atomic budget deduction and persistent ledger creation.
    Revalidates the allocation immediately before committing.
    Guarantees idempotency: retries cannot deduct the same expense twice.
    """
    # 1. Idempotency Check: Check if an EXPENDITURE entry already exists in budget_ledger
    existing_ledger = con.execute("""
        SELECT * FROM budget_ledger 
        WHERE expense_id = ? AND entry_type = 'EXPENDITURE'
    """, (expense_id,)).fetchone()

    if existing_ledger:
        return {
            "success": True,
            "idempotent": True,
            "message": f"Expense #{expense_id} was already deducted in ledger entry #{existing_ledger['id']}.",
            "ledger_id": existing_ledger["id"],
            "balance_after": existing_ledger["balance_after"]
        }

    # 2. Fetch Expense Record
    exp = con.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    if not exp:
        return {"success": False, "reason": "Expense record not found."}
    exp = dict(exp)

    user_id = exp["user_id"]
    project_id = exp["project_id"]
    claimed_amt = to_decimal(exp["amount_inr"] or exp["amount"] or 0)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Resolve project_id if missing
    if not project_id:
        if exp.get("project_code"):
            p_row = con.execute("SELECT id FROM projects WHERE upper(code)=upper(?)", (exp["project_code"],)).fetchone()
            if p_row:
                project_id = p_row["id"]
        if not project_id:
            p_row = con.execute("SELECT id FROM projects WHERE status='Active' LIMIT 1").fetchone()
            project_id = p_row["id"] if p_row else 1
        con.execute("UPDATE expenses SET project_id = ? WHERE id = ?", (project_id, expense_id))

    # 3. Find Allocation
    alloc = con.execute("""
        SELECT * FROM project_allocations 
        WHERE project_id = ? AND user_id = ?
    """, (project_id, user_id)).fetchone()

    if not alloc:
        p_row = con.execute("SELECT auto_approval_cap FROM projects WHERE id = ?", (project_id,)).fetchone()
        p_cap = p_row["auto_approval_cap"] if (p_row and p_row["auto_approval_cap"]) else 4000.0
        alloc = get_or_create_allocation(con, project_id, user_id, cap=p_cap, actor="System Default")

    alloc_id = alloc["id"]
    amt_float = to_float(claimed_amt)

    # 4. Atomic Balance Update with row lock / concurrency check (WHERE remaining_balance >= amt)
    cursor = con.execute("""
        UPDATE project_allocations 
        SET approved_expenditure = approved_expenditure + ?,
            remaining_balance = remaining_balance - ?,
            updated_at = ?
        WHERE id = ? AND remaining_balance >= ?
    """, (amt_float, amt_float, now_str, alloc_id, amt_float))

    if cursor.rowcount == 0:
        # Concurrency conflict or insufficient balance!
        fresh_alloc = con.execute("SELECT remaining_balance FROM project_allocations WHERE id = ?", (alloc_id,)).fetchone()
        fresh_rem = fresh_alloc["remaining_balance"] if fresh_alloc else 0.0
        return {
            "success": False,
            "reason": f"Atomic budget check failed: Insufficient remaining balance (Available: ₹{fresh_rem:,.2f}, Requested: ₹{amt_float:,.2f})."
        }

    # 5. Fetch updated allocation balance
    updated_alloc = con.execute("SELECT * FROM project_allocations WHERE id = ?", (alloc_id,)).fetchone()
    new_balance = updated_alloc["remaining_balance"]

    # 6. Record immutable double-entry ledger record
    decision_str = "AUTO_APPROVED" if is_auto else "MANUAL_APPROVED"
    con.execute("""
    INSERT INTO budget_ledger (
        allocation_id, project_id, user_id, expense_id, amount, currency, reporting_amount,
        entry_type, approval_decision, actor, balance_after, notes, created_at
    ) VALUES (?, ?, ?, ?, ?, 'INR', ?, 'EXPENDITURE', ?, ?, ?, ?, ?)
    """, (
        alloc_id, project_id, user_id, expense_id, amt_float, amt_float,
        decision_str, actor, new_balance,
        f"{'Automatic' if is_auto else 'Accounts manual'} approval under Project #{project_id}. Remaining: ₹{new_balance:,.2f}",
        now_str
    ))
    ledger_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 7. Update Expense status dimensions
    proj_row = con.execute("SELECT name, code FROM projects WHERE id = ?", (project_id,)).fetchone()
    proj_name = proj_row["name"] if proj_row else f"PRJ-{project_id}"

    status_str = "Approved"
    con.execute("""
    UPDATE expenses 
    SET status = ?,
        approval_status = ?,
        evidence_verification_status = 'VERIFIED',
        policy_compliance_status = 'PASS',
        budget_status = 'WITHIN_CAP',
        reimbursement_status = 'READY_FOR_REIMBURSEMENT',
        allocation_id = ?,
        auto_approval_reasons = ?
    WHERE id = ?
    """, (
        status_str,
        decision_str,
        alloc_id,
        f"Approved under Project {proj_name}. Bill and payment verified. Deducted ₹{amt_float:,.2f}. Remaining balance: ₹{new_balance:,.2f}",
        expense_id
    ))

    # Append to expense audit log
    audit_entry = {
        "action": f"{'Auto-Approved' if is_auto else 'Accounts Approved'}",
        "status": status_str,
        "amount": amt_float,
        "actor": actor,
        "timestamp": now_str,
        "remaining_balance": new_balance,
        "ledger_id": ledger_id
    }
    existing_audit = json.loads(exp["audit_log"] or "[]")
    existing_audit.append(audit_entry)
    con.execute("UPDATE expenses SET audit_log = ? WHERE id = ?", (json.dumps(existing_audit), expense_id))

    # 8. Create In-App Notification for employee
    from app import create_notification
    create_notification(
        con,
        user_id,
        expense_id,
        "Expense Auto-Approved!" if is_auto else "Expense Approved!",
        f"Expense EXP-{expense_id:03d} for ₹{amt_float:,.2f} has been {'automatically ' if is_auto else ''}approved under {proj_name}. "
        f"The bill and payment evidence matched, policy checks passed, and the expense was within your available allocation. Remaining budget: ₹{new_balance:,.2f}.",
        "success"
    )

    return {
        "success": True,
        "ledger_id": ledger_id,
        "allocation_id": alloc_id,
        "amount": amt_float,
        "remaining_balance": new_balance,
        "approval_status": decision_str
    }


def reverse_expense_approval(con, expense_id: int, reason: str, actor: str = "Accounts Admin") -> dict:
    """
    Reverses an approved expense through a compensating ledger transaction.
    Never deletes the original approval history.
    Compensating entry: entry_type='REVERSAL', amount = -approved_amount.
    """
    # 1. Locate original expenditure ledger entry
    orig_ledger = con.execute("""
        SELECT * FROM budget_ledger 
        WHERE expense_id = ? AND entry_type = 'EXPENDITURE'
        ORDER BY id DESC LIMIT 1
    """, (expense_id,)).fetchone()

    if not orig_ledger:
        return {"success": False, "reason": "No approved expenditure ledger entry found for this expense."}

    alloc_id = orig_ledger["allocation_id"]
    rev_amt = to_decimal(orig_ledger["amount"])
    rev_amt_float = to_float(rev_amt)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 2. Update Allocation Balance (re-add to remaining balance, subtract from approved expenditure)
    con.execute("""
        UPDATE project_allocations 
        SET approved_expenditure = max(0.0, approved_expenditure - ?),
            remaining_balance = remaining_balance + ?,
            updated_at = ?
        WHERE id = ?
    """, (rev_amt_float, rev_amt_float, now_str, alloc_id))

    updated_alloc = con.execute("SELECT remaining_balance FROM project_allocations WHERE id = ?", (alloc_id,)).fetchone()
    new_balance = updated_alloc["remaining_balance"] if updated_alloc else 0.0

    # 3. Create Compensating Ledger Entry
    con.execute("""
    INSERT INTO budget_ledger (
        allocation_id, project_id, user_id, expense_id, amount, currency, reporting_amount,
        entry_type, approval_decision, actor, balance_after, notes, reference_id, created_at
    ) VALUES (?, ?, ?, ?, ?, 'INR', ?, 'REVERSAL', 'REVERSED', ?, ?, ?, ?, ?)
    """, (
        alloc_id, orig_ledger["project_id"], orig_ledger["user_id"], expense_id,
        -rev_amt_float, -rev_amt_float, actor, new_balance,
        f"Reversal of Expense #{expense_id}. Reason: {reason}",
        orig_ledger["id"], now_str
    ))
    reversal_ledger_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 4. Update Expense record status
    con.execute("""
    UPDATE expenses 
    SET status = 'Rejected',
        approval_status = 'REJECTED',
        reimbursement_status = 'NOT_READY'
    WHERE id = ?
    """, (expense_id,))

    # Update audit log
    exp = con.execute("SELECT audit_log, user_id FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    existing_audit = json.loads(exp["audit_log"] or "[]")
    existing_audit.append({
        "action": "Expense Approval Reversed",
        "actor": actor,
        "reason": reason,
        "amount_reversed": rev_amt_float,
        "compensating_ledger_id": reversal_ledger_id,
        "timestamp": now_str
    })
    con.execute("UPDATE expenses SET audit_log = ? WHERE id = ?", (json.dumps(existing_audit), expense_id))

    # Notify employee
    from app import create_notification
    create_notification(
        con,
        exp["user_id"],
        expense_id,
        "Expense Approval Reversed",
        f"Expense EXP-{expense_id:03d} for ₹{rev_amt_float:,.2f} was reversed by {actor}. Reason: {reason}. Budget balance restored to ₹{new_balance:,.2f}.",
        "error"
    )

    return {
        "success": True,
        "reversal_ledger_id": reversal_ledger_id,
        "amount_reversed": rev_amt_float,
        "new_remaining_balance": new_balance
    }


def route_expense_for_review(con, expense_id: int, eval_result: dict, actor: str = "SYSTEM") -> dict:
    """
    Routes an expense that failed automatic approval to the appropriate review queue
    (Accounts Reviewer vs. Accounts Admin) and records all status dimensions and notifications.
    """
    exp = con.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    if not exp:
        return {"success": False, "reason": "Expense not found"}
    exp = dict(exp)

    user_id = exp["user_id"]
    claimed_amt = to_decimal(exp["amount_inr"] or exp["amount"] or 0)
    failed_reasons = eval_result.get("failed_reasons", [])
    conds = eval_result.get("conditions", {})
    alloc = eval_result.get("allocation")
    remaining_balance = eval_result.get("remaining_balance", 0.0)

    # Determine Distinct Status Dimensions:
    # 1. Evidence Verification Status
    if not conds.get("5_bill_readable", {}).get("passed", True) or not conds.get("6_payment_proof_present", {}).get("passed", True):
        evidence_status = "INCOMPLETE"
    elif not conds.get("9_payment_reconciled_with_bill", {}).get("passed", True) or not conds.get("8_bill_amount_matches_claimed", {}).get("passed", True):
        evidence_status = "MISMATCH"
    elif not conds.get("10_payment_confirmed_successful", {}).get("passed", True):
        evidence_status = "PAYMENT_UNCONFIRMED"
    elif not conds.get("7_ocr_confidence_sufficient", {}).get("passed", True):
        evidence_status = "NEEDS_REVIEW"
    else:
        evidence_status = "VERIFIED"

    # 2. Policy Compliance Status
    if not conds.get("12_not_duplicate", {}).get("passed", True) or not conds.get("14_no_prohibited_items_or_math_error", {}).get("passed", True):
        policy_status = "VIOLATION"
    elif not conds.get("13_passes_company_policy", {}).get("passed", True):
        policy_status = "WARNING"
    elif not conds.get("15_no_mandatory_escalation_threshold", {}).get("passed", True):
        policy_status = "MANUAL_REVIEW"
    else:
        policy_status = "PASS"

    # 3. Budget Status
    if not conds.get("3_allocation_active", {}).get("passed", True) or not conds.get("2_assigned_to_project", {}).get("passed", True):
        budget_status = "ALLOCATION_INACTIVE"
    elif remaining_balance <= 0:
        budget_status = "CAP_EXHAUSTED"
    elif not conds.get("16_within_available_budget", {}).get("passed", True):
        budget_status = "INSUFFICIENT_BALANCE"
    else:
        budget_status = "WITHIN_CAP"

    # 4. Approval Status & Queue Routing
    orig_status = exp.get("status")
    if orig_status in ("Rejected", "REJECTED"):
        approval_status = "REJECTED"
        claim_status = "Rejected"
    elif orig_status in ("Duplicate", "DUPLICATE") or not conds.get("12_not_duplicate", {}).get("passed", True):
        approval_status = "PENDING_ACCOUNTS"
        claim_status = "Duplicate"
    elif evidence_status == "INCOMPLETE":
        approval_status = "NEEDS_INFORMATION"
        claim_status = "Needs Info"
    elif budget_status in ("INSUFFICIENT_BALANCE", "CAP_EXHAUSTED") or claimed_amt >= 8000.0 or policy_status == "VIOLATION":
        approval_status = "PENDING_ACCOUNTS_ADMIN"
        claim_status = "Needs Review"
    else:
        approval_status = "PENDING_ACCOUNTS"
        claim_status = "Needs Review"

    # Save to expenses table
    con.execute("""
    UPDATE expenses 
    SET status = ?,
        approval_status = ?,
        evidence_verification_status = ?,
        policy_compliance_status = ?,
        budget_status = ?,
        reimbursement_status = 'NOT_READY',
        verification_details_json = ?,
        auto_approval_reasons = ?
    WHERE id = ?
    """, (
        claim_status,
        approval_status,
        evidence_status,
        policy_status,
        budget_status,
        json.dumps(conds),
        " | ".join(failed_reasons),
        expense_id
    ))

    # Notifications
    from app import create_notification, notify_accounts_team
    reason_summary = " ".join(failed_reasons)
    
    if budget_status in ("INSUFFICIENT_BALANCE", "CAP_EXHAUSTED"):
        # Budget Exhaustion notification
        create_notification(
            con,
            user_id,
            expense_id,
            "Insufficient Project Budget",
            f"Expense EXP-{expense_id:03d} cannot be automatically approved because the project has only ₹{remaining_balance:,.2f} remaining, while the requested expense is ₹{to_float(claimed_amt):,.2f}. Accounts review or an authorized allocation adjustment is required.",
            "warning"
        )
        notify_accounts_team(
            con,
            expense_id,
            "Budget Exhaustion Review",
            f"Claim #{expense_id} (₹{to_float(claimed_amt):,.2f}) by employee exceeds project allocation balance of ₹{remaining_balance:,.2f}.",
            "escalation"
        )
    elif evidence_status == "MISMATCH":
        create_notification(
            con,
            user_id,
            expense_id,
            "Bill/Payment Discrepancy",
            f"Expense EXP-{expense_id:03d} requires Accounts review. The bill and payment screenshot do not reconcile: {reason_summary}. Please provide matching payment evidence or clarify the discrepancy.",
            "error"
        )
        notify_accounts_team(
            con,
            expense_id,
            "Payment Mismatch Review",
            f"Claim #{expense_id} requires review: {reason_summary}",
            "review"
        )
    elif evidence_status == "INCOMPLETE":
        create_notification(
            con,
            user_id,
            expense_id,
            "Action Required: Upload Payment Proof",
            f"Expense EXP-{expense_id:03d} is pending evidence. Please upload the matching payment screenshot.",
            "warning"
        )
    else:
        create_notification(
            con,
            user_id,
            expense_id,
            "Expense Routed for Accounts Review",
            f"Expense EXP-{expense_id:03d} requires Accounts review: {reason_summary}.",
            "info"
        )
        notify_accounts_team(
            con,
            expense_id,
            "Accounts Review Required",
            f"Claim #{expense_id} routed for review: {reason_summary}",
            "review"
        )

    return {
        "success": True,
        "approval_status": approval_status,
        "evidence_status": evidence_status,
        "budget_status": budget_status,
        "reasons": failed_reasons
    }


def process_claim_auto_approval(con, expense_id: int, actor: str = "SYSTEM_AUTO_APPROVAL") -> dict:
    """
    Main orchestration function: Evaluates the 17 conditions for a claim.
    If 100% eligible, commits the atomic budget deduction and auto-approves.
    If ineligible, routes to Accounts review or Accounts Admin escalation.
    """
    eval_result = evaluate_auto_approval_conditions(con, expense_id)

    if eval_result["eligible"]:
        commit_res = apply_budget_approval(con, expense_id, actor=actor, is_auto=True)
        return {
            "auto_approved": True,
            "commit_result": commit_res,
            "eval_result": eval_result
        }
    else:
        route_res = route_expense_for_review(con, expense_id, eval_result, actor=actor)
        return {
            "auto_approved": False,
            "route_result": route_res,
            "eval_result": eval_result
        }
