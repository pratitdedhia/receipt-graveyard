"""
test_budget_workflow.py - Comprehensive Automated Test Suite for:
PROJECT-WISE BUDGET CAPS, CONDITIONAL AUTO-APPROVAL & ACCOUNTS ESCALATION

Covers all 14 Mandatory Test Scenarios specified in Section 12:
- Test 1: Basic automatic approval (Cap: ₹4,000, verified expense: ₹100, bill & payment match, all checks pass)
- Test 2: Multiple valid expenses (Initial allocation: ₹4,000, auto-approved expenses: ₹100, ₹500, ₹400 -> remaining: ₹3,000)
- Test 3: Bill/payment mismatch (Allocation: ₹4,000, Bill: ₹1,000, Payment: ₹900 -> no auto-approval, routed to Accounts Review)
- Test 4: Missing payment proof (Bill present but payment screenshot missing -> NEEDS_INFORMATION / prompt employee)
- Test 5: OCR uncertainty (Low-confidence critical fields -> routed to Accounts Review)
- Test 6: Duplicate receipt (Duplicate receipt detected -> duplicate finding, policy VIOLATION, no auto-approval)
- Test 7: Budget exhaustion (Allocation: ₹4,000, previously approved: ₹3,900, new verified expense: ₹100 -> auto-approves to ₹0; next ₹50 -> blocked with insufficient budget)
- Test 8: Expense exceeds remaining budget (Remaining balance: ₹100, expense amount: ₹250 -> no auto-approval, no overspending)
- Test 9: Independent project allocations (Employee has ₹4,000 for Alpha and ₹2,500 for Beta; ₹100 expense on Alpha does not affect Beta)
- Test 10: Unauthorized employee (Employee cannot submit expenses against another employee's allocation or unauthorized project)
- Test 11: Concurrent approval (Remaining balance: ₹150, two separate expenses of ₹100 processed simultaneously -> atomic check prevents overspending)
- Test 12: Duplicate approval request (Idempotency: same approval submitted twice -> only one approval decision and one budget deduction occur)
- Test 13: Reversal (Approved expense reversed -> original ledger entry remains, compensating REVERSAL ledger entry recorded, remaining budget restored)
- Test 14: Admin override (Authorized admin adjusts cap with mandatory reason -> immutable audit log and ledger adjustment recorded)
"""

import unittest
import json
import time
from decimal import Decimal
import threading
from datetime import datetime

from app import app, connect, init_db
import budget_engine

class ProjectBudgetWorkflowTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        cls.client = app.test_client()
        init_db()

        # Seed dedicated test projects and users if not existing
        with connect() as con:
            # Clean up test namespace
            con.execute("DELETE FROM expenses WHERE merchant LIKE 'TEST_WORKFLOW_%'")
            con.execute("DELETE FROM projects WHERE code IN ('PRJ-ALPHA-101', 'PRJ-BETA-202', 'PRJ-RESTRICTED-303')")
            
            # Create Project Alpha
            con.execute("""
            INSERT INTO projects (code, name, description, budget, auto_approval_cap, status, created_at, updated_at)
            VALUES ('PRJ-ALPHA-101', 'College Event Operations Alpha', 'Core operations budget for campus event', 100000.0, 4000.0, 'Active', '2026-01-01', '2026-01-01')
            """)
            cls.proj_alpha_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Create Project Beta
            con.execute("""
            INSERT INTO projects (code, name, description, budget, auto_approval_cap, status, created_at, updated_at)
            VALUES ('PRJ-BETA-202', 'College Tech Symposium Beta', 'Technical symposium hardware procurement', 75000.0, 2500.0, 'Active', '2026-01-01', '2026-01-01')
            """)
            cls.proj_beta_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Create Restricted Project (explicit membership only)
            con.execute("""
            INSERT INTO projects (code, name, description, budget, auto_approval_cap, status, created_at, updated_at)
            VALUES ('PRJ-RESTRICTED-303', 'Restricted Executive Project', 'Restricted to authorized members only', 50000.0, 5000.0, 'Active', '2026-01-01', '2026-01-01')
            """)
            cls.proj_restricted_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Assign only user 1 (Admin) to Restricted Project to test unauthorized employee access
            con.execute("INSERT OR REPLACE INTO project_memberships (project_id, user_id, role, assigned_at) VALUES (?, 1, 'Owner', '2026-01-01')", (cls.proj_restricted_id,))

            con.commit()

        # Employee A (user_id = 4: Aarav Mehta)
        cls.emp_a_id = 4
        # Employee B (user_id = 6: Kabir Rao)
        cls.emp_b_id = 6
        # Accounts Admin (user_id = 1: Priya Sharma)
        cls.admin_id = 1
        # Accounts Reviewer (user_id = 2: Kavita Rao)
        cls.reviewer_id = 2

    def setUp(self):
        """Reset test allocations and ledger before each test."""
        with connect() as con:
            con.execute("DELETE FROM expenses WHERE merchant LIKE 'TEST_WORKFLOW_%'")
            con.execute("DELETE FROM budget_ledger WHERE project_id IN (?, ?, ?)", (self.proj_alpha_id, self.proj_beta_id, self.proj_restricted_id))
            con.execute("DELETE FROM allocation_adjustments WHERE allocation_id IN (SELECT id FROM project_allocations WHERE project_id IN (?, ?, ?))", (self.proj_alpha_id, self.proj_beta_id, self.proj_restricted_id))
            con.execute("DELETE FROM project_allocations WHERE project_id IN (?, ?, ?)", (self.proj_alpha_id, self.proj_beta_id, self.proj_restricted_id))
            con.commit()

    # Helper method to insert a structured test expense
    def _create_expense(self, con, user_id, project_id, project_code, amount, merchant, file_name="invoice_receipt.jpg", ocr_text=None, payment_file="payment_screenshot.jpg", payment_note="Payment reconciled. Amount matched exactly.", payment_verified=1, transaction_ref=None, flags=None, status="Needs Review"):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        if ocr_text is None:
            ocr_text = f"TAX INVOICE\nMerchant: {merchant}\nDate: 2026-10-15\nTotal: INR {amount:.2f}\nGST: 18%\nSubtotal: {amount*0.82:.2f}"
        if transaction_ref is None:
            transaction_ref = f"UTR_TEST_{int(time.time()*1000)}"
        if flags is None:
            flags = []

        con.execute("""
        INSERT INTO expenses (
            user_id, office_id, employee, submitted_at, expense_date, merchant, category, city, amount, currency,
            amount_inr, eligible_amount, difference_from_cap, payment_method, transaction_ref, project_id, project_code,
            client_name, attendees, description, status, reimbursable, risk_score, flags, suspicion_types,
            explanation, file_name, math_status, extracted_amount, non_reimbursable_deduction, itemized_items,
            ocr_raw_text, payment_file, payment_verified, payment_match_note, audit_log, policy_version, editing_deadline, resubmission_count
        ) VALUES (
            ?, 1, 'Employee', ?, '2026-10-15', ?, 'Office Supplies', 'Mumbai', ?, 'INR',
            ?, ?, 0.0, 'UPI', ?, ?, ?,
            '', 0, 'Test expense submission', ?, ?, 0, ?, '[]',
            'Test expense audit', ?, 'Verified (Matches Items)', ?, 0.0, '[]',
            ?, ?, ?, ?, '[]', 'v2026.1', '2026-10-16 23:59', 0
        )
        """, (
            user_id, now_str, merchant, amount,
            amount, amount, transaction_ref, project_id, project_code,
            status, amount, json.dumps(flags),
            file_name, amount, ocr_text, payment_file, payment_verified, payment_note
        ))
        return con.execute("SELECT last_insert_rowid()").fetchone()[0]

    # -------------------------------------------------------------------------
    # TEST 1: Basic Automatic Approval
    # Allocation: ₹4,000. Verified expense: ₹100. Bill and payment proof match.
    # Expected: Expense auto-approved, ledger entry created exactly once,
    # remaining balance: ₹3,900, employee notification created, audit log records automated decision.
    # -------------------------------------------------------------------------
    def test_01_basic_automatic_approval(self):
        """Test 1: Fully verified ₹100 expense under ₹4,000 cap auto-approves and creates ledger entry."""
        with connect() as con:
            # 1. Allocate ₹4,000 to Employee A under Project Alpha
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            con.commit()
            self.assertEqual(alloc["allocated_cap"], 4000.0)
            self.assertEqual(alloc["remaining_balance"], 4000.0)

            # 2. Create verified expense of ₹100
            exp_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 100.0,
                merchant="TEST_WORKFLOW_Merchant_01",
                payment_note="Payment reconciled. Amount matched ₹100.00 exactly."
            )
            con.commit()

            # 3. Process auto-approval pipeline
            result = budget_engine.process_claim_auto_approval(con, exp_id, actor="System Auto-Approval Engine")
            con.commit()

            self.assertTrue(result["auto_approved"], "Expense should have auto-approved!")
            
            # 4. Verify persistent database record for the expense
            exp = con.execute("SELECT * FROM expenses WHERE id = ?", (exp_id,)).fetchone()
            self.assertEqual(exp["status"], "Approved")
            self.assertEqual(exp["approval_status"], "AUTO_APPROVED")
            self.assertEqual(exp["evidence_verification_status"], "VERIFIED")
            self.assertEqual(exp["budget_status"], "WITHIN_CAP")
            self.assertEqual(exp["reimbursement_status"], "READY_FOR_REIMBURSEMENT")

            # 5. Verify persistent budget ledger record created exactly once
            ledger_rows = con.execute("SELECT * FROM budget_ledger WHERE expense_id = ?", (exp_id,)).fetchall()
            self.assertEqual(len(ledger_rows), 1, "Budget ledger should have exactly 1 entry for this expense.")
            ledger = dict(ledger_rows[0])
            self.assertEqual(ledger["entry_type"], "EXPENDITURE")
            self.assertEqual(ledger["amount"], 100.0)
            self.assertEqual(ledger["balance_after"], 3900.0)

            # 6. Verify real-time balance on the allocation
            bal = budget_engine.calculate_allocation_balance(con, alloc["id"])
            self.assertEqual(bal["allocated_cap"], 4000.0)
            self.assertEqual(bal["approved_expenditure"], 100.0)
            self.assertEqual(bal["remaining_balance"], 3900.0)

            # 7. Verify employee notification created
            notif = con.execute("SELECT * FROM notifications WHERE user_id = ? AND claim_id = ? ORDER BY id DESC LIMIT 1", (self.emp_a_id, exp_id)).fetchone()
            self.assertIsNotNone(notif, "Employee notification should be created.")
            self.assertIn("3,900", notif["message"])

            # 8. Verify audit log records the automated decision
            audit = json.loads(exp["audit_log"] or "[]")
            self.assertTrue(any(a.get("action") == "Auto-Approved" for a in audit))

    # -------------------------------------------------------------------------
    # TEST 2: Multiple Valid Expenses
    # Initial allocation: ₹4,000. Auto-approved expenses: ₹100, ₹500, ₹400.
    # Expected remaining balance: ₹3,000.
    # -------------------------------------------------------------------------
    def test_02_multiple_valid_expenses(self):
        """Test 2: Sequential approved expenses (₹100, ₹500, ₹400) deplete allocation to ₹3,000."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            con.commit()

            amounts = [100.0, 500.0, 400.0]
            for amt in amounts:
                exp_id = self._create_expense(
                    con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", amt,
                    merchant=f"TEST_WORKFLOW_Merchant_Seq_{amt}"
                )
                res = budget_engine.process_claim_auto_approval(con, exp_id, actor="System Auto-Approval Engine")
                self.assertTrue(res["auto_approved"])
                con.commit()

            # Verify authoritative ledger entries count
            ledger_rows = con.execute("SELECT * FROM budget_ledger WHERE allocation_id = ? AND entry_type='EXPENDITURE'", (alloc["id"],)).fetchall()
            self.assertEqual(len(ledger_rows), 3)

            # Verify final balance is exactly ₹3,000
            bal = budget_engine.calculate_allocation_balance(con, alloc["id"])
            self.assertEqual(bal["approved_expenditure"], 1000.0)
            self.assertEqual(bal["remaining_balance"], 3000.0)

    # -------------------------------------------------------------------------
    # TEST 3: Bill/Payment Mismatch
    # Allocation: ₹4,000. Bill: ₹1,000. Payment proof: ₹900.
    # Expected: No automatic approval, no approved-expenditure deduction,
    # routed to Accounts Review, both amounts and discrepancy visible.
    # -------------------------------------------------------------------------
    def test_03_bill_payment_mismatch(self):
        """Test 3: Bill of ₹1,000 with payment proof of ₹900 blocks auto-approval and routes to Accounts Review."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            con.commit()

            exp_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 1000.0,
                merchant="TEST_WORKFLOW_Merchant_Mismatch",
                payment_note="Payment proof mismatch: Screenshot indicates ₹900.00 vs claimed ₹1000.00. Discrepancy: ₹100.00.",
                payment_verified=0,
                flags=["Payment proof mismatch: Screenshot indicates ₹900.00 vs claimed ₹1000.00"]
            )
            con.commit()

            res = budget_engine.process_claim_auto_approval(con, exp_id, actor="System")
            con.commit()

            # Must NOT auto-approve
            self.assertFalse(res["auto_approved"])

            # Must have created NO expenditure in budget ledger
            ledger_cnt = con.execute("SELECT COUNT(*) FROM budget_ledger WHERE expense_id = ?", (exp_id,)).fetchone()[0]
            self.assertEqual(ledger_cnt, 0, "No ledger deduction permitted on mismatched evidence.")

            # Remaining balance must be unchanged at ₹4,000
            bal = budget_engine.calculate_allocation_balance(con, alloc["id"])
            self.assertEqual(bal["remaining_balance"], 4000.0)

            # Verify expense status dimensions and explanation
            exp = con.execute("SELECT * FROM expenses WHERE id = ?", (exp_id,)).fetchone()
            self.assertEqual(exp["status"], "Needs Review")
            self.assertEqual(exp["approval_status"], "PENDING_ACCOUNTS")
            self.assertEqual(exp["evidence_verification_status"], "MISMATCH")
            self.assertIn("900", exp["auto_approval_reasons"])
            self.assertIn("1000", exp["auto_approval_reasons"])

    # -------------------------------------------------------------------------
    # TEST 4: Missing Payment Proof
    # Bill present but payment screenshot missing.
    # Expected: No automatic approval, expense status NEEDS_INFORMATION / Needs Info,
    # employee is prompted to upload evidence.
    # -------------------------------------------------------------------------
    def test_04_missing_payment_proof(self):
        """Test 4: Missing payment screenshot prevents auto-approval and transitions to NEEDS_INFORMATION."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            con.commit()

            exp_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 200.0,
                merchant="TEST_WORKFLOW_Missing_Payment",
                file_name="tax_bill.jpg",
                ocr_text="TAX INVOICE Total INR 200.00 Merchant Stationery Store",
                payment_file=None,
                payment_note="Payment screenshot pending.",
                payment_verified=0,
                transaction_ref=""
            )
            con.commit()

            res = budget_engine.process_claim_auto_approval(con, exp_id, actor="System")
            con.commit()

            self.assertFalse(res["auto_approved"])

            exp = con.execute("SELECT * FROM expenses WHERE id = ?", (exp_id,)).fetchone()
            self.assertEqual(exp["approval_status"], "NEEDS_INFORMATION")
            self.assertEqual(exp["status"], "Needs Info")
            self.assertEqual(exp["evidence_verification_status"], "INCOMPLETE")

            # Verify employee notification prompting upload
            notif = con.execute("SELECT * FROM notifications WHERE user_id = ? AND claim_id = ? ORDER BY id DESC LIMIT 1", (self.emp_a_id, exp_id)).fetchone()
            self.assertIsNotNone(notif)
            self.assertIn("Upload Payment Proof", notif["title"])

    # -------------------------------------------------------------------------
    # TEST 5: OCR Uncertainty
    # Low-confidence critical fields trigger review.
    # Expected: No automatic approval until verified.
    # -------------------------------------------------------------------------
    def test_05_ocr_uncertainty(self):
        """Test 5: Low OCR confidence on key financial fields prevents auto-approval."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            con.commit()

            exp_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 350.0,
                merchant="TEST_WORKFLOW_Low_OCR",
                flags=["Low confidence OCR detected on total invoice amount", "Blurry receipt scan"]
            )
            con.commit()

            res = budget_engine.process_claim_auto_approval(con, exp_id, actor="System")
            con.commit()

            self.assertFalse(res["auto_approved"])

            exp = con.execute("SELECT * FROM expenses WHERE id = ?", (exp_id,)).fetchone()
            self.assertEqual(exp["approval_status"], "PENDING_ACCOUNTS")
            self.assertEqual(exp["evidence_verification_status"], "NEEDS_REVIEW")
            self.assertIn("Low OCR confidence", exp["auto_approval_reasons"])

    # -------------------------------------------------------------------------
    # TEST 6: Duplicate Receipt
    # Expected: Duplicate finding generated, policy compliance VIOLATION,
    # no duplicate reimbursement approval, existing record linked.
    # -------------------------------------------------------------------------
    def test_06_duplicate_receipt(self):
        """Test 6: Duplicate receipt match blocks automatic approval and flags VIOLATION."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            con.commit()

            # First legitimate claim
            exp1_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 150.0,
                merchant="TEST_WORKFLOW_Original_Receipt"
            )
            res1 = budget_engine.process_claim_auto_approval(con, exp1_id, actor="System")
            self.assertTrue(res1["auto_approved"])
            con.commit()

            # Second duplicate claim referencing original claim
            exp2_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 150.0,
                merchant="TEST_WORKFLOW_Duplicate_Receipt",
                flags=[f"Duplicate receipt detected: Exact perceptual hash match with Claim #{exp1_id}"]
            )
            con.execute("UPDATE expenses SET duplicate_of_id = ?, status = 'Duplicate' WHERE id = ?", (exp1_id, exp2_id))
            con.commit()

            res2 = budget_engine.process_claim_auto_approval(con, exp2_id, actor="System")
            con.commit()

            self.assertFalse(res2["auto_approved"])

            exp2 = con.execute("SELECT * FROM expenses WHERE id = ?", (exp2_id,)).fetchone()
            self.assertEqual(exp2["status"], "Duplicate")
            self.assertEqual(exp2["policy_compliance_status"], "VIOLATION")
            self.assertEqual(exp2["duplicate_of_id"], exp1_id)

            # Budget ledger must only have 1 entry (for exp1), not exp2
            ledger_exp2 = con.execute("SELECT COUNT(*) FROM budget_ledger WHERE expense_id = ?", (exp2_id,)).fetchone()[0]
            self.assertEqual(ledger_exp2, 0, "Duplicate expense must not be deducted from ledger.")

    # -------------------------------------------------------------------------
    # TEST 7: Budget Exhaustion
    # Allocation: ₹4,000. Previously approved: ₹3,900.
    # New verified expense: ₹100 -> auto-approves, remaining balance = ₹0.
    # Subsequent verified expense: ₹50 -> blocked with insufficient budget.
    # -------------------------------------------------------------------------
    def test_07_budget_exhaustion(self):
        """Test 7: Exhausting the cap to ₹0 allows ₹100 approval, then rejects subsequent ₹50 expense."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            # Pre-approve ₹3,900
            con.execute("""
            UPDATE project_allocations 
            SET approved_expenditure = 3900.0, remaining_balance = 100.0 
            WHERE id = ?
            """, (alloc["id"],))
            con.commit()

            # 1. Submit ₹100 expense -> Should auto-approve and bring balance to ₹0
            exp_100_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 100.0,
                merchant="TEST_WORKFLOW_Last_100_Available"
            )
            con.commit()
            res1 = budget_engine.process_claim_auto_approval(con, exp_100_id, actor="System")
            con.commit()

            self.assertTrue(res1["auto_approved"], "₹100 expense should auto-approve against remaining ₹100.")
            bal1 = con.execute("SELECT remaining_balance FROM project_allocations WHERE id = ?", (alloc["id"],)).fetchone()
            self.assertEqual(bal1["remaining_balance"], 0.0)

            # 2. Submit ₹50 expense -> Cap is exhausted, must block auto-approval
            exp_50_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 50.0,
                merchant="TEST_WORKFLOW_Over_Exhausted_Cap"
            )
            con.commit()
            res2 = budget_engine.process_claim_auto_approval(con, exp_50_id, actor="System")
            con.commit()

            self.assertFalse(res2["auto_approved"])

            exp_50 = con.execute("SELECT * FROM expenses WHERE id = ?", (exp_50_id,)).fetchone()
            self.assertIn(exp_50["budget_status"], ("CAP_EXHAUSTED", "INSUFFICIENT_BALANCE"))
            self.assertEqual(exp_50["approval_status"], "PENDING_ACCOUNTS_ADMIN")

            # Balance remains ₹0, never negative
            bal2 = con.execute("SELECT remaining_balance FROM project_allocations WHERE id = ?", (alloc["id"],)).fetchone()
            self.assertEqual(bal2["remaining_balance"], 0.0)

    # -------------------------------------------------------------------------
    # TEST 8: Expense Exceeds Remaining Budget
    # Allocation remaining: ₹100. Expense amount: ₹250.
    # Expected: No automatic approval, no overspending, budget adjustment required.
    # -------------------------------------------------------------------------
    def test_08_expense_exceeds_remaining_budget(self):
        """Test 8: Expense of ₹250 against ₹100 remaining balance is blocked from overspending."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            con.execute("UPDATE project_allocations SET approved_expenditure = 3900.0, remaining_balance = 100.0 WHERE id = ?", (alloc["id"],))
            con.commit()

            exp_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 250.0,
                merchant="TEST_WORKFLOW_Excess_250"
            )
            con.commit()

            res = budget_engine.process_claim_auto_approval(con, exp_id, actor="System")
            con.commit()

            self.assertFalse(res["auto_approved"])

            exp = con.execute("SELECT * FROM expenses WHERE id = ?", (exp_id,)).fetchone()
            self.assertEqual(exp["budget_status"], "INSUFFICIENT_BALANCE")
            self.assertEqual(exp["approval_status"], "PENDING_ACCOUNTS_ADMIN")
            self.assertIn("exceeds remaining project allocation", exp["auto_approval_reasons"])

            # Verify balance did not go negative
            bal = con.execute("SELECT remaining_balance FROM project_allocations WHERE id = ?", (alloc["id"],)).fetchone()
            self.assertEqual(bal["remaining_balance"], 100.0)

    # -------------------------------------------------------------------------
    # TEST 9: Independent Project Allocations
    # Employee has ₹4,000 for Project Alpha and ₹2,500 for Project Beta.
    # Approving a ₹100 Alpha expense must NOT change the Beta allocation.
    # -------------------------------------------------------------------------
    def test_09_independent_project_allocations(self):
        """Test 9: Spending on Project Alpha does not alter allocation for Project Beta."""
        with connect() as con:
            alloc_alpha = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            alloc_beta = budget_engine.get_or_create_allocation(
                con, self.proj_beta_id, self.emp_a_id, cap=2500.0, actor="Accounts Admin"
            )
            con.commit()

            # Approve ₹100 expense under Project Alpha
            exp_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 100.0,
                merchant="TEST_WORKFLOW_Alpha_Expense"
            )
            res = budget_engine.process_claim_auto_approval(con, exp_id, actor="System")
            self.assertTrue(res["auto_approved"])
            con.commit()

            # Alpha must be ₹3,900
            bal_alpha = budget_engine.calculate_allocation_balance(con, alloc_alpha["id"])
            self.assertEqual(bal_alpha["approved_expenditure"], 100.0)
            self.assertEqual(bal_alpha["remaining_balance"], 3900.0)

            # Beta must remain untouched at ₹2,500
            bal_beta = budget_engine.calculate_allocation_balance(con, alloc_beta["id"])
            self.assertEqual(bal_beta["approved_expenditure"], 0.0)
            self.assertEqual(bal_beta["remaining_balance"], 2500.0)

    # -------------------------------------------------------------------------
    # TEST 10: Unauthorized Employee
    # Employee cannot submit expenses against an unauthorized project or unassigned budget.
    # -------------------------------------------------------------------------
    def test_10_unauthorized_employee(self):
        """Test 10: Employee submitting against restricted project where they are not a member is blocked."""
        with connect() as con:
            # Employee A submits against Restricted Project (only Admin is assigned)
            exp_id = self._create_expense(
                con, self.emp_a_id, self.proj_restricted_id, "PRJ-RESTRICTED-303", 200.0,
                merchant="TEST_WORKFLOW_Restricted_Access"
            )
            con.commit()

            res = budget_engine.process_claim_auto_approval(con, exp_id, actor="System")
            con.commit()

            self.assertFalse(res["auto_approved"], "Unauthorized project submission must not auto-approve.")
            exp = con.execute("SELECT * FROM expenses WHERE id = ?", (exp_id,)).fetchone()
            self.assertIn("not authorized or assigned", exp["auto_approval_reasons"])
            self.assertEqual(exp["budget_status"], "ALLOCATION_INACTIVE")

    # -------------------------------------------------------------------------
    # TEST 11: Concurrent Approval
    # Remaining balance: ₹150. Two separate expenses of ₹100 processed concurrently.
    # Expected: The system must NOT approve both; final ledger remains consistent (₹50 remaining).
    # -------------------------------------------------------------------------
    def test_11_concurrent_approval(self):
        """Test 11: Atomic concurrency check ensures only one of two ₹100 claims against ₹150 balance succeeds."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=150.0, actor="Accounts Admin"
            )
            con.commit()

            # Create two claims of ₹100 each
            exp1_id = self._create_expense(con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 100.0, merchant="TEST_WORKFLOW_Race_1")
            exp2_id = self._create_expense(con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 100.0, merchant="TEST_WORKFLOW_Race_2")
            con.commit()

        results = []
        def approve_claim(expense_id):
            with connect() as thread_con:
                res = budget_engine.apply_budget_approval(thread_con, expense_id, actor="Concurrent Worker", is_auto=True)
                thread_con.commit()
                results.append(res)

        t1 = threading.Thread(target=approve_claim, args=(exp1_id,))
        t2 = threading.Thread(target=approve_claim, args=(exp2_id,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [r for r in results if r.get("success") is True]
        failures = [r for r in results if r.get("success") is False]

        # Exactly 1 must succeed, 1 must fail due to atomic balance check
        self.assertEqual(len(successes), 1, "Exactly one claim should succeed in concurrent race.")
        self.assertEqual(len(failures), 1, "The competing claim must fail atomic budget deduction.")
        self.assertIn("Insufficient remaining balance", failures[0]["reason"])

        # Final persistent ledger check
        with connect() as con:
            bal = budget_engine.calculate_allocation_balance(con, alloc["id"])
            self.assertEqual(bal["remaining_balance"], 50.0)
            self.assertEqual(bal["approved_expenditure"], 100.0)

    # -------------------------------------------------------------------------
    # TEST 12: Duplicate Approval Request (Idempotency)
    # The same approval request is submitted twice.
    # Expected: Only one approval decision and one budget deduction occur.
    # -------------------------------------------------------------------------
    def test_12_duplicate_approval_request(self):
        """Test 12: Calling apply_budget_approval twice on the same expense is completely idempotent."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            con.commit()

            exp_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 120.0,
                merchant="TEST_WORKFLOW_Idempotent_Test"
            )
            con.commit()

            # First approval
            res1 = budget_engine.apply_budget_approval(con, exp_id, actor="Reviewer", is_auto=False)
            con.commit()
            self.assertTrue(res1["success"])
            self.assertFalse(res1.get("idempotent", False))

            # Second approval attempt on the exact same expense
            res2 = budget_engine.apply_budget_approval(con, exp_id, actor="Reviewer Retry", is_auto=False)
            con.commit()
            self.assertTrue(res2["success"])
            self.assertTrue(res2.get("idempotent", False), "Second call must be flagged idempotent.")

            # Ledger must contain exactly ONE EXPENDITURE entry
            ledger_cnt = con.execute("SELECT COUNT(*) FROM budget_ledger WHERE expense_id = ? AND entry_type = 'EXPENDITURE'", (exp_id,)).fetchone()[0]
            self.assertEqual(ledger_cnt, 1)

            # Remaining balance must be deducted only once (₹4,000 - ₹120 = ₹3,880)
            bal = budget_engine.calculate_allocation_balance(con, alloc["id"])
            self.assertEqual(bal["remaining_balance"], 3880.0)

    # -------------------------------------------------------------------------
    # TEST 13: Reversal
    # An approved expense is later reversed through an authorized process.
    # Expected: Original ledger entry remains intact, compensating entry recorded,
    # remaining budget is recalculated and restored correctly.
    # -------------------------------------------------------------------------
    def test_13_reversal(self):
        """Test 13: Reversing an approved ₹200 expense creates compensating ledger entry and restores balance."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            con.commit()

            exp_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 200.0,
                merchant="TEST_WORKFLOW_Reversal_Target"
            )
            budget_engine.apply_budget_approval(con, exp_id, actor="Reviewer", is_auto=False)
            con.commit()

            # Balance is now ₹3,800
            bal_before = budget_engine.calculate_allocation_balance(con, alloc["id"])
            self.assertEqual(bal_before["remaining_balance"], 3800.0)

            # Execute financial reversal
            rev_res = budget_engine.reverse_expense_approval(
                con, exp_id, reason="Customer cancelled conference booking", actor="Accounts Admin"
            )
            con.commit()
            self.assertTrue(rev_res["success"])
            self.assertEqual(rev_res["amount_reversed"], 200.0)
            self.assertEqual(rev_res["new_remaining_balance"], 4000.0)

            # Verify original ledger entry was NOT deleted
            orig_ledger = con.execute("SELECT * FROM budget_ledger WHERE expense_id = ? AND entry_type = 'EXPENDITURE'", (exp_id,)).fetchone()
            self.assertIsNotNone(orig_ledger, "Original expenditure ledger entry must never be deleted!")

            # Verify compensating entry was created
            comp_ledger = con.execute("SELECT * FROM budget_ledger WHERE expense_id = ? AND entry_type = 'REVERSAL'", (exp_id,)).fetchone()
            self.assertIsNotNone(comp_ledger, "Compensating REVERSAL entry must exist!")
            self.assertEqual(comp_ledger["amount"], -200.0)
            self.assertEqual(comp_ledger["reference_id"], orig_ledger["id"])

            # Verify recalculation of balance directly from database ledger
            bal_after = budget_engine.calculate_allocation_balance(con, alloc["id"])
            self.assertEqual(bal_after["approved_expenditure"], 0.0)
            self.assertEqual(bal_after["remaining_balance"], 4000.0)

    # -------------------------------------------------------------------------
    # TEST 14: Admin Override & Budget Cap Adjustment
    # Authorized admin modifies cap with mandatory reason.
    # Expected: Immutable audit log recorded with previous cap, new cap, actor,
    # timestamp, reason; approved expenditure is never wiped out.
    # -------------------------------------------------------------------------
    def test_14_admin_override(self):
        """Test 14: Admin increases cap from ₹4,000 to ₹6,000 with mandatory reason without wiping spend."""
        with connect() as con:
            alloc = budget_engine.get_or_create_allocation(
                con, self.proj_alpha_id, self.emp_a_id, cap=4000.0, actor="Accounts Admin"
            )
            con.commit()

            # Approve ₹500
            exp_id = self._create_expense(
                con, self.emp_a_id, self.proj_alpha_id, "PRJ-ALPHA-101", 500.0,
                merchant="TEST_WORKFLOW_Spend_Before_Adjustment"
            )
            budget_engine.apply_budget_approval(con, exp_id, actor="System", is_auto=True)
            con.commit()

            bal_pre = budget_engine.calculate_allocation_balance(con, alloc["id"])
            self.assertEqual(bal_pre["remaining_balance"], 3500.0)

            # Admin increases spending cap to ₹6,000
            adj_res = budget_engine.adjust_allocation_cap(
                con, alloc["id"], new_cap=6000.0,
                reason="Executive approval: Expanded venue management scope",
                actor="Priya Sharma (Accounts Admin)"
            )
            con.commit()

            self.assertEqual(adj_res["previous_cap"], 4000.0)
            self.assertEqual(adj_res["new_cap"], 6000.0)
            self.assertEqual(adj_res["approved_expenditure"], 500.0)
            # New Remaining = ₹6,000 - ₹500 = ₹5,500
            self.assertEqual(adj_res["remaining_balance"], 5500.0)

            # Verify immutable audit log
            audit_entry = con.execute("SELECT * FROM allocation_adjustments WHERE allocation_id = ? ORDER BY id DESC LIMIT 1", (alloc["id"],)).fetchone()
            self.assertIsNotNone(audit_entry)
            self.assertEqual(audit_entry["previous_cap"], 4000.0)
            self.assertEqual(audit_entry["new_cap"], 6000.0)
            self.assertEqual(audit_entry["actor"], "Priya Sharma (Accounts Admin)")
            self.assertIn("Expanded venue management", audit_entry["reason"])

            # Verify budget ledger adjustment entry
            adj_ledger = con.execute("SELECT * FROM budget_ledger WHERE allocation_id = ? AND entry_type = 'ADJUSTMENT' ORDER BY id DESC LIMIT 1", (alloc["id"],)).fetchone()
            self.assertIsNotNone(adj_ledger)
            self.assertEqual(adj_ledger["amount"], 2000.0)
            self.assertEqual(adj_ledger["balance_after"], 5500.0)


if __name__ == "__main__":
    unittest.main()
