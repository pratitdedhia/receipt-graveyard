# The Receipt Graveyard — AI Expense Auditor & Fraud Detection Platform

> **Autonomous Enterprise Expense Auditing, High-Accuracy OCR, Policy Compliance & Fraud Intelligence Platform**  
> Transforms unstructured, messy, multi-currency receipts and bulk Google Drive workbooks into deterministic, 100% explainable corporate reimbursement decisions.

---

## 📋 Table of Contents
1. [Problem Statement & Core Objective](#problem-statement--core-objective)
2. [High-Accuracy OCR Pipeline Architecture](#high-accuracy-ocr-pipeline-architecture)
3. [Excel & Google Drive Bulk Receipt Ingestion](#excel--google-drive-bulk-receipt-ingestion)
4. [Enterprise Expense Policy Engine & Approval Hierarchy](#enterprise-expense-policy-engine--approval-hierarchy)
5. [Multi-Vector Duplicate & Fraud Detection](#multi-vector-duplicate--fraud-detection)
6. [Human-in-the-Loop OCR Field Correction & Provenance](#human-in-the-loop-ocr-field-correction--provenance)
7. [UI/UX & Workflow Updates](#uiux--workflow-updates)
8. [Accuracy Benchmarking Suite & Results](#accuracy-benchmarking-suite--results)
9. [Database Schema & Architecture](#database-schema--architecture)
10. [Demo Login Credentials & Quick Persona Switcher](#demo-login-credentials--quick-persona-switcher)
11. [Installation & Windows PowerShell Setup Guide](#installation--windows-powershell-setup-guide)
12. [Automated Test Suite Execution](#automated-test-suite-execution)

---

## 1. Problem Statement & Core Objective

Business expense reimbursement is unnecessarily manual. Employees submit receipts from business trips, client lunches, flights, and office purchases. Finance teams must squint at faded thermal printouts, verify arithmetic, check category limits, enforce approval caps, detect duplicates, and decide whether to approve or reject claims.

Real submissions are messy:
- Receipts are faded, rotated, sideways, or low contrast.
- Amounts use different currencies and Indian numbering formats (`1,23,456.78`).
- Receipts may be submitted multiple times or split across consecutive transactions to dodge approval thresholds.
- Business trips have different per-diem allowances than home office meals.
- Bulk receipts arrive in Excel sheets containing Google Drive links.

**Core Objective:** Reduce manual finance work while improving expense accuracy, policy compliance, duplicate detection, and audit explainability without fabricating data or silently altering numbers.

---

## 2. High-Accuracy OCR Pipeline Architecture

The platform uses a multi-stage document processing pipeline (`ocr_engine.py`) designed for production resilience:

```text
Receipt Image / PDF
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ 1. OpenCV Preprocessing & Restoration                 │
│    • EXIF Orientation Correction                       │
│    • Automated Deskewing & Angle Alignment (Hough/MinArea)│
│    • CLAHE (Contrast Limited Adaptive Histogram Eq.)   │
│    • Bilateral Denoising for Faded Thermal Printouts   │
│    • Otsu Adaptive Binarization                        │
└────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ 2. Modular Multi-Engine Execution                      │
│    • Primary: PaddleOCR (deep learning text detection) │
│    • Fallback: Tesseract OCR (PSM 6 receipt layout)    │
│    • Native PDF: Stream text parser (pypdf)            │
│    • Cloud Interface: Google Document AI / Azure AI    │
└────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ 3. Structured Financial Field Extraction & Validation  │
│    • Merchant Name & Address                           │
│    • GSTIN / Tax Identification (15-char regex)        │
│    • Transaction Date & Timestamp                      │
│    • Indian Number Formatting: 1,23,456.78 and 1,234.50│
│    • Subtotal, CGST, SGST, IGST, VAT, Tip, Discount   │
│    • Grand Total with Candidate Totals Preservation    │
│    • Arithmetic Validation: Subtotal + Taxes + Tip = Total│
│    • Field-Level Confidence Scoring (High/Med/Low)     │
└────────────────────────────────────────────────────────┘
```

---

## 3. Excel & Google Drive Bulk Receipt Ingestion

Finance administrators and authorized employees can ingest batches of receipts via Excel or CSV workbooks containing Google Drive links (`bulk_drive_ingestion.py`):

1. **Workbook Upload (`/import-bulk`):** Supports `.xlsx`, `.xls`, and `.csv` files up to 30MB.
2. **Worksheet & Column Auto-Detection (`/import-bulk/batch/<id>/map`):** Automatically detects headers (`Employee Name`, `Receipt URL`, `Date`, `Amount`, `Merchant`, `Category`, `Notes`) with visual preview of the first 5 rows.
3. **Robust Google Drive Downloader:**
   - Supports `/file/d/ID/view`, `/open?id=ID`, `/uc?id=ID&export=download`.
   - **SSRF Protection:** Resolves hosts and strictly blocks loopback (`127.0.0.1`), private subnets (`10.*`, `172.16-31.*`, `192.168.*`), cloud metadata endpoints (`169.254.169.254`), and non-HTTP schemes.
   - **Anti-Virus Warning Bypass:** Detects and handles Google Drive virus-scan confirmation tokens.
   - **Private File Protection:** Flags inaccessible or permission-restricted files as `ACCESS_REQUIRED` without crashing or aborting the batch.
4. **Background Worker & Live Polling (`/import-bulk/batch/<id>/status`):** Processes receipts in the background via non-blocking worker threads with live client-side progress bars.
5. **Staging & Queue Commit (`/import-bulk/batch/<id>/results`):** Validated rows (`READY_FOR_AUDIT`) can be committed into the primary corporate finance audit queue with one click.

---

## 4. Enterprise Expense Policy Engine & Approval Hierarchy

Policies (`policy.py`) are evaluated deterministically on the backend:
- **Home Office vs. Travel Per-Diems:**
  - Local meals in mapped home city: ₹1,200/day.
  - Out-of-town business trips: Destination city limit (e.g. Mumbai ₹2,500/day, Delhi ₹2,400/day, London £120/day, New York $150/day).
- **Cumulative Running Daily Limits:** Tracks cumulative spend per employee per date. When a second or third receipt on the same date breaches the daily cap, excess amount is flagged and deducted.
- **Enterprise Project Reimbursement Caps:**
  - Each enterprise project has a configurable per-person auto-approval cap (e.g., `PRJ-MIG-2026`: ₹3,500, `PRJ-UPI-09`: ₹5,000). Compliant claims under the cap are auto-approved.
- **Itemized Non-Reimbursable Disallowance:** Automatically deducts prohibited items (alcohol, tobacco, personal supplies) while allowing legitimate food portions to be reimbursed.
- **Conditional Requirements:** Enforces client name when dinner > ₹1,200 and attendee count when > ₹1,000.

---

## 5. Multi-Vector Duplicate & Fraud Detection

- **Level 1 (Exact File Hash):** SHA-256 fingerprinting flags identical receipts uploaded under different names or across different channels.
- **Level 2 (Perceptual Image Hash):** 64-bit dHash detects re-photographed, cropped, resized, or rotated receipts.
- **Level 3 (Exact Transaction Duplicate):** Flags identical (Employee + Merchant + Date + Amount) matches.
- **Level 4 (Split Transactions / Smurfing):** Flags consecutive receipts at the same vendor submitted just below policy limits.
- **Level 5 (Cross-Employee Collusion):** Detects when two employees submit the same physical bill.

---

## 6. Human-in-the-Loop OCR Field Correction & Provenance

When an OCR extraction has low confidence or faint thermal printing, reviewers can correct fields directly on `/expense/<id>`:
- **Action:** Open `Correct Extracted Field` modal.
- **Target Fields:** Amount, Merchant, Date, Category, City.
- **Mandatory Justification:** Reviewer must provide an audit reason (e.g., "Faded thermal printout digit 8 misread as 3").
- **Immutable Provenance:** The original OCR extracted value is permanently stored in `receipt_field_corrections` and linked in the audit log. The system never overwrites extraction history.

---

## 7. UI/UX & Workflow Updates

1. **Submission Channel Field Completely Removed:** Eliminates redundant channel selectors from all submission forms and claim detail views.
2. **UPI Payment Method Lock:** Restricts payment method strictly to UPI with app selection (Google Pay, PhonePe, Paytm, CRED, BHIM) and optional UPI VPA.
3. **City Auto-Selected Currency:** Selecting an expense city automatically selects its official currency (e.g. Mumbai/Delhi -> INR, New York -> USD, London -> GBP, Frankfurt -> EUR, Dubai -> AED).
4. **Future Dates Blocked:** Enforces HTML5 `max` attribute set to today and server-side validation rejecting any post-dated claims.
5. **Business Trip & Project Questionnaire:** Interactive hierarchy:
   - "Was this an official out-of-town business trip?" -> If yes:
   - "Was this trip for an enterprise project?" -> If yes:
   - Reveals "Enterprise Project Code" dropdown displaying active project codes and auto-approval caps.

---

## 8. Accuracy Benchmarking Suite & Results

The platform includes a standalone accuracy test harness (`benchmark_ocr.py`) evaluating text recognition, Character Error Rate (CER), Word Error Rate (WER), and field extraction across diverse receipt types:

```text
================================================================================
  THE RECEIPT GRAVEYARD — HIGH-ACCURACY OCR & EXTRACTION BENCHMARK  
================================================================================
ID     Category                     Merchant     Date       Total      Curr  Conf   CER   
-------------------------------------------------------------------------------------
BM-01  Clean Printed Receipt        PASS         PASS       PASS       PASS    93%  0.00
BM-02  Indian Number Formatting     PASS         PASS       PASS       PASS    87%  0.00
BM-03  Faded / Low-Contrast Therm   PASS         PASS       PASS       PASS    93%  0.00
BM-04  Multi-Currency Foreign Inv   PASS         PASS       PASS       PASS    93%  0.00
BM-05  Multiple Candidate Totals    PASS         PASS       PASS       PASS    87%  0.00
BM-06  Client Meal with Tip & Sur   PASS         PASS       PASS       PASS    87%  0.00
-------------------------------------------------------------------------------------

BENCHMARK ACCURACY SUMMARY:
  * Merchant Name Exact/Normalized Match: 100.0% (6/6)
  * Transaction Date Exact Match:        100.0% (6/6)
  * Total Amount Exact Match (Decimal):   100.0% (6/6)
  * Currency Accuracy:                    100.0% (6/6)
  * Mean Character Error Rate (CER):      0.0000
  * Mean Word Error Rate (WER):           0.0000
  * Avg Field Extraction Latency:         1.32 ms / receipt
```

To run the benchmark independently:
```powershell
.venv\Scripts\python.exe benchmark_ocr.py
```

---

## 9. Database Schema & Architecture

```text
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│              USERS              │       │             OFFICES             │
├─────────────────────────────────┤       ├─────────────────────────────────┤
│ id (PK)                         │◄──────│ id (PK)                         │
│ email, password, name, role     │       │ name, city, state, address      │
│ office_id (FK), department      │       │ local_meal_cap (₹1,200)         │
└────────────────┬────────────────┘       └─────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│            EXPENSES             │       │            PROJECTS             │
├─────────────────────────────────┤       ├─────────────────────────────────┤
│ id (PK), user_id (FK)           │◄──────│ id (PK), code, name, client     │
│ employee, expense_date, merchant│       │ auto_approval_cap (₹2,000-5,000)│
│ amount, currency, amount_inr    │       │ budget, status                  │
│ eligible_amount, reimbursable   │       └─────────────────────────────────┘
│ payment_method (UPI), upi_app   │
│ is_trip, project_code           │       ┌─────────────────────────────────┐
│ math_status, extracted_amount   │       │   RECEIPT_FIELD_CORRECTIONS     │
│ file_hash (SHA-256), dHash      │       ├─────────────────────────────────┤
│ status, risk_score, audit_log   │◄──────│ id (PK), expense_id (FK)        │
└────────────────┬────────────────┘       │ field_name, original_ocr_value  │
                 │                        │ corrected_value, corrected_by   │
                 ▼                        │ corrected_at, reason            │
┌─────────────────────────────────┐       └─────────────────────────────────┘
│      SUPPORTING_DOCUMENTS       │
├─────────────────────────────────┤       ┌─────────────────────────────────┐
│ id (PK), claim_id (FK)          │       │         IMPORT_BATCHES          │
│ filename, document_category     │       ├─────────────────────────────────┤
│ file_type, revision, note       │       │ id (PK), filename, uploaded_by  │
└─────────────────────────────────┘       │ status, worksheet, total_rows   │
                                          │ completed_rows, failed_rows     │
                                          └────────────────┬────────────────┘
                                                           │
                                                           ▼
                                          ┌─────────────────────────────────┐
                                          │           IMPORT_ROWS           │
                                          ├─────────────────────────────────┤
                                          │ id (PK), batch_id (FK)          │
                                          │ source_sheet, source_row_num    │
                                          │ mapped_employee, receipt_url    │
                                          │ drive_file_id, download_status  │
                                          │ ocr_status, import_status       │
                                          │ extracted_data_json, confidence │
                                          │ linked_expense_id (FK)          │
                                          └─────────────────────────────────┘
```

---

## 10. Demo Login Credentials & Quick Persona Switcher

The top navigation includes an instant **Quick Persona Switcher** dropdown for hackathon demonstration:

| Persona | Role | Email | Password | Home Office |
| :--- | :--- | :--- | :--- | :--- |
| **Rajesh Sharma** | Finance Admin | `rajesh.sharma@graveyard.corp` | `admin123` | Mumbai HQ (₹1,200 cap) |
| **Priya Nair** | Accounts Reviewer | `priya.nair@graveyard.corp` | `accounts123` | Mumbai HQ (₹1,200 cap) |
| **Vikram Sen** | Accounts Reviewer | `vikram.sen@graveyard.corp` | `accounts123` | Bengaluru Tech Hub |
| **Aarav Mehta** | Staff Employee | `aarav.mehta@graveyard.corp` | `emp123` | Mumbai HQ |
| **Neha Sharma** | Staff Employee | `neha.sharma@graveyard.corp` | `emp123` | Delhi Regional Office |
| **Rohan Verma** | Staff Employee | `rohan.verma@graveyard.corp` | `emp123` | Pune Delivery Center |
| **Kavita Patel** | Staff Employee | `kavita.patel@graveyard.corp` | `emp123` | Hyderabad Center |

---

## 11. Installation & Windows PowerShell Setup Guide

Run the following commands in **Windows PowerShell**:

```powershell
# 1. Clone repository and navigate to folder
cd c:\Users\dedhi\Downloads\receipt_graveyard

# 2. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Generate sample Excel workbook with Google Drive receipt links
.venv\Scripts\python.exe scripts\generate_sample_excel.py

# 5. Run the High-Accuracy OCR benchmark
.venv\Scripts\python.exe benchmark_ocr.py

# 6. Start the Receipt Graveyard server
.venv\Scripts\python.exe app.py
```

Open your browser at **`http://127.0.0.1:5000`**.

---

## 12. Automated Test Suite Execution

All business logic, security constraints, and OCR pipelines are covered by automated unit and integration tests:

```powershell
# Run the complete test suite (34 tests)
.venv\Scripts\python.exe -W ignore -m unittest test_suite.py test_high_accuracy_ocr.py
```

### Actual Execution Results:
```text
Ran 34 tests in 3.008s
OK
```

All 34 automated tests execute cleanly with a 100% pass rate.
#   r e c e i p t - g r a v e y a r d  
 