#!/usr/bin/env python3
"""
Generates a realistic sample Excel workbook with Google Drive receipt links
for hackathon demonstration of the Bulk Receipt Ingestion & High-Accuracy OCR Pipeline.
"""

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from pathlib import Path

def create_sample_workbook():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Q4_Expenses_Drive_Receipts"

    headers = [
        "Employee Name",
        "Expense Date",
        "Category",
        "Claimed Amount",
        "Currency",
        "Google Drive Receipt Link",
        "Merchant / Vendor",
        "Business Purpose"
    ]

    ws.append(headers)

    # Style header row
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="10211A", end_color="10211A", fill_type="solid")
    center_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin', color='D9E3DB'),
        right=Side(style='thin', color='D9E3DB'),
        top=Side(style='thin', color='D9E3DB'),
        bottom=Side(style='thin', color='D9E3DB')
    )

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align

    # Realistic Test Data Rows
    sample_rows = [
        (
            "Aarav Mehta",
            "2026-10-12",
            "Meals",
            766.50,
            "INR",
            "https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/view?usp=sharing",
            "Theobroma Foods Pvt Ltd",
            "Client lunch discussion with HDFC product team"
        ),
        (
            "Priya Nair",
            "2026-10-14",
            "Travel",
            1400.00,
            "INR",
            "https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStUvWxYz012345",
            "Meru Cabs Airport",
            "T2 Airport cab to BKC office for Q4 review"
        ),
        (
            "Rohan Verma",
            "2026-10-04",
            "Office Supplies",
            39.00,
            "USD",
            "https://drive.google.com/uc?id=1ZyxWvUtSrQpOnMlKjIhGfEdCbA987654&export=download",
            "GitHub Inc",
            "Monthly Copilot Enterprise cloud license for engineering"
        ),
        (
            "Neha Sharma",
            "2026-10-15",
            "Meals",
            2929.76,
            "INR",
            "https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/view",
            "Toit Brewpub Indiranagar",
            "Engineering sprint retrospective dinner (Duplicate file test)"
        ),
        (
            "Vikram Sen",
            "2026-10-10",
            "Meals",
            3168.00,
            "INR",
            "https://drive.google.com/file/d/1PrivateDocNoPublicAccessPermissionDenied999/view",
            "ITC Grand Chola Chennai",
            "Private corporate shared folder receipt (Access required test)"
        ),
        (
            "Kavita Patel",
            "2026-09-28",
            "Office Supplies",
            145679.00,
            "INR",
            "https://drive.google.com/file/d/1LakhNumberFormattingInvoiceTestFileId2026/view",
            "Croma Electronics",
            "4K UltraSharp development monitors for mobile switch rollout"
        )
    ]

    for row_idx, r in enumerate(sample_rows, start=2):
        for col_idx, val in enumerate(r, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            if col_idx in (2, 5):
                cell.alignment = Alignment(horizontal="center")
            elif col_idx == 4:
                cell.number_format = '#,##0.00'
                cell.alignment = Alignment(horizontal="right")

    # Auto-adjust column widths
    column_widths = {
        'A': 18,
        'B': 14,
        'C': 16,
        'D': 16,
        'E': 10,
        'F': 48,
        'G': 28,
        'H': 44
    }
    for col, width in column_widths.items():
        ws.column_dimensions[col].width = width

    out_path = Path("sample_receipts_drive.xlsx")
    wb.save(out_path)
    print(f"Generated sample workbook with Google Drive links: {out_path.resolve()}")

if __name__ == "__main__":
    create_sample_workbook()
