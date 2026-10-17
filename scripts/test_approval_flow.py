import requests
import sqlite3

s = requests.Session()

# Clean up any existing candidate from previous run
with sqlite3.connect('expenses.db') as con:
    con.execute("DELETE FROM users WHERE email='candidate.emp@company.com'")
    con.commit()

# 1. Register a new employee
reg_data = {
    'name': 'Test Candidate Employee',
    'email': 'candidate.emp@company.com',
    'password': 'Password2026!',
    'confirm_password': 'Password2026!',
    'role': 'employee',
    'employee_id': 'EMP-CAND-001',
    'department': 'Product Engineering',
    'designation': 'Software Engineer',
    'office_id': 1
}
r1 = s.post('http://127.0.0.1:5000/register', data=reg_data, allow_redirects=True)
print('1. Registration Redirect URL:', r1.url)

# 2. Attempt login as the pending user
s_pending = requests.Session()
r2 = s_pending.post('http://127.0.0.1:5000/login', data={'email': 'candidate.emp@company.com', 'password': 'Password2026!'}, allow_redirects=True)
print('2. Pending Login Result URL:', r2.url)
print('   Has awaiting approval notice:', 'awaiting administrator approval' in r2.text)

# 3. Log in as Administrator and check pending list
s_admin = requests.Session()
r3 = s_admin.post('http://127.0.0.1:5000/login', data={'email': 'admin@company.com', 'password': 'admin123'}, allow_redirects=True)
r_admin_page = s_admin.get('http://127.0.0.1:5000/admin')
print('3. Admin Console shows pending applicant:', 'Test Candidate Employee' in r_admin_page.text)

# 4. Find user id and approve
with sqlite3.connect('expenses.db') as con:
    con.row_factory = sqlite3.Row
    user = con.execute("SELECT id, status FROM users WHERE email='candidate.emp@company.com'").fetchone()
    print('4. Candidate user record before approval:', dict(user))

r4 = s_admin.post(f"http://127.0.0.1:5000/admin/users/{user['id']}/approve", allow_redirects=True)
print('   Admin approve HTTP status:', r4.status_code)

with sqlite3.connect('expenses.db') as con:
    con.row_factory = sqlite3.Row
    user_after = con.execute("SELECT id, status, is_active FROM users WHERE email='candidate.emp@company.com'").fetchone()
    print('   Candidate user record after approval:', dict(user_after))

# 5. Now log in as the approved employee
s_approved = requests.Session()
r5 = s_approved.post('http://127.0.0.1:5000/login', data={'email': 'candidate.emp@company.com', 'password': 'Password2026!'}, allow_redirects=True)
print('5. Approved user login destination:', r5.url)
print('   Successfully redirected to dashboard:', '/dashboard' in r5.url)
