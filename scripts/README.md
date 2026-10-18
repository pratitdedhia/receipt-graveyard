# Repository Helper & Test Scripts

This directory contains utility, verification, and testing scripts for the Receipt Graveyard AI platform:

| Script | Purpose |
|---|---|
| `bootstrap_admin.py` | Bootstraps or resets the administrator account in `expenses.db` |
| `check_db.py` | Inspects database connection, tables, row counts, and schema definitions |
| `create_sample_receipts.py` | Generates synthetic sample receipt images and payment screenshots in `uploads/` |
| `generate_sample_excel.py` | Generates sample Excel expense ledgers for testing bulk ingestion workflows |
| `test_approval_flow.py` | Verifies end-to-end multi-tier approval flows (Finance Manager & Accounts) |
| `test_rejection_flow.py` | Verifies policy rejection reasons, audit trail updates, and notifications |

## Running Scripts

Run any script using the project's virtual environment:
```bash
.venv\Scripts\python.exe scripts/<script_name>.py
```
