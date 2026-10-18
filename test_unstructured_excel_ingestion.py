# test_unstructured_excel_ingestion.py - Automated tests for Smart Unstructured Excel Ingestion & Auto-User Provisioning
import io
import unittest
import openpyxl
from datetime import datetime

import app
import unstructured_excel_engine

class TestUnstructuredExcelIngestion(unittest.TestCase):
    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()
        app.init_db()

    def test_unstructured_excel_parsing_and_user_creation(self):
        # 1. Generate an in-memory unstructured Excel workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Messy_Q4_Expenses"

        # Add 2 messy title rows before the real header
        ws.append(["ACME GLOBAL CORP - UNSTRUCTURED EXPENSE AUDIT", "", "", ""])
        ws.append(["Confidential - Internal Accounts Review", "", "", ""])
        
        # Unstructured/inconsistent headers
        headers = [
            "Team Member",       # Employee
            "Spent On",           # Date
            "Vendor / Store",     # Merchant
            "Expense Head",       # Category
            "Price (INR)",        # Amount
            "Cost Center",        # Project
            "Item Details",       # Description
            "Contact Phone"       # Phone
        ]
        ws.append(headers)

        # Generate a unique brand new employee who definitely doesn't exist
        unique_emp_name = f"Kavita Verma {int(datetime.now().timestamp())}"
        test_rows = [
            (
                unique_emp_name,
                "2026-10-14",
                "Grand Hyatt Mumbai",
                "Lodging",
                "4,500.00",
                "PRJ-MIG-2026",
                "Accommodations during client technical audit",
                "+91 91234 56789"
            ),
            (
                "Aarav Mehta", # Existing user
                "15/10/2026",
                "Mainland China",
                "Dining",
                "1850",
                "PRJ-MIG-2026",
                "Client dinner discussion",
                ""
            )
        ]
        for r in test_rows:
            ws.append(r)

        excel_stream = io.BytesIO()
        wb.save(excel_stream)
        excel_bytes = excel_stream.getvalue()

        # 2. Process through unstructured_excel_engine
        with app.connect() as con:
            report = unstructured_excel_engine.process_unstructured_ledger(
                con=con,
                file_bytes=excel_bytes,
                filename="Messy_Q4_Expenses.xlsx",
                current_user_id=2,
                analyze_func=app.analyze_expense
            )

        # 3. Assertions
        self.assertTrue(report["success"])
        self.assertEqual(report["total_rows_processed"], 2)
        self.assertGreaterEqual(report["total_amount_inr"], 6350.0)

        # Verify new user was created
        created_users = report["new_users_created"]
        self.assertEqual(len(created_users), 1)
        new_user = created_users[0]
        self.assertEqual(new_user["name"], unique_emp_name)
        self.assertTrue(new_user["email"].endswith("@receiptgraveyard.com"))
        self.assertEqual(new_user["password"], f"Welcome@{datetime.now().year}")

        # Verify the new user can authenticate / exists in database
        with app.connect() as con:
            u_row = con.execute("SELECT * FROM users WHERE id=?", (new_user["id"],)).fetchone()
            self.assertIsNotNone(u_row)
            self.assertEqual(u_row["name"], unique_emp_name)
            self.assertEqual(u_row["role"], "employee")
            self.assertEqual(u_row["status"], "APPROVED")
            self.assertEqual(u_row["is_active"], 1)

            # Verify the claim was arranged into portal requirements
            exp_row = con.execute("SELECT * FROM expenses WHERE user_id=?", (new_user["id"],)).fetchone()
            self.assertIsNotNone(exp_row)
            self.assertEqual(exp_row["merchant"], "Grand Hyatt Mumbai")
            self.assertEqual(exp_row["category"], "Lodging")
            self.assertEqual(exp_row["amount"], 4500.0)
            self.assertEqual(exp_row["expense_date"], "2026-10-14")
            self.assertEqual(exp_row["project_code"], "PRJ-MIG-2026")

    def test_accounts_upload_ledger_http_endpoint(self):
        # Test HTTP GET and POST
        with self.client.session_transaction() as sess:
            sess["user_id"] = 2
            sess["role"] = "accounts"
            sess["user_name"] = "Priya Nair"

        res = self.client.get("/accounts/upload-ledger")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Smart Excel Ledger Ingestor", res.data)
        self.assertIn(b"Upload Unstructured Excel", res.data)

if __name__ == "__main__":
    unittest.main()
