# fraud_engine.py - Multi-Vector Duplicate, Anomaly, Collusion & Smurfing Detection Engine

import json
from datetime import datetime
from ocr_engine import hamming_distance
from policy import POLICY

def audit_claim_integrity(data, con, file_hash=None, perceptual_hash=None, extracted_data=None, exclude_id=None):
    """
    Performs comprehensive fraud, duplicate, collusion, and anomaly checks across all submitted claims.
    Returns:
    - risk_score: int (0 to 100)
    - flags: list of str
    - suspicion_types: list of str
    - duplicate_of_id: int or None
    """
    flags = []
    suspicion_types = []
    risk_score = 0
    duplicate_of_id = None

    employee = (data.get("employee") or "").strip()
    expense_date = data.get("expense_date")
    merchant = (data.get("merchant") or "").strip()
    amount_inr = float(data.get("amount_inr") or 0)
    category = data.get("category") or "Other"
    city = data.get("city") or "Other"
    is_trip = bool(data.get("is_trip", False))

    # --- Vector 1: Exact File Hash Duplicate (SHA-256) ---
    if file_hash and con:
        q = "SELECT id, employee, submitted_at, source, status FROM expenses WHERE file_hash = ?"
        args = [file_hash]
        if exclude_id:
            q += " AND id != ?"
            args.append(exclude_id)
        match = con.execute(q, args).fetchone()
        if match:
            duplicate_of_id = match["id"]
            if match["employee"] == employee:
                flags.append(f"Exact duplicate receipt detected: matches your prior expense #{match['id']} (submitted via {match['source']})")
                suspicion_types.append("Exact File Duplicate")
            else:
                flags.append(f"COLLUSION ALERT: Receipt matches identical file previously submitted by {match['employee']} (#{match['id']})")
                suspicion_types.append("Cross-Employee Collusion")
            risk_score = max(risk_score, 95)

    # --- Vector 2: Perceptual Image Duplicate (dHash) ---
    if perceptual_hash and con and not duplicate_of_id:
        q = "SELECT id, employee, perceptual_hash, source FROM expenses WHERE perceptual_hash IS NOT NULL"
        args = []
        if exclude_id:
            q += " AND id != ?"
            args.append(exclude_id)
        candidates = con.execute(q, args).fetchall()
        for cand in candidates:
            dist = hamming_distance(perceptual_hash, cand["perceptual_hash"])
            if dist <= 5:  # Close perceptual similarity (re-scanned, cropped, or angle shift)
                duplicate_of_id = cand["id"]
                if cand["employee"] == employee:
                    flags.append(f"Visual duplicate detected: receipt image matches expense #{cand['id']} (visual diff: {dist}/64 bits)")
                    suspicion_types.append("Perceptual Duplicate")
                else:
                    flags.append(f"COLLUSION ALERT: Receipt image is visually identical to claim #{cand['id']} by {cand['employee']} (diff: {dist}/64)")
                    suspicion_types.append("Cross-Employee Collusion")
                risk_score = max(risk_score, 90)
                break

    # --- Vector 3: Semantic Duplicate (Same Date + Merchant + Amount) ---
    if con and merchant and expense_date and amount_inr > 0 and not duplicate_of_id:
        # Check within +/- 2% amount tolerance on same date and same merchant
        q = """
        SELECT id, employee, amount_inr, status 
        FROM expenses 
        WHERE expense_date = ? 
        AND lower(merchant) = lower(?)
        AND status != 'Duplicate'
        """
        args = [expense_date, merchant]
        if exclude_id:
            q += " AND id != ?"
            args.append(exclude_id)
        same_merchant_rows = con.execute(q, args).fetchall()
        for r in same_merchant_rows:
            other_amt = float(r["amount_inr"] or 0)
            if abs(other_amt - amount_inr) <= max(1.0, 0.02 * amount_inr):
                duplicate_of_id = r["id"]
                if r["employee"] == employee:
                    flags.append(f"Semantic duplicate: You already claimed ₹{other_amt:,.2f} at {merchant} on {expense_date} (expense #{r['id']})")
                    suspicion_types.append("Semantic Duplicate")
                    risk_score = max(risk_score, 85)
                else:
                    flags.append(f"Potential double-claim: {r['employee']} also claimed ₹{other_amt:,.2f} at {merchant} on {expense_date} (expense #{r['id']})")
                    suspicion_types.append("Cross-Employee Semantic Duplicate")
                    risk_score = max(risk_score, 75)
                break

    # --- Vector 4: Anti-Smurfing / Split Transaction Detection ---
    if con and employee and expense_date and merchant and amount_inr > 0:
        # Look for multiple claims on same day at same merchant
        q = """
        SELECT id, amount_inr, client_name 
        FROM expenses 
        WHERE employee = ? 
        AND expense_date = ? 
        AND lower(merchant) = lower(?)
        AND status != 'Duplicate'
        """
        args = [employee, expense_date, merchant]
        if exclude_id:
            q += " AND id != ?"
            args.append(exclude_id)
        prior_same_day = con.execute(q, args).fetchall()
        if prior_same_day:
            combined_spend = sum(float(x["amount_inr"] or 0) for x in prior_same_day) + amount_inr
            # Check if each transaction sits just below meal client threshold (e.g., ₹1,200)
            threshold = POLICY.get("meal_rules", {}).get("client_name_required_above", 1200)
            if combined_spend > threshold and amount_inr < threshold and any(float(x["amount_inr"]) < threshold for x in prior_same_day):
                flags.append(f"Split-transaction pattern: {len(prior_same_day)+1} claims at {merchant} on {expense_date} total ₹{combined_spend:,.2f}, appearing to avoid the ₹{threshold:,.0f} client detail rule")
                suspicion_types.append("Split Transaction / Smurfing")
                risk_score += 40

    # --- Vector 5: Claim Inflation Discrepancy ---
    if extracted_data and extracted_data.get("extracted_total"):
        ext_tot = float(extracted_data["extracted_total"])
        # If currency rate was applied, compare in original currency
        claimed_orig = float(data.get("amount") or 0)
        if ext_tot > 0 and claimed_orig > ext_tot * 1.05 and (claimed_orig - ext_tot) > 50:
            diff = claimed_orig - ext_tot
            flags.append(f"Claim inflation discrepancy: Claimed {claimed_orig:,.2f} exceeds receipt OCR total of {ext_tot:,.2f} by {diff:,.2f}")
            suspicion_types.append("Claim Inflation")
            risk_score += 45

    # --- Vector 6: Math Discrepancy Detection ---
    if extracted_data and "Discrepancy Detected" in extracted_data.get("math_status", ""):
        flags.append(f"Receipt math error: {extracted_data['math_status']}")
        suspicion_types.append("Receipt Math Mismatch")
        risk_score += 25

    # --- Vector 7: Date & Temporal Anomalies ---
    if expense_date:
        try:
            exp_dt = datetime.strptime(expense_date, "%Y-%m-%d").date()
            today = datetime.now().date()
            if exp_dt > today:
                flags.append(f"Future date anomaly: Expense date ({expense_date}) is in the future")
                suspicion_types.append("Future Expense Date")
                risk_score += 35
            else:
                age_days = (today - exp_dt).days
                max_age = POLICY.get("max_submission_age_days", 60)
                if age_days > max_age:
                    flags.append(f"Stale claim: Expense is {age_days} days old (exceeds {max_age}-day submission policy window)")
                    suspicion_types.append("Stale / Expired Submission")
                    risk_score += 20

            # Weekend anomaly check (Saturday=5, Sunday=6)
            if exp_dt.weekday() in (5, 6) and not is_trip:
                flags.append(f"Weekend expense on {exp_dt.strftime('%A')}: Requires trip context or manager overtime verification")
                suspicion_types.append("Weekend Non-Travel Expense")
                risk_score += 15
        except Exception:
            pass

    # --- Vector 8: Suspicious Round Number Bias ---
    if amount_inr >= 3000 and amount_inr % 1000 == 0 and not data.get("description"):
        flags.append("Round amount anomaly: High round amount (₹{:,.0f}) without itemized breakdown".format(amount_inr))
        suspicion_types.append("Round Number Anomaly")
        risk_score += 15

    # --- Vector 9: Recycled Payment UTR / Transaction Reference Fraud ---
    txn_ref = (data.get("transaction_ref") or "").strip()
    if con and txn_ref and len(txn_ref) >= 8:
        clean_ref = "".join(c for c in txn_ref if c.isalnum()).lower()
        if len(clean_ref) >= 8:
            q = "SELECT id, employee, expense_date, amount_inr FROM expenses WHERE transaction_ref IS NOT NULL AND lower(replace(replace(transaction_ref, ' ', ''), '-', '')) = ?"
            args = [clean_ref]
            if exclude_id:
                q += " AND id != ?"
                args.append(exclude_id)
            match_txn = con.execute(q, args).fetchone()
            if match_txn:
                if match_txn["employee"] == employee:
                    flags.append(f"RECYCLED PAYMENT PROOF: Transaction ref '{txn_ref}' was already claimed in expense #{match_txn['id']} (₹{float(match_txn['amount_inr'] or 0):,.2f})")
                    suspicion_types.append("Recycled Payment Reference")
                    risk_score = max(risk_score, 90)
                else:
                    flags.append(f"PAYMENT PROOF FRAUD: Transaction ref '{txn_ref}' was previously submitted by {match_txn['employee']} in #{match_txn['id']}")
                    suspicion_types.append("Cross-Employee Payment Proof Recycling")
                    risk_score = max(risk_score, 95)

    return {
        "risk_score": min(100, risk_score),
        "flags": flags,
        "suspicion_types": suspicion_types,
        "duplicate_of_id": duplicate_of_id
    }
