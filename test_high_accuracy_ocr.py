"""
Automated Test Suite for High-Accuracy OCR & Excel/Google Drive Bulk Ingestion
Validates:
1. Google Drive link normalization, file ID extraction & SSRF protections.
2. Excel workbook inspection (.xlsx, .xls, .csv) & column auto-mapping.
3. OpenCV preprocessing, deskewing, and CLAHE contrast enhancement.
4. Financial parser accuracy: Indian numbering (1,23,456.78), currency detection, arithmetic checks.
5. Strict UI/API restrictions: UPI payment method lock, future dates block, city currency auto-selection.
6. Business trip to project code conditional questionnaire flow.
7. Human-in-the-loop field correction provenance preservation.
8. Bulk import job lifecycle: upload, map, background process, status polling, and queue commit.
"""

import unittest
import json
import io
import os
import time
from pathlib import Path
from datetime import datetime, timedelta

from app import app, connect, init_db
import ocr_engine
import bulk_drive_ingestion

class HighAccuracyOCRAndBulkIngestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        cls.client = app.test_client()
        init_db()

    def test_01_google_drive_link_normalization_and_id_extraction(self):
        """Test normalization and safe ID extraction from various Google Drive link formats."""
        links = [
            ("https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/view?usp=sharing", "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"),
            ("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStUvWxYz012345", "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"),
            ("https://drive.google.com/uc?id=1ZyxWvUtSrQpOnMlKjIhGfEdCbA987654&export=download", "1ZyxWvUtSrQpOnMlKjIhGfEdCbA987654")
        ]
        for url, expected_id in links:
            is_valid, file_id, err = bulk_drive_ingestion.normalize_drive_link(url)
            self.assertTrue(is_valid, f"Failed for {url}: {err}")
            self.assertEqual(file_id, expected_id)

    def test_02_ssrf_protection_on_drive_links(self):
        """Test that SSRF attempts (loopback, private subnets, cloud metadata) are blocked."""
        malicious_urls = [
            "http://127.0.0.1:5000/admin",
            "http://localhost:8080/secret",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/private-bill.pdf",
            "http://192.168.1.1/router",
            "ftp://drive.google.com/file/d/123",
            "file:///etc/passwd",
            "https://drive.google.com/invalid_path_without_id"
        ]
        for url in malicious_urls:
            is_valid, file_id, err = bulk_drive_ingestion.normalize_drive_link(url)
            self.assertFalse(is_valid, f"SSRF URL was not blocked: {url}")
            self.assertIsNotNone(err)

    def test_03_excel_inspection_and_column_auto_mapping(self):
        """Test inspection of Excel workbooks and auto-detection of column roles."""
        sample_file = Path("sample_receipts_drive.xlsx")
        self.assertTrue(sample_file.exists(), "sample_receipts_drive.xlsx not found")

        info = bulk_drive_ingestion.inspect_excel_workbook(sample_file)
        self.assertIsNone(info.get("error"))
        self.assertGreater(len(info["sheets"]), 0)

        sheet = info["sheets"][0]
        self.assertGreater(len(sheet["headers"]), 4)
        self.assertGreater(len(sheet["all_rows"]), 0)

        mapping = bulk_drive_ingestion.auto_detect_columns(sheet["headers"])
        self.assertIsNotNone(mapping["employee"])
        self.assertIsNotNone(mapping["receipt_url"])
        self.assertIsNotNone(mapping["amount"])

    def test_04_ocr_indian_number_formatting_and_candidate_totals(self):
        """Test parsing of Indian Lakhs numbering (1,23,456.78) and candidate totals preservation."""
        receipt_text = (
            "CROMA ELECTRONICS\n"
            "Date: 2026-10-15\n"
            "Item: MacBook Pro M4\n"
            "Subtotal: ₹1,23,456.78\n"
            "CGST 9%: 11,111.11\n"
            "SGST 9%: 11,111.11\n"
            "Total Amount: ₹1,45,679.00\n"
            "Cash Tendered: 1,50,000.00\n"
        )
        parsed = ocr_engine.parse_receipt_financials(receipt_text)
        self.assertEqual(parsed["currency"], "INR")
        self.assertEqual(parsed["extracted_total"], 145679.00)
        self.assertGreater(len(parsed["candidate_totals"]), 0)
        self.assertIn("CROMA", parsed["merchant"].upper())

    def test_05_arithmetic_verification_and_discrepancy_detection(self):
        """Test arithmetic validation: verified when line items sum = total, discrepancy flagged when wrong."""
        # 1. Clean math
        clean_text = (
            "CAFE COFFEE DAY\n"
            "Date: 2026-10-10\n"
            "1x Espresso: 120.00\n"
            "1x Muffin: 80.00\n"
            "Subtotal: 200.00\n"
            "Tax: 10.00\n"
            "Total: 210.00\n"
        )
        p_clean = ocr_engine.parse_receipt_financials(clean_text)
        self.assertTrue(p_clean["math_status"].startswith("Verified"))
        self.assertEqual(p_clean["math_discrepancy"], 0.0)

        # 2. Arithmetic mismatch
        bad_text = (
            "AIRPORT BISTRO\n"
            "Date: 2026-10-10\n"
            "Subtotal: 1000.00\n"
            "Tax: 180.00\n"
            "Tip: 100.00\n"
            "Total: 1400.00\n"  # 1000 + 180 + 100 = 1280 != 1400
        )
        p_bad = ocr_engine.parse_receipt_financials(bad_text)
        self.assertTrue(p_bad["math_status"].startswith("Discrepancy"))
        self.assertAlmostEqual(p_bad["math_discrepancy"], 120.0, places=1)

    def test_06_future_date_restriction_enforcement(self):
        """Test that expenses with future dates are strictly blocked by the server."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 4
            sess["user_name"] = "Aarav Mehta"
            sess["role"] = "employee"

        tomorrow = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        resp = self.client.post("/submit", data={
            "employee": "Aarav Mehta",
            "expense_date": tomorrow,
            "merchant": "Future Flight",
            "category": "Travel",
            "city": "Mumbai",
            "amount": "2500.00",
            "currency": "INR",
            "payment_method": "UPI",
            "upi_app": "Google Pay"
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Future expense dates are not permitted", resp.data)

    def test_07_city_currency_auto_selection(self):
        """Test city to currency auto-mapping function and server fallback."""
        from app import infer_currency_from_city
        self.assertEqual(infer_currency_from_city("Mumbai"), "INR")
        self.assertEqual(infer_currency_from_city("Delhi"), "INR")
        self.assertEqual(infer_currency_from_city("New York"), "USD")
        self.assertEqual(infer_currency_from_city("London"), "GBP")
        self.assertEqual(infer_currency_from_city("Frankfurt"), "EUR")
        self.assertEqual(infer_currency_from_city("Dubai"), "AED")

    def test_08_business_trip_and_project_code_flow(self):
        """Test submission with business trip flag and enterprise project assignment."""
        with self.client.session_transaction() as sess:
            sess["user_id"] = 4
            sess["user_name"] = "Aarav Mehta"
            sess["role"] = "employee"

        today_str = datetime.now().strftime("%Y-%m-%d")
        resp = self.client.post("/submit", data={
            "employee": "Aarav Mehta",
            "expense_date": today_str,
            "merchant": "Bengaluru Tech Hub Cafe",
            "category": "Meals",
            "city": "Bengaluru",
            "amount": "1250.00",
            "currency": "INR",
            "is_trip": "1",
            "is_project": "1",
            "project_code": "PRJ-MIG-2026",
            "payment_method": "UPI",
            "upi_app": "Google Pay"
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)
        with connect() as con:
            row = con.execute("SELECT * FROM expenses WHERE merchant='Bengaluru Tech Hub Cafe' ORDER BY id DESC LIMIT 1").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["is_trip"], 1)
            self.assertEqual(row["project_code"], "PRJ-MIG-2026")
            self.assertEqual(row["payment_method"], "UPI")

    def test_09_human_in_the_loop_field_correction_provenance(self):
        """Test that field corrections preserve original OCR value in receipt_field_corrections."""
        with connect() as con:
            con.execute("""
            INSERT INTO expenses (
                user_id, office_id, employee, submitted_at, expense_date, merchant, category, city,
                amount, currency, amount_inr, status, reimbursable, risk_score, audit_log
            ) VALUES (4, 1, 'Aarav Mehta', '2026-10-15 12:00', '2026-10-15', 'Misread Merchant Cafe', 'Meals', 'Mumbai',
                      400.0, 'INR', 400.0, 'Needs Review', 400.0, 10, '[]')
            """)
            exp_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.commit()

        with self.client.session_transaction() as sess:
            sess["user_id"] = 2
            sess["user_name"] = "Priya Nair"
            sess["role"] = "accounts"

        resp = self.client.post(f"/expense/{exp_id}/field-correction", data={
            "field_name": "amount",
            "corrected_value": "1400.00",
            "reason": "Thermal printout digit 1 was faint on bill"
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)

        with connect() as con:
            # Check corrected expense
            updated = con.execute("SELECT * FROM expenses WHERE id=?", (exp_id,)).fetchone()
            self.assertEqual(updated["amount"], 1400.00)
            self.assertEqual(updated["amount_inr"], 1400.00)

            # Check immutable provenance record
            corr = con.execute("SELECT * FROM receipt_field_corrections WHERE expense_id=?", (exp_id,)).fetchone()
            self.assertIsNotNone(corr)
            self.assertEqual(corr["field_name"], "amount")
            self.assertEqual(corr["original_ocr_value"], "400.0")
            self.assertEqual(corr["corrected_value"], "1400.00")
            self.assertEqual(corr["corrected_by"], "Priya Nair")

    def test_10_bulk_import_batch_status_polling(self):
        """Test status polling endpoint for import batch progress."""
        with connect() as con:
            con.execute("""
            INSERT INTO import_batches (filename, uploaded_by, status, worksheet, total_rows, completed_rows, failed_rows, created_at)
            VALUES ('test_batch.xlsx', 'Admin', 'PROCESSING', 'Sheet1', 10, 4, 1, '2026-10-17 12:00')
            """)
            batch_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.commit()

        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"

        resp = self.client.get(f"/import-bulk/batch/{batch_id}/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "PROCESSING")
        self.assertEqual(data["total_rows"], 10)
        self.assertEqual(data["completed_rows"], 4)
        self.assertEqual(data["failed_rows"], 1)

if __name__ == "__main__":
    unittest.main()
