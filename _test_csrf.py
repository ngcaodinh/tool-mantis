import requests
import re

s = requests.Session()
BASE = 'http://localhost/mantisbt-2.25.5'

# Login
r = s.post(f'{BASE}/login.php', data={'username': 'administrator', 'password': 'root123'}, allow_redirects=True)
print(f'Login: {r.status_code} url={r.url}')

# Check if logged in - try to load bug report page
r = s.get(f'{BASE}/bug_report_page.php?project_id=0', allow_redirects=True)
print(f'Bug report page: status={r.status_code} url={r.url}')

# Search for CSRF token
patterns = [
    r'<input[^>]+name=["\']bug_report_token["\'][^>]+value=["\']([^"\']+)["\']',
    r'name=["\']bug_report_token["\'][^>]*value=["\']([^"\']+)["\']',
]
html = r.text
print(f'HTML length: {len(html)}')

# Find any bug_report_token mention
mentions = re.findall(r'[^>]*bug_report_token[^<]*', html)[:5]
print('Token mentions:', mentions[:3])

# Find form_security_field
sec = re.findall(r'form_security_field[^<]*', html)[:3]
print('form_security_field mentions:', sec)

# Find MantisBT CSRF protection
mt_sec = re.findall(r'<input[^>]*name=["\'][^"\']+["\'][^>]*type=["\']hidden["\'][^>]*>', html)
print('Hidden inputs found:', mt_sec[:5])

# Print first 50 lines of html after form
idx = html.find('<form')
if idx >= 0:
    print('--- snippet near <form ---')
    print(html[idx:idx+1500])