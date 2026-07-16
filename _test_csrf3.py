import requests
import re

s = requests.Session()
BASE = 'http://localhost/mantisbt-2.25.5'

# First get login page
r = s.get(f'{BASE}/login_page.php')
print(f'login_page: status={r.status_code}')
html = r.text
# Check for CSRF in login form
m = re.search(r'<input[^>]+name=["\']login_token["\'][^>]+value=["\']([^"\']+)["\']', html, re.IGNORECASE)
print('login_token:', m.group(1)[:30] if m else 'NOT FOUND')

# Also check for cookie-set
print('Cookies:', dict(s.cookies))

# Try login with token
if m:
    data = {'username': 'administrator', 'password': 'root', 'login_token': m.group(1)}
else:
    data = {'username': 'administrator', 'password': 'root'}

r = s.post(f'{BASE}/login.php', data=data, allow_redirects=True)
print(f'After login: status={r.status_code} url={r.url[-80:]}')

# Check session
r = s.get(f'{BASE}/my_view_page.php', allow_redirects=True)
print(f'my_view_page: status={r.status_code} url={r.url[-80:]}')
if 'login' in r.url:
    print('STILL NOT LOGGED IN')