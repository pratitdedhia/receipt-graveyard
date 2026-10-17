# bulk_drive_ingestion.py - Excel & Google Drive Receipt Ingestion Module
import re
import os
import io
import csv
import json
import socket
import logging
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from datetime import datetime
import requests
from decimal import Decimal, ROUND_HALF_UP

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

logger = logging.getLogger(__name__)

# Permitted Google Drive domains for security and SSRF mitigation
PERMITTED_DRIVE_DOMAINS = {
    "drive.google.com",
    "docs.google.com",
    "drive.usercontent.google.com",
    "googleusercontent.com"
}

# Private / local IP ranges that must be blocked for SSRF protection
BLOCKED_IP_PREFIXES = (
    "127.", "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
    "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.",
    "172.27.", "172.28.", "172.29.", "172.30.", "172.31.", "192.168.",
    "169.254.", "0.", "::1", "fe80:"
)

def normalize_drive_link(url):
    """
    Validates a Google Drive URL and extracts its unique file ID safely.
    Returns (is_valid, file_id, error_message).
    Protects against SSRF and non-drive targets.
    """
    if not url or not isinstance(url, str):
        return False, None, "Empty or non-string URL provided."

    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, None, f"Malformed URL: {str(e)}"

    if parsed.scheme not in ("http", "https"):
        return False, None, f"Unsupported URL scheme: {parsed.scheme}. Only HTTP/HTTPS permitted."

    hostname = (parsed.hostname or "").lower()
    if not any(hostname == domain or hostname.endswith("." + domain) for domain in PERMITTED_DRIVE_DOMAINS):
        return False, None, f"Untrusted domain '{hostname}'. Only official Google Drive links are permitted."

    # SSRF Protection: Resolve host IP and ensure not a loopback/private range
    try:
        resolved_ips = socket.gethostbyname_ex(hostname)[2]
        for ip in resolved_ips:
            if any(ip.startswith(prefix) for prefix in BLOCKED_IP_PREFIXES) or ip == "localhost":
                return False, None, f"Security violation: Resolved IP '{ip}' is in a private network range."
    except Exception:
        # If host cannot be resolved right now, let requests handle timeout/failure later
        pass

    file_id = None
    # Pattern 1: /file/d/<file_id>/
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', parsed.path)
    if m:
        file_id = m.group(1)

    # Pattern 2: ?id=<file_id> (e.g. /open?id=... or /uc?id=...)
    if not file_id:
        qs = parse_qs(parsed.query)
        if "id" in qs and qs["id"]:
            file_id = qs["id"][0]

    # Pattern 3: /folders/<file_id> (Folder link - not an individual receipt)
    if not file_id and "/folders/" in parsed.path:
        return False, None, "Google Drive folder link provided. Please provide a direct link to an individual receipt file."

    if not file_id:
        return False, None, "Could not extract a valid Google Drive file ID from URL."

    # Validate file ID structure (typically 28-50 alphanumeric characters)
    if not re.match(r'^[a-zA-Z0-9_-]{10,100}$', file_id):
        return False, None, "Extracted Google Drive file ID has invalid format."

    return True, file_id, None

