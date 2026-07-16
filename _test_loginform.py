import requests
import re

s = requests.Session()
BASE = 'http://localhost/mantisbt-2.25.5'

# Get login page
r = s.get(f'{BASE}/login_page.php')
print('Status:', r.status_code)
# Find all hidden inputs in login form
idx = r.text.find('<form')
end = r.text.find('</form>', idx)
form_html = r.text[idx:end+7]
inputs = re.findall(r'<input[^>]+>', form_html)
print('Login form inputs:')
for inp in inputs:
    print(' ', inp[:200])

# Find any error messages
m = re.findall(r'class=["\']alert[^>]*>.*?</div>', r.text, re.DOTALL)
print('\nAlerts in page:')
for a in m[:3]:
    print(' ', a[:300])