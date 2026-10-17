#!/usr/bin/env python3
"""
scripts/bootstrap_admin.py - Secure Server-Side Administrator Provisioning
Receipt Graveyard AI Expense Auditor

Usage:
    python scripts/bootstrap_admin.py --email admin@company.com --name "System Administrator" --password "SecureAdminPassword2026!"
    python scripts/bootstrap_admin.py --list
"""
import sys
import os
import argparse
import sqlite3
import secrets
import string
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "expenses.db"

def connect_db():
    if not DB_PATH.exists():
        print(f"[ERROR] Database file not found at {DB_PATH}. Please run app once to initialize schema.")
        sys.exit(1)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def generate_secure_password(length=14):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))

def bootstrap_admin(email, name, password=None, office_id=1, department="Executive Office"):
    email = email.strip().lower()
    name = name.strip()
    if not password:
        password = generate_secure_password()
        print(f"[INFO] Auto-generated random secure password: {password}")

    with connect_db() as con:
        existing = con.execute("SELECT id, role, status FROM users WHERE lower(email)=?", (email,)).fetchone()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        if existing:
            con.execute("""
            UPDATE users 
            SET name=?, password=?, role='admin', status='APPROVED', is_active=1, 
                office_id=?, department=?, reviewed_by='Bootstrap Script', reviewed_at=?
            WHERE id=?
            """, (name, password, office_id, department, now_str, existing["id"]))
            con.commit()
            print(f"[SUCCESS] Updated existing user #{existing['id']} ({email}) to APPROVED Administrator.")
        else:
            con.execute("""
            INSERT INTO users (
                name, email, password, role, office_id, department, designation, employee_id,
                status, is_active, created_at, reviewed_by, reviewed_at
            ) VALUES (?, ?, ?, 'admin', ?, ?, 'System Administrator', 'ADM-ROOT-01', 'APPROVED', 1, ?, 'Bootstrap Script', ?)
            """, (name, email, password, office_id, department, now_str, now_str))
            con.commit()
            new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            print(f"[SUCCESS] Created new Administrator account #{new_id} ({email}).")

    print("\n-----------------------------------------------------")
    print(f" Administrator Email:    {email}")
    print(f" Administrator Name:     {name}")
    print(f" Account Role:           admin")
    print(f" Account Status:         APPROVED (Active)")
    print("-----------------------------------------------------\n")

def list_admins():
    with connect_db() as con:
        admins = con.execute("SELECT id, name, email, role, status, is_active, created_at FROM users WHERE role='admin'").fetchall()
        print(f"\n[INFO] Found {len(admins)} Administrator account(s):")
        for a in admins:
            print(f"  - ID: {a['id']} | Name: {a['name']} | Email: {a['email']} | Status: {a['status']} | Active: {a['is_active']}")
        print()

def main():
    parser = argparse.ArgumentParser(description="Bootstrap or provision an Administrator account.")
    parser.add_argument("--email", help="Administrator email address")
    parser.add_argument("--name", default="System Administrator", help="Administrator full name")
    parser.add_argument("--password", help="Administrator password (auto-generated if omitted)")
    parser.add_argument("--list", action="store_true", help="List all configured administrators")

    args = parser.parse_args()

    if args.list:
        list_admins()
        return

    if not args.email:
        print("[ERROR] --email is required to provision an administrator. Example:")
        print("  python scripts/bootstrap_admin.py --email admin@company.com --name 'Admin User'")
        sys.exit(1)

    bootstrap_admin(args.email, args.name, args.password)

if __name__ == "__main__":
    main()
