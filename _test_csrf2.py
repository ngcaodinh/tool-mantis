import requests
import re

s = requests.Session()
BASE = 'http://localhost/mantisbt-2.25.5'

# Login
r = s.post(f'{BASE}/login.php', data={'username': 'administrator', 'password': 'root'}, allow_redirects=True)
print(f'Login: {r.status_code} url={r.url[-80:]}')

# Load bug report page
r = s.get(f'{BASE}/bug_report_page.php?project_id=0', allow_redirects=True)
print(f'Bug report page: status={r.status_code} url={r.url[-80:]}')

if 'login_page' in r.url:
    print('REDIRECTED TO LOGIN - session lost')
    print('--- Page snippet ---')
    idx = r.text.find('<form')
    print(r.text[idx:idx+800] if idx >= 0 else r.text[:800])
else:
    html = r.text
    # Look for CSRF token
    patterns = [
        r'<input[^>]+name=["\']bug_report_token["\'][^>]+value=["\']([^"\']+)["\']',
        r'name=["\']bug_report_token["\'][^>]*value=["\']([^"\']+)["\']',
        r'<input[^>]*value=["\']([^"\']+)["\'][^>]*name=["\']bug_report_token["\']',
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            print(f'PATTERN MATCHED: {p[:60]}...')
            print(f'Token: {m.group(1)[:50]}...')
            break
    else:
        print('NO bug_report_token in page')
        # Print first 500 chars around form
        idx = html.find('bug_report_token')
        print('Index:', idx)
        idx = html.find('form_security_field')
        print('form_security_field at:', idx)
        idx = html.find('<form')
        print('--- near <form ---')
        print(html[idx:idx+1500] if idx >= 0 else 'no form')