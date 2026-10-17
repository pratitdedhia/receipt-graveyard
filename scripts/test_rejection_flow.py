import requests
import sqlite3

s = requests.Session()

# Clean up
with sqlite3.connect('expenses.db') as con:
    con.execute("DELETE FROM users WHERE email='rejected.candidate@company.com'")
    con.commit()

# 1. Register candidate
reg_data = {
    'name': 'Rejected Candidate',
    'email': 'rejected.candidate@company.com',
    'password': 'Password2026!',
    'confirm_password': 'Password2026!',
    'role': 'accounts',
    'employee_id': 'ACC-REJ-999',
    'department': 'Finance',
    'designation': 'Accounts Officer',
    'office_id': 1,
    'reason_for_access': 'Need access to test rejections'
}
r1 = s.post('http://127.0.0.1:5000/register', data=reg_data, allow_redirects=True)
print('1. Registration redirected to:', r1.url)

with sqlite3.connect('expenses.db') as con:
    con.row_factory = sqlite3.Row
    user = con.execute("SELECT id, status FROM users WHERE email='rejected.candidate@company.com'").fetchone()

# 2. Admin rejects with reason
s_admin = requests.Session()
s_admin.post('http://127.0.0.1:5000/login', data={'email': 'admin@company.com', 'password': 'admin123'})
r_rej = s_admin.post(f"http://127.0.0.1:5000/admin/users/{user['id']}/reject", data={
    'rejection_reason': 'Unauthorized Accounts access request. Please contact your manager.'
}, allow_redirects=True)
print('2. Admin reject HTTP status:', r_rej.status_code)

# 3. User tries to login
s_user = requests.Session()
r_login = s_user.post('http://127.0.0.1:5000/login', data={
    'email': 'rejected.candidate@company.com',
    'password': 'Password2026!'
}, allow_redirects=True)
print('3. Rejected login destination:', r_login.url)
print('   Contains rejection reason:', 'Unauthorized Accounts access request' in r_login.text)
