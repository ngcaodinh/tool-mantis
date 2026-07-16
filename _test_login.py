import requests

BASE = 'http://localhost/mantisbt-2.25.5'
candidates = [('administrator', 'root'), ('administrator', 'password'), ('administrator', 'admin'),
              ('administrator', 'mantis'), ('administrator', 'P@ssw0rd'),
              ('administrator', ''), ('admin', 'admin'),
              ('administrator', 'root123'), ('administrator', 'mantispassword')]

for u, p in candidates:
    s = requests.Session()
    r = s.post(f'{BASE}/login.php', data={'username': u, 'password': p}, allow_redirects=True)
    # Check if logged in: see if "logout" or username appears in next page
    ok = 'error=1' not in r.url
    print(f'  {u!r:20} {p!r:25} -> {"OK" if ok else "FAIL"} ({r.url[-60:]})')
    if ok:
        # Confirm by hitting a protected page
        r2 = s.get(f'{BASE}/my_view_page.php', allow_redirects=True)
        if 'login_page' in r2.url:
            print('    but redirected to login -> still not logged in')
        else:
            print(f'    CONFIRMED logged in -> {r2.url[-60:]}')