def download_drive_file(url, destination_dir, timeout=30, max_size_mb=25, custom_session=None):
    """
    Downloads a publicly accessible file from Google Drive.
    - Handles redirect confirmations for large files
    - Detects private/login HTML screens
    - Enforces file size limit and MIME validation
    - Saves to destination_dir with a safe generated filename
    Returns dict with status, local_path, file_id, size_bytes, error_message.
    """
    is_valid, file_id, error = normalize_drive_link(url)
    if not is_valid:
        return {
            "status": "INVALID_LINK",
            "file_id": None,
            "local_path": None,
            "size_bytes": 0,
            "error": error
        }

    session = custom_session or requests.Session()
    session.headers.update({
        "User-Agent": "ReceiptGraveyard-AuditIngest/1.0 (Enterprise Expense Auditor)"
    })

    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    max_bytes = max_size_mb * 1024 * 1024

    try:
        response = session.get(download_url, stream=True, timeout=timeout, allow_redirects=True)
        
        # Check if Google Drive returned a virus scan warning confirmation page
        for k, v in response.cookies.items():
            if k.startswith("download_warning"):
                confirm_url = f"https://drive.google.com/uc?export=download&confirm={v}&id={file_id}"
                response = session.get(confirm_url, stream=True, timeout=timeout, allow_redirects=True)
                break

        # Check response status
        if response.status_code == 404:
            return {
                "status": "NOT_FOUND",
                "file_id": file_id,
                "local_path": None,
                "size_bytes": 0,
                "error": "Google Drive file was not found (404). The file may have been deleted."
            }
        elif response.status_code in (401, 403):
            return {
                "status": "ACCESS_REQUIRED",
                "file_id": file_id,
                "local_path": None,
                "size_bytes": 0,
                "error": "Access denied (403/401). This Google Drive file is private and requires owner permission."
            }
        elif response.status_code != 200:
            return {
                "status": "DOWNLOAD_FAILED",
                "file_id": file_id,
                "local_path": None,
                "size_bytes": 0,
                "error": f"Google Drive HTTP error: Status code {response.status_code}"
            }

        # Inspect Content-Type: If HTML, check if it's a login or permission page
        content_type = response.headers.get("Content-Type", "").lower()
        content_peek = b""
        chunks = []
        total_downloaded = 0

        # Read first chunk to inspect header / magic bytes
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                chunks.append(chunk)
                total_downloaded += len(chunk)
                if not content_peek:
                    content_peek = chunk[:4096]
                if total_downloaded > max_bytes:
                    return {
                        "status": "OVERSIZED",
                        "file_id": file_id,
                        "local_path": None,
                        "size_bytes": total_downloaded,
                        "error": f"File exceeds maximum allowed size of {max_size_mb} MB."
                    }
                if total_downloaded > 65536: # First 64KB enough to inspect
                    break

        # If it returned HTML, check for permission/sign-in text
        if "text/html" in content_type or b"<html" in content_peek.lower() or b"<!doctype html" in content_peek.lower():
            html_text = content_peek.decode("utf-8", errors="ignore")
            if any(term in html_text for term in ["accounts.google.com", "Sign in", "You need access", "permission", "request access"]):
                return {
                    "status": "ACCESS_REQUIRED",
                    "file_id": file_id,
                    "local_path": None,
                    "size_bytes": total_downloaded,
                    "error": "Google Drive file is private. Sign-in or viewer permission is required."
                }

        # Continue streaming remaining chunks if any
        for chunk in response.iter_content(chunk_size=32768):
            if chunk:
                chunks.append(chunk)
                total_downloaded += len(chunk)
                if total_downloaded > max_bytes:
                    return {
                        "status": "OVERSIZED",
                        "file_id": file_id,
                        "local_path": None,
                        "size_bytes": total_downloaded,
                        "error": f"File exceeds maximum allowed size of {max_size_mb} MB."
                    }

        full_content = b"".join(chunks)

        # Detect file extension by magic bytes
        ext = "jpg"
        if full_content.startswith(b"%PDF-"):
            ext = "pdf"
        elif full_content.startswith(b"\x89PNG\r\n\x1a\n"):
            ext = "png"
        elif full_content.startswith(b"\xff\xd8\xff"):
            ext = "jpg"
        elif full_content.startswith(b"RIFF") and b"WEBP" in full_content[:16]:
            ext = "webp"
        elif full_content.startswith(b"II*\x00") or full_content.startswith(b"MM\x00*"):
            ext = "tiff"

        # Generate safe server-side filename
        dest_path = Path(destination_dir)
        dest_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = f"gdrive_{file_id}_{timestamp}.{ext}"
        target_file = dest_path / safe_name

        with open(target_file, "wb") as f:
            f.write(full_content)

        return {
            "status": "SUCCESS",
            "file_id": file_id,
            "local_path": str(target_file),
            "filename": safe_name,
            "size_bytes": len(full_content),
            "extension": ext,
            "error": None
        }

    except requests.exceptions.Timeout:
        return {
            "status": "TIMEOUT",
            "file_id": file_id,
            "local_path": None,
            "size_bytes": 0,
            "error": f"Download request timed out after {timeout} seconds."
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": "NETWORK_ERROR",
            "file_id": file_id,
            "local_path": None,
            "size_bytes": 0,
            "error": f"Network error during download: {str(e)}"
        }
    except Exception as e:
        return {
            "status": "DOWNLOAD_FAILED",
            "file_id": file_id,
            "local_path": None,
            "size_bytes": 0,
            "error": f"Unexpected download exception: {str(e)}"
        }

def inspect_excel_workbook(file_bytes_or_path):
    """
    Reads an uploaded Excel (.xlsx, .xls) or CSV file.
    Returns: {
        'format': 'excel' | 'csv',
        'sheets': [{'name': str, 'rows': int, 'headers': [str], 'preview': [[str]]}]
    }
    """
    if isinstance(file_bytes_or_path, (str, Path)):
        p = Path(file_bytes_or_path)
        is_csv = p.suffix.lower() == ".csv"
        file_bytes = p.read_bytes()
    else:
        file_bytes = file_bytes_or_path.read() if hasattr(file_bytes_or_path, "read") else file_bytes_or_path
        is_csv = False
        if isinstance(file_bytes_or_path, str) and file_bytes_or_path.endswith(".csv"):
            is_csv = True

    # Try openpyxl first
    if not is_csv and HAS_OPENPYXL:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheets_meta = []
            for sheetname in wb.sheetnames:
                ws = wb[sheetname]
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    continue
                # Extract headers
                headers = [str(c).strip() if c is not None else f"Column_{i+1}" for i, c in enumerate(rows[0])]
                preview = []
                for r in rows[1:6]:
                    preview.append([str(c) if c is not None else "" for c in r])
                sheets_meta.append({
                    "name": sheetname,
                    "total_rows": max(0, len(rows) - 1),
                    "headers": headers,
                    "preview": preview,
                    "all_rows": rows[1:]
                })
            if sheets_meta:
                return {"format": "excel", "sheets": sheets_meta, "error": None}
        except Exception as e:
            logger.warning(f"Failed openpyxl read: {e}, falling back to CSV parser.")

    # Fallback to CSV parser
    try:
        text = file_bytes.decode("utf-8", errors="replace")
        reader = list(csv.reader(io.StringIO(text)))
        if reader:
            headers = [h.strip() if h.strip() else f"Column_{i+1}" for i, h in enumerate(reader[0])]
            preview = reader[1:6]
            return {
                "format": "csv",
                "sheets": [{
                    "name": "Sheet1",
                    "total_rows": max(0, len(reader) - 1),
                    "headers": headers,
                    "preview": preview,
                    "all_rows": reader[1:]
                }],
                "error": None
            }
    except Exception as e:
        return {"format": "unknown", "sheets": [], "error": f"Unable to parse spreadsheet: {str(e)}"}

    return {"format": "unknown", "sheets": [], "error": "Spreadsheet is empty or unreadable."}

