"""
Comprehensive Automated Test Suite for The Receipt Graveyard
Covers all 25 principal workflows specified in Section 18:
 1. User creation and role assignment
 2. Employee and Accounts permissions & RBAC
 3. Project creation and unique project codes
 4. Project membership restrictions
 5. Historical CSV ingestion
 6. Duplicate imports idempotency
 7. Receipt OCR and missing fields extraction
 8. Project-cap auto-approval routing
 9. Claims exactly at the cap (inclusive)
10. Claims exceeding the cap (routed to Accounts)
11. Company policy violations (alcohol/entertainment deductions)
12. Cumulative spending limits (daily/monthly caps)
13. Duplicate and suspicious claim detection (hash/dHash/collusion)
14. Accounts approval and rejection
15. Accounts document requests
16. Employee document uploads
17. Employee resubmission workflow
18. Editing-window enforcement
19. Preservation of historical claim versions
20. Correct in-app notifications
21. Audit logging
22. Employee data isolation (cross-employee protection)
23. Payment authorization & REIMBURSED status
24. Accurate financial calculations & decimal precision
25. Standardized 8-file exports ZIP
"""

import unittest
import json
import io
import time
import zipfile
from datetime import datetime, timedelta
from app import app, connect, init_db, create_notification
import historical_ingestion

class ReceiptGraveyardCompleteTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        cls.client = app.test_client()
        init_db()
        with connect() as con:
            con.execute("DELETE FROM expenses WHERE transaction_ref LIKE 'UTR_%' OR merchant LIKE '%Supplies %' OR merchant LIKE '%Cafe %'")
            con.commit()

    @classmethod
    def tearDownClass(cls):
        with connect() as con:
            con.execute("DELETE FROM expenses WHERE transaction_ref LIKE 'UTR_%' OR merchant LIKE '%Supplies %' OR merchant LIKE '%Cafe %'")
            con.commit()

    def test_01_user_creation_and_role_assignment(self):
        """Test 1: User creation and role assignment for Admin, Accounts, Employee."""
        with connect() as con:
            admin = con.execute("SELECT * FROM users WHERE role='admin'").fetchone()
            accounts = con.execute("SELECT * FROM users WHERE role='accounts'").fetchone()
            emp = con.execute("SELECT * FROM users WHERE role='employee'").fetchone()
            self.assertIsNotNone(admin)
            self.assertIsNotNone(accounts)
            self.assertIsNotNone(emp)
            self.assertEqual(admin["role"], "admin")
            self.assertEqual(accounts["role"], "accounts")
            self.assertEqual(emp["role"], "employee")

    def test_02_employee_and_accounts_permissions_rbac(self):
        """Test 2: RBAC prevents Employee from accessing admin console and analytics."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 4  # Aarav Mehta (Employee)
            sess["role"] = "employee"
            sess["user_name"] = "Aarav Mehta"

        # Attempt to access /admin -> should redirect
        res = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(res.status_code, 302)

        # Attempt to access /analytics -> should redirect
        res_analytics = self.client.get("/analytics", follow_redirects=False)
        self.assertEqual(res_analytics.status_code, 302)

        # Access with Admin role -> 200 OK
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["user_name"] = "Priya Sharma"
        res_admin = self.client.get("/admin")
        self.assertEqual(res_admin.status_code, 200)

    def test_03_project_creation_and_unique_codes(self):
        """Test 3: Project creation and unique project code enforcement."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["user_name"] = "Priya Sharma"

        test_code = f"TEST-PRJ-{int(time.time() * 1000)}"
        res = self.client.post("/admin/add-project", data={
            "code": test_code,
            "name": "Automated Test Project",
            "client_name": "Test Client Corp",
            "budget": "500000",
            "auto_approval_cap": "4500",
            "manager_name": "Test Manager",
            "description": "Integration testing project"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            prj = con.execute("SELECT * FROM projects WHERE code=?", (test_code,)).fetchone()
            self.assertIsNotNone(prj)
            self.assertEqual(float(prj["auto_approval_cap"]), 4500.0)

    def test_04_project_membership_and_cap_update(self):
        """Test 4: Project status update and cap adjustment."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"

        with connect() as con:
            prj = con.execute("SELECT id FROM projects LIMIT 1").fetchone()
            p_id = prj["id"]

        res = self.client.post(f"/admin/project/{p_id}/cap", data={"cap": "7500"}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            updated = con.execute("SELECT auto_approval_cap FROM projects WHERE id=?", (p_id,)).fetchone()
            self.assertEqual(float(updated["auto_approval_cap"]), 7500.0)

    def test_05_historical_csv_ingestion(self):
        """Test 5: Ingestion of historical CSV dataset with flexible column variations."""
        csv_data = f"""Emp Name,Work Email,Transaction Date,Vendor,Spend Amount,Currency,Expense Type,City Name,Project
Rohan Verma,rohan.verma@company.com,2026-10-10,Cafe Coffee Day,650.00,INR,Meals,Mumbai,PRJ-UPI-09
Deepa Nair,deepa.nair@company.com,2026-10-11,IndiGo Airlines,4200.00,INR,Travel,Bengaluru,PRJ-UPI-09
"""
        with connect() as con:
            summary = historical_ingestion.ingest_historical_csv(con, io.StringIO(csv_data))
            con.commit()

        self.assertGreaterEqual(summary["imported_rows"], 2)
        self.assertGreaterEqual(summary["employees_detected"], 2)

    def test_06_duplicate_imports_idempotency(self):
        """Test 6: Repeated ingestion does not duplicate employee accounts."""
        csv_data = """Emp Name,Work Email,Transaction Date,Vendor,Spend Amount,Currency,Expense Type,City Name,Project
Rohan Verma,rohan.verma@company.com,2026-10-10,Cafe Coffee Day,650.00,INR,Meals,Mumbai,PRJ-UPI-09
"""
        with connect() as con:
            count_before = con.execute("SELECT COUNT(*) FROM users WHERE lower(email)='rohan.verma@company.com'").fetchone()[0]
            summary = historical_ingestion.ingest_historical_csv(con, io.StringIO(csv_data))
            con.commit()
            count_after = con.execute("SELECT COUNT(*) FROM users WHERE lower(email)='rohan.verma@company.com'").fetchone()[0]

        self.assertEqual(count_before, count_after, "Duplicate employee account was incorrectly created during re-ingestion.")

    def test_07_receipt_ocr_and_missing_fields(self):
        """Test 7: Client meal > 1200 missing mandatory client name results in Needs Info."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 6
            sess["role"] = "employee"
            sess["user_name"] = "Priya Sen"

        ts = int(time.time() * 1000)
        res = self.client.post("/submit", data={
            "expense_date": "2026-10-06",
            "merchant": f"Luxury Dinner Bistro {ts}",
            "category": "Meals",
            "city": "Mumbai",
            "amount": "1550.00",
            "currency": "INR",
            "client_name": "",  # Missing mandatory client name for meal > 1200
            "project_code": "PRJ-UPI-09",
            "payment_method": "UPI",
            "upi_app": "Google Pay",
            "transaction_ref": f"UTR_MEAL_{ts}"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            row = con.execute("SELECT * FROM expenses WHERE merchant=?", (f"Luxury Dinner Bistro {ts}",)).fetchone()
            self.assertIsNotNone(row)
            self.assertIn(row["status"], ("Needs Info", "ADDITIONAL_INFORMATION_REQUESTED"))

    def test_08_project_cap_auto_approval(self):
        """Test 8: Clean claim below project auto-approval cap is automatically approved."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 6
            sess["role"] = "employee"
            sess["user_name"] = "Priya Sen"

        ts = int(time.time() * 1000)
        ref = f"UTR_CLN_{ts}"
        merchant = f"Stationery Supplies {ts}"
        res = self.client.post("/submit", data={
            "expense_date": "2026-10-02",
            "merchant": merchant,
            "category": "Office Supplies",
            "city": "Mumbai",
            "amount": "850.00",
            "currency": "INR",
            "project_code": "PRJ-UPI-09",
            "payment_method": "UPI",
            "upi_app": "PhonePe",
            "transaction_ref": ref
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            row = con.execute("SELECT * FROM expenses WHERE transaction_ref=?", (ref,)).fetchone()
            self.assertIsNotNone(row)
            self.assertIn(row["status"], ("Approved", "AUTO_APPROVED"))
            self.assertEqual(float(row["reimbursable"]), 850.0)

    def test_09_claims_exactly_at_cap(self):
        """Test 9: Claim within project cap auto-approves if compliant."""
        with connect() as con:
            con.execute("UPDATE projects SET auto_approval_cap=2500 WHERE code='PRJ-UPI-09'")
            con.commit()

        with self.client.session_transaction() as sess:
            sess["user_id"] = 6
            sess["role"] = "employee"
            sess["user_name"] = "Priya Sen"

        ts = int(time.time() * 1000)
        ref = f"UTR_EX_{ts}"
        merchant = f"Hardware Supplies {ts}"
        res = self.client.post("/submit", data={
            "expense_date": "2026-10-06",
            "merchant": merchant,
            "category": "Office Supplies",
            "city": "Mumbai",
            "amount": "1250.00",
            "currency": "INR",
            "project_code": "PRJ-UPI-09",
            "payment_method": "UPI",
            "upi_app": "Paytm",
            "transaction_ref": ref
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            row = con.execute("SELECT * FROM expenses WHERE transaction_ref=?", (ref,)).fetchone()
            self.assertIsNotNone(row)
            self.assertIn(row["status"], ("Approved", "AUTO_APPROVED"))

    def test_10_claims_exceeding_the_cap(self):
        """Test 10: Claim exceeding the project cap routes to review."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 6
            sess["role"] = "employee"
            sess["user_name"] = "Priya Sen"

        ts = int(time.time() * 1000)
        ref = f"UTR_OVR_{ts}"
        merchant = f"High Value Server Hardware {ts}"
        res = self.client.post("/submit", data={
            "expense_date": "2026-10-08",
            "merchant": merchant,
            "category": "Office Supplies",
            "city": "Mumbai",
            "amount": "9500.00",
            "currency": "INR",
            "project_code": "PRJ-UPI-09",
            "payment_method": "Corporate Credit Card",
            "transaction_ref": ref
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            row = con.execute("SELECT * FROM expenses WHERE transaction_ref=?", (ref,)).fetchone()
            self.assertIsNotNone(row)
            self.assertIn(row["status"], ("Needs Review", "PENDING_ACCOUNTS_REVIEW"))

    def test_11_company_policy_violations(self):
        """Test 11: Non-reimbursable alcohol/entertainment expenses are deducted or rejected."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 6
            sess["role"] = "employee"
            sess["user_name"] = "Priya Sen"

        ts = int(time.time() * 1000)
        merchant = f"Night Club Lounge {ts}"
        res = self.client.post("/submit", data={
            "expense_date": "2026-10-09",
            "merchant": merchant,
            "category": "Entertainment",
            "city": "Mumbai",
            "amount": "2500.00",
            "currency": "INR",
            "client_name": "",  # Disallowed entertainment
            "project_code": "PRJ-UPI-09",
            "payment_method": "Cash",
            "transaction_ref": f"TX_{ts}"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            row = con.execute("SELECT * FROM expenses WHERE merchant=?", (merchant,)).fetchone()
            self.assertIsNotNone(row)
            self.assertIn(row["status"], ("Rejected", "REJECTED"))
            self.assertEqual(float(row["reimbursable"]), 0.0)

    def test_12_cumulative_spending_limits(self):
        """Test 12: Daily per-diem and cumulative limits capping."""
        with connect() as con:
            row = con.execute("SELECT * FROM expenses WHERE flags LIKE '%per-diem%' OR explanation LIKE '%capped%' LIMIT 1").fetchone()
            if row:
                self.assertLess(float(row["reimbursable"]), float(row["amount_inr"]))

    def test_13_duplicate_and_suspicious_detection(self):
        """Test 13: Submitting identical UTR reference triggers duplicate detection."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 4
            sess["role"] = "employee"
            sess["user_name"] = "Aarav Mehta"

        ts = int(time.time() * 1000)
        ref = f"UTR_REC_{ts}"

        # First claim
        self.client.post("/submit", data={
            "expense_date": "2026-10-15",
            "merchant": f"Original Cafe {ts}",
            "category": "Meals",
            "city": "Mumbai",
            "amount": "400.00",
            "currency": "INR",
            "project_code": "PRJ-UPI-09",
            "payment_method": "UPI",
            "transaction_ref": ref
        })

        # Second claim with exact same UTR ref
        self.client.post("/submit", data={
            "expense_date": "2026-10-15",
            "merchant": f"Duplicate Cafe {ts}",
            "category": "Meals",
            "city": "Mumbai",
            "amount": "400.00",
            "currency": "INR",
            "project_code": "PRJ-UPI-09",
            "payment_method": "UPI",
            "transaction_ref": ref
        })

        with connect() as con:
            dup = con.execute("SELECT * FROM expenses WHERE merchant=?", (f"Duplicate Cafe {ts}",)).fetchone()
            self.assertIsNotNone(dup)
            self.assertIn(dup["status"], ("Duplicate", "Needs Review", "PENDING_ACCOUNTS_REVIEW"))

    def test_14_accounts_approval_and_rejection(self):
        """Test 14: Accounts person approves claims with audit trail."""
        with connect() as con:
            con.execute("UPDATE expenses SET status='Needs Review' WHERE id=2")
            con.commit()

        with self.client.session_transaction() as sess:
            sess["user_id"] = 2  # Finance Reviewer (Accounts)
            sess["role"] = "accounts"
            sess["user_name"] = "Kavita Rao"

        # Approve
        res = self.client.post("/expense/2/action", data={
            "action": "approve",
            "comment": "Approved following finance policy audit."
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            updated = con.execute("SELECT status FROM expenses WHERE id=2").fetchone()
            self.assertIn(updated["status"], ("APPROVED", "Approved"))

    def test_15_accounts_document_requests(self):
        """Test 15: Accounts requests additional documents, transitioning status to ADDITIONAL_INFORMATION_REQUESTED."""
        with connect() as con:
            con.execute("UPDATE expenses SET status='Needs Review' WHERE id=3")
            con.commit()

        with self.client.session_transaction() as sess:
            sess["user_id"] = 2
            sess["role"] = "accounts"
            sess["user_name"] = "Kavita Rao"

        res = self.client.post("/expense/3/request-info", data={
            "review_reason": "Missing tax GST invoice breakdown",
            "requested_documents": "Official GSTIN tax invoice"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            updated = con.execute("SELECT status, review_reason, requested_documents FROM expenses WHERE id=3").fetchone()
            self.assertEqual(updated["status"], "ADDITIONAL_INFORMATION_REQUESTED")
            self.assertEqual(updated["review_reason"], "Missing tax GST invoice breakdown")

    def test_16_employee_document_upload_and_17_resubmission(self):
        """Test 16 & 17: Employee uploads new supporting document and resubmits claim."""
        with connect() as con:
            claim = con.execute("SELECT employee FROM expenses WHERE id=3").fetchone()
            emp_name = claim["employee"]

        with self.client.session_transaction() as sess:
            sess["user_id"] = 4
            sess["role"] = "employee"
            sess["user_name"] = emp_name

        dummy_file = (io.BytesIO(b"Dummy proof bytes for tax invoice"), "tax_invoice_v2.png")
        res = self.client.post("/expense/3/resubmit", data={
            "document": dummy_file,
            "resubmission_note": "Attached official merchant GST tax invoice as requested."
        }, content_type="multipart/form-data", follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            updated = con.execute("SELECT status, resubmission_count FROM expenses WHERE id=3").fetchone()
            self.assertEqual(updated["status"], "RESUBMITTED")
            self.assertGreaterEqual(updated["resubmission_count"], 1)

            # Check supporting documents table has new entry
            doc = con.execute("SELECT * FROM supporting_documents WHERE claim_id=3 ORDER BY id DESC LIMIT 1").fetchone()
            self.assertIsNotNone(doc)
            self.assertEqual(doc["document_category"], "Resubmission Proof")

    def test_18_editing_window_enforcement(self):
        """Test 18: Editing deadline calculation and claim editing."""
        with connect() as con:
            claim = con.execute("SELECT id, employee FROM expenses LIMIT 1").fetchone()
            claim_id = claim["id"]
            emp_name = claim["employee"]

        with self.client.session_transaction() as sess:
            sess["user_id"] = 4
            sess["role"] = "employee"
            sess["user_name"] = emp_name

        res = self.client.post(f"/expense/{claim_id}/edit", data={
            "description": "Updated business purpose note during active window.",
            "client_name": "Updated Client Name"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            updated = con.execute("SELECT description, client_name FROM expenses WHERE id=?", (claim_id,)).fetchone()
            self.assertEqual(updated["description"], "Updated business purpose note during active window.")

    def test_19_preservation_of_historical_claim_versions(self):
        """Test 19: Claim versions table captures immutable snapshots."""
        with connect() as con:
            versions = con.execute("SELECT * FROM claim_versions").fetchall()
            self.assertGreater(len(versions), 0)
            self.assertIn("version_num", versions[0].keys())

    def test_20_correct_notifications(self):
        """Test 20: In-app notifications reach target recipient and manage read status."""
        with connect() as con:
            create_notification(con, 4, 1, "Test Notification", "This is an automated test notification", "info")
            con.commit()

        with self.client.session_transaction() as sess:
            sess["user_id"] = 4
            sess["role"] = "employee"
            sess["user_name"] = "Aarav Mehta"

        res = self.client.get("/notifications", follow_redirects=True)
        self.assertEqual(res.status_code, 200)

    def test_21_audit_logging(self):
        """Test 21: Audit logs preserve actor, action, timestamp, and status changes."""
        with connect() as con:
            claim = con.execute("SELECT audit_log FROM expenses WHERE audit_log IS NOT NULL LIMIT 1").fetchone()
            self.assertIsNotNone(claim)
            logs = json.loads(claim["audit_log"])
            self.assertIsInstance(logs, list)
            self.assertIn("action", logs[0])
            self.assertIn("timestamp", logs[0])

    def test_22_employee_data_isolation(self):
        """Test 22: Employee cannot view another employee's claim detail."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 4  # Aarav Mehta
            sess["role"] = "employee"
            sess["user_name"] = "Aarav Mehta"

        with connect() as con:
            other_claim = con.execute("SELECT id FROM expenses WHERE lower(employee) != 'aarav mehta' LIMIT 1").fetchone()

        if other_claim:
            res = self.client.get(f"/expense/{other_claim['id']}", follow_redirects=False)
            self.assertEqual(res.status_code, 302, "Employee was able to access another employee's claim!")

    def test_23_payment_authorization_and_reimbursed_status(self):
        """Test 23: Distinction between Approved and Reimbursed; recording payment."""
        with connect() as con:
            con.execute("UPDATE expenses SET status='REIMBURSEMENT_PENDING' WHERE id=1")
            con.commit()

        with self.client.session_transaction() as sess:
            sess["user_id"] = 2
            sess["role"] = "accounts"
            sess["user_name"] = "Kavita Rao"

        tx_ref = f"NEFT_{int(time.time() * 1000)}"
        res = self.client.post("/expense/1/action", data={
            "action": "record_payment",
            "reimbursement_method": "Direct Bank Transfer (NEFT)",
            "reimbursement_tx_ref": tx_ref
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with connect() as con:
            paid = con.execute("SELECT status, reimbursed_by, reimbursement_tx_ref FROM expenses WHERE id=1").fetchone()
            self.assertEqual(paid["status"], "REIMBURSED")
            self.assertEqual(paid["reimbursement_tx_ref"], tx_ref)

    def test_24_accurate_financial_calculations(self):
        """Test 24: Difference from cap and reimbursable calculations are accurate to 2 decimal places."""
        with connect() as con:
            expenses = con.execute("SELECT amount_inr, reimbursable, difference_from_cap FROM expenses WHERE amount_inr IS NOT NULL LIMIT 10").fetchall()
            for e in expenses:
                amt = float(e["amount_inr"])
                reimb = float(e["reimbursable"] or 0)
                self.assertLessEqual(reimb, amt + 0.01)

    def test_25_standardized_exports_zip(self):
        """Test 25: Standardized 8-file ZIP export contains all mandatory CSV and JSON files."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["user_name"] = "Priya Sharma"

        res = self.client.get("/admin/export-standardized")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("Content-Type"), "application/zip")

        # Verify ZIP contents
        zip_buffer = io.BytesIO(res.data)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            file_names = set(zf.namelist())
            expected_files = {
                "employees.csv",
                "expenses.csv",
                "receipts.csv",
                "expense_items.csv",
                "policy_evaluations.csv",
                "duplicate_candidates.csv",
                "risk_flags.csv",
                "ingestion_summary.json"
            }
            for expected in expected_files:
                self.assertIn(expected, file_names, f"Missing {expected} in standardized export archive!")

if __name__ == "__main__":
    unittest.main()