def auto_detect_columns(headers):
    """
    Maps spreadsheet column headers to standard expense fields.
    """
    col_map = {}
    lower_headers = [h.strip().lower().replace("_", " ").replace("-", " ") for h in headers]

    variations = {
        "employee": ["employee", "staff", "claimant", "user", "name", "employee name", "submitted by", "worker"],
        "email": ["email", "employee email", "staff email", "user email", "mail"],
        "expense_id": ["expense id", "claim id", "id", "exp id", "ticket no", "report id"],
        "merchant": ["merchant", "vendor", "store", "payee", "shop", "establishment", "merchant name"],
        "date": ["date", "expense date", "transaction date", "txn date", "bill date", "receipt date"],
        "category": ["category", "expense category", "type", "cost type", "classification"],
        "amount": ["amount", "cost", "total", "price", "claimed amount", "expense amount", "gross amount"],
        "currency": ["currency", "curr", "fx", "currency code"],
        "receipt_url": ["receipt link", "receipt url", "drive link", "bill link", "invoice link", "google drive link", "link", "url", "receipt", "bill", "attachment"],
        "supporting_url": ["supporting link", "supporting url", "payment screenshot", "payment proof", "proof link", "upi screenshot"],
        "description": ["description", "business purpose", "purpose", "notes", "memo", "justification", "details"],
        "city": ["city", "location", "destination", "town"],
        "project_code": ["project code", "project", "cost center", "project id", "prj"],
        "client_name": ["client name", "client", "customer", "account"],
        "attendees": ["attendees", "attendee count", "pax", "number of attendees"]
    }

    used_indices = set()
    for field, var_list in variations.items():
        matched_idx = None
        # Exact match
        for idx, h in enumerate(lower_headers):
            if idx in used_indices:
                continue
            if h in var_list:
                matched_idx = idx
                break
        # Substring match
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

def init_bulk_tables(con):
    """
    Creates tables for Excel / Google Drive bulk batch processing:
    - import_batches
    - import_rows
    - receipt_extractions
    - receipt_field_corrections
    """
    con.execute("""
    CREATE TABLE IF NOT EXISTS import_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        uploaded_by TEXT NOT NULL,
        status TEXT DEFAULT 'PENDING',
        worksheet TEXT,
        total_rows INTEGER DEFAULT 0,
        completed_rows INTEGER DEFAULT 0,
        failed_rows INTEGER DEFAULT 0,
        config_json TEXT,
        created_at TEXT NOT NULL
    )
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS import_rows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER REFERENCES import_batches(id),
        source_sheet TEXT,
        source_row_num INTEGER,
        original_row_data_json TEXT,
        mapped_employee TEXT,
        receipt_url TEXT,
        drive_file_id TEXT,
        download_status TEXT DEFAULT 'PENDING',
        downloaded_file_path TEXT,
        ocr_status TEXT DEFAULT 'PENDING',
        extracted_data_json TEXT,
        ocr_confidence REAL DEFAULT 0.0,
        import_status TEXT DEFAULT 'PENDING',
        error_message TEXT,
        retry_count INTEGER DEFAULT 0,
        linked_expense_id INTEGER,
        created_at TEXT NOT NULL
    )
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS receipt_extractions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id INTEGER,
        expense_id INTEGER,
        ocr_engine TEXT NOT NULL,
        engine_version TEXT,
        raw_text TEXT,
        structured_json TEXT,
        confidence_json TEXT,
        preprocessing_meta_json TEXT,
        duration_ms INTEGER,
        created_at TEXT NOT NULL
    )
    """)

    con.execute("""
    CREATE TABLE IF NOT EXISTS receipt_field_corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        extraction_id INTEGER,
        expense_id INTEGER,
        field_name TEXT NOT NULL,
        original_ocr_value TEXT,
        corrected_value TEXT NOT NULL,
        corrected_by TEXT NOT NULL,
        corrected_at TEXT NOT NULL,
        reason TEXT
    )
    """)
    con.commit()
