"""
MantisBT HTTP Client - handles login, CSRF token scraping, and bug submission.
"""

import re
import os
import json
import time
import logging
import requests
from bs4 import BeautifulSoup
from typing import Optional

# Debug logger for fetch_projects
_logger = logging.getLogger('mantisbt_fetch_projects')
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
_logger.addHandler(_handler)
_logger.setLevel(logging.DEBUG)

try:
    from config import SESSION_DIR, DEFAULT_DELAY, CSRF_REFRESH_EVERY
except ImportError:
    SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sessions')
    DEFAULT_DELAY = 0.5
    CSRF_REFRESH_EVERY = 10


class MantisBTClient:
    """HTTP client for MantisBT web form interaction."""

    CSRF_INPUT_PATTERN = re.compile(
        r'<input[^>]+name=["\']bug_report_token["\'][^>]+value=["\']([^"\']+)["\']',
        re.IGNORECASE
    )

    # Also try this pattern if the above doesn't match
    CSRF_INPUT_PATTERN_ALT = re.compile(
        r'name=["\']bug_report_token["\'][^>]*value=["\']([^"\']+)["\']',
        re.IGNORECASE
    )

    LOCATION_BUG_PATTERN = re.compile(r'bug_view_page\.php\?id=(\d+)', re.IGNORECASE)

    # MantisBT 2.x often returns HTTP 200 confirmation page (meta-refresh) instead of 302.
    # ONLY match the confirmation wording — never generic bug_view links (Recently Visited).
    # Example: "Operation successful. View Submitted Issue 31"
    SUCCESS_BUG_ID_PATTERNS = [
        re.compile(r'View\s+Submitted\s+Issue\s+(\d+)', re.IGNORECASE),
        re.compile(
            r'Operation\s+successful[.\s]*View\s+Submitted\s+Issue\s+(\d+)',
            re.IGNORECASE,
        ),
    ]

    # Pattern for MantisBT project dropdown: <option value="123" ... >Name</option>
    PROJECT_OPTION_PATTERN = re.compile(
        r'<option[^>]+value=["\'](\d+)["\'][^>]*>(.*?)</option>',
        re.IGNORECASE | re.DOTALL
    )

    # Pattern for MantisBT project dropdown inside <select name="project_id">...</select>
    PROJECT_SELECT_PATTERN = re.compile(
        r'<select[^>]+name=["\']project_id["\'][^>]*>(.*?)</select>',
        re.IGNORECASE | re.DOTALL
    )

    ERROR_PATTERNS = [
        re.compile(r'class=["\']alert alert-danger["\'][^>]*>(.*?)</div>', re.DOTALL | re.IGNORECASE),
        re.compile(r'class=["\']error["\'][^>]*>(.*?)</p>', re.DOTALL | re.IGNORECASE),
        re.compile(r'ERROR_FORM_TOKEN_INVALID', re.IGNORECASE),
        re.compile(r'ERROR_(\w+)', re.IGNORECASE),
    ]

    # Fallback mappings for MantisBT enum strings (int:label).
    # Mirrors config_defaults_inc.php $g_*_enum_string defaults.
    # Multiple labels per int handle localization variants.
    ENUM_MAPS = {
        'severity':         {10: 'feature', 20: 'trivial', 30: 'text',  40: 'tweak',
                             50: 'minor',    60: 'major',   70: 'crash', 80: 'block'},
        'reproducibility':  {10: 'always',  30: 'sometimes', 50: 'random', 70: 'have not tried',
                             90: 'unable to duplicate', 100: 'N/A'},
        'priority':         {10: 'none', 20: 'low', 30: 'normal', 40: 'high', 50: 'urgent', 60: 'immediate'},
        'eta':              {10: 'none', 20: '< 1 day', 30: '2-3 days', 40: '< 1 week', 50: '< 1 month', 60: '> 1 month'},
        'projection':       {10: 'none', 30: 'tweak', 50: 'minor fix', 70: 'major rework', 90: 'redesign'},
        'resolution':       {10: 'open', 20: 'fixed', 30: 'reopened', 40: 'unable to reproduce',
                             50: 'not fixable', 60: 'duplicate', 70: 'no change required',
                             80: 'suspended', 90: 'won\'t fix'},
        'status':           {10: 'new', 20: 'feedback', 30: 'acknowledged', 40: 'confirmed',
                             50: 'assigned', 80: 'resolved', 90: 'closed'},
        'view_state':       {10: 'public', 50: 'private'},
    }

    def __init__(self, base_url: str, session_id: str = ''):
        self.base_url = base_url.rstrip('/')
        self.session_id = session_id or self._generate_session_id()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'MantisBT-Import-Tool/1.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        self._csrf_token: str = ''
        self._logged_in: bool = False

    @classmethod
    def _enum_norm(cls, field: str, value, default: int = 0) -> int:
        """Normalize an enum value (label, int, str-int) -> int key.

        Lookup order:
          1. Try parse as integer (if int/float or numeric string).
          2. If string label: search ENUM_MAPS[field] reverse (case-insensitive,
             whitespace-tolerant).
          3. Fallback to default.
        Returns MantisBT enum int key.
        """
        if value is None or value == '':
            return default

        s = str(value).strip()
        if not s:
            return default

        # 1. Numeric fast-path (int or numeric string)
        try:
            return int(s)
        except (ValueError, TypeError):
            pass

        # 2. Label lookup
        enum_map = cls.ENUM_MAPS.get(field)
        if enum_map:
            needle = s.lower()
            for k, label in enum_map.items():
                if label.lower() == needle:
                    return k

        # 3. Unknown label → default (caller can decide to warn)
        return default

    @staticmethod
    def _generate_session_id() -> str:
        import uuid
        return str(uuid.uuid4())

    def _session_file_path(self) -> str:
        safe_id = self.session_id.replace('-', '_')
        return os.path.join(SESSION_DIR, f'mantis_session_{safe_id}.json')

    def _save_session(self):
        path = self._session_file_path()
        meta_path = path.replace('.json', '_meta.json')
        try:
            # Serialize cookies via dict (RequestsCookieJar is dict-compatible)
            cookies_dict = {name: None for name in self.session.cookies.keys()}
            for name in self.session.cookies.keys():
                try:
                    cookies_dict[name] = self.session.cookies.get(name)
                except Exception:
                    cookies_dict[name] = None

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cookies_dict, f)

            with open(meta_path, 'w', encoding='utf-8') as mf:
                json.dump({
                    'base_url': self.base_url,
                    'session_id': self.session_id,
                    'logged_in': self._logged_in,
                }, mf)

            self._cleanup_old_sessions()
        except Exception as e:
            print(f'[_save_session] warning: {e}')

    def _cleanup_old_sessions(self):
        try:
            if not os.path.exists(SESSION_DIR):
                return
            files = []
            for name in os.listdir(SESSION_DIR):
                filepath = os.path.join(SESSION_DIR, name)
                if os.path.isfile(filepath):
                    files.append((filepath, os.path.getmtime(filepath)))
            
            # Sắp xếp các file theo thời gian chỉnh sửa (mtime) cũ nhất lên đầu
            files.sort(key=lambda x: x[1])
            
            # Xóa các file cũ nhất cho đến khi chỉ còn tối đa 5 file
            while len(files) > 5:
                oldest_file, _ = files.pop(0)
                try:
                    os.remove(oldest_file)
                except Exception as e:
                    print(f'[_cleanup_old_sessions] error removing {oldest_file}: {e}')
        except Exception as e:
            print(f'[_cleanup_old_sessions] error: {e}')

    def _load_session(self) -> bool:
        path = self._session_file_path()
        if not os.path.exists(path):
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cookies_dict = json.load(f)

            if isinstance(cookies_dict, dict):
                for name, value in cookies_dict.items():
                    if value is None:
                        continue
                    self.session.cookies.set(name, value, domain=self.base_url.lstrip('http://').lstrip('https://').split('/')[0])

            meta_path = path.replace('.json', '_meta.json')
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as mf:
                    data = json.load(mf)
                    self.base_url = data.get('base_url', self.base_url)
                    self._logged_in = data.get('logged_in', False)
            return True
        except Exception as e:
            print(f'[_load_session] warning: {e}')
            return False

    def test_connection(self) -> dict:
        try:
            resp = self.session.get(self.base_url, timeout=15)
            if resp.status_code == 200:
                return {'success': True, 'message': 'Kết nối thành công'}
            return {'success': False, 'message': f'HTTP {resp.status_code}'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def login(self, username: str, password: str) -> dict:
        try:
            login_url = f'{self.base_url}/login.php'
            data = {
                'username': username,
                'password': password,
            }
            resp = self.session.post(login_url, data=data, allow_redirects=False, timeout=15)
            if resp.status_code in (302, 303):
                redirect_location = resp.headers.get('Location', '')
                if 'login' in redirect_location and 'error=1' in redirect_location:
                    return {'success': False, 'message': 'Tên đăng nhập hoặc mật khẩu không đúng'}
                self._logged_in = True
                self._save_session()
                return {'success': True, 'message': 'Đăng nhập thành công'}
            if resp.status_code == 200:
                if 'error' in resp.text.lower() or 'incorrect' in resp.text.lower():
                    return {'success': False, 'message': 'Tên đăng nhập hoặc mật khẩu không đúng'}
            return {'success': False, 'message': f'Unexpected response: {resp.status_code}'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def is_logged_in(self) -> bool:
        try:
            resp = self.session.get(
                f'{self.base_url}/bug_report_page.php',
                timeout=10,
                allow_redirects=False
            )
            if resp.status_code == 200:
                if 'login' not in resp.request.url.lower() or 'login_page' not in resp.url:
                    self._logged_in = True
                    return True
            elif resp.status_code in (302, 303):
                location = resp.headers.get('Location', '')
                if 'login' not in location:
                    self._logged_in = True
                    return True
            self._logged_in = False
            return False
        except Exception:
            self._logged_in = False
            return False

    def fetch_projects(self) -> dict:
        # Helper to parse a MantisBT page that contains <select name="project_id">
        def _parse_projects_from_html(html: str) -> list:
            projects = []
            # Strategy 1: <select name="project_id">...</select>
            select_match = self.PROJECT_SELECT_PATTERN.search(html)
            candidates = select_match.group(1) if select_match else ''
            for match in self.PROJECT_OPTION_PATTERN.finditer(candidates):
                pid = match.group(1).strip()
                name = re.sub(r'<[^>]+>', '', match.group(2)).replace('\xa0', ' ').strip()
                if not name or name.lower() in ('select a project', '-- select --',
                                                'choose a project', 'select project'):
                    continue
                if any(p['id'] == pid for p in projects):
                    continue
                projects.append({'id': pid, 'name': name})
            # Strategy 2: JSON array in <script>
            if not projects:
                for js_pattern in [
                    r'project_list\s*[:=]\s*(\[.*?\])\s*[,;]',
                    r'var\s+projects\s*=\s*(\[.*?\])\s*[,;]',
                ]:
                    m = re.search(js_pattern, html, re.DOTALL)
                    if m:
                        try:
                            for item in json.loads(m.group(1)):
                                pid = str(item.get('id') or item.get('project_id') or '').strip()
                                name = str(item.get('name') or item.get('project_name') or '').strip()
                                if pid and name and not any(p['id'] == pid for p in projects):
                                    projects.append({'id': pid, 'name': name})
                        except Exception:
                            pass
            return projects

        try:
            # 1) MantisBT 2.x with project selection ON: login flow goes via
            #    login_select_proj_page.php which contains <select name="project_id">.
            #    Try it FIRST since this is the most common in modern installs.
            _logger.debug("fetch_projects: trying login_select_proj_page.php first")
            try:
                resp_sel = self.session.get(
                    f'{self.base_url}/login_select_proj_page.php',
                    timeout=15
                )
                _logger.debug(f"fetch_projects: select_proj status={resp_sel.status_code} url={resp_sel.url}")
                if resp_sel.status_code == 200 and 'login_select_proj_page' in resp_sel.url \
                        and 'project_id' in resp_sel.text:
                    projects = _parse_projects_from_html(resp_sel.text)
                    _logger.debug(f"fetch_projects: parsed {len(projects)} projects from login_select_proj_page")
                    if projects:
                        return {
                            'success': True,
                            'message': f'Tải thành công {len(projects)} project (từ login_select_proj_page)',
                            'projects': projects
                        }
            except Exception as e:
                _logger.debug(f"fetch_projects: select_proj exception: {e}")

            # 2) Fallback: try bug_report_page.php directly (no project selection required)
            resp = self.session.get(
                f'{self.base_url}/bug_report_page.php',
                timeout=15
            )
            final_url = resp.url
            _logger.debug(f"fetch_projects: status={resp.status_code} final_url={final_url}")

            # Detect redirect to login — session expired
            if 'login' in final_url.lower() or 'login_page' in final_url.lower() \
                    or 'login_select_proj_page' in final_url.lower():
                _logger.debug("fetch_projects: redirected away from bug_report_page")
                # If still on select_proj without projects, session is OK but
                # we couldn't read project_id on this page — try once more.
                if 'login_select_proj_page' in final_url:
                    projects = _parse_projects_from_html(resp.text)
                    if projects:
                        return {
                            'success': True,
                            'message': f'Tải thành công {len(projects)} project',
                            'projects': projects
                        }
                return {
                    'success': False,
                    'message': 'Session hết hạn, vui lòng đăng nhập lại',
                    'projects': []
                }

            if resp.status_code != 200:
                return {
                    'success': False,
                    'message': f'MantisBT trả HTTP {resp.status_code} khi tải trang tạo bug',
                    'projects': []
                }

            html = resp.text
            projects = _parse_projects_from_html(html)

            # ---- Strategy 3: SOAP API project list (MantisBT 1.3+) ----
            if not projects:
                try:
                    soap_resp = self.session.get(
                        f'{self.base_url}/api/soap/project_list.php',
                        timeout=10
                    )
                    if soap_resp.status_code == 200:
                        projects = _parse_projects_from_html(soap_resp.text)
                except Exception:
                    pass

            _logger.debug(f"fetch_projects: final parsed {len(projects)} projects: {projects}")

            if not projects:
                return {
                    'success': False,
                    'message': 'Không tìm thấy project nào trong trang MantisBT. '
                               'Bạn có thể chưa được cấp quyền vào project nào.',
                    'projects': []
                }

            return {
                'success': True,
                'message': f'Tải thành công {len(projects)} project',
                'projects': projects
            }
        except Exception as e:
            _logger.debug(f"fetch_projects: exception: {e}")
            return {'success': False, 'message': str(e), 'projects': []}

    def fetch_csrf_token(self, project_id: str = '') -> Optional[str]:
        """Load bug_report_page and scrape bug_report_token.

        When project_id is set, request that project's form so the hidden
        project_id and available categories match the import target.
        """
        try:
            url = f'{self.base_url}/bug_report_page.php'
            params = {}
            if project_id and str(project_id) not in ('', '0'):
                params['project_id'] = str(project_id)
            resp = self.session.get(url, params=params or None, timeout=15)
            if resp.status_code != 200:
                return None

            # Redirected to login or project picker — no usable form token
            final = (resp.url or '').lower()
            if 'login_page' in final or 'login_select_proj' in final:
                return None

            html = resp.text

            for pattern in [self.CSRF_INPUT_PATTERN, self.CSRF_INPUT_PATTERN_ALT]:
                match = pattern.search(html)
                if match:
                    token = match.group(1).strip()
                    if token and len(token) > 10:
                        self._csrf_token = token
                        return token

            soup = BeautifulSoup(html, 'html.parser')
            token_input = soup.find('input', {'name': 'bug_report_token'})
            if token_input and token_input.get('value'):
                self._csrf_token = token_input['value']
                return self._csrf_token

            return None
        except Exception:
            return None

    def _parse_error(self, html: str) -> str:
        for pattern in self.ERROR_PATTERNS:
            match = pattern.search(html)
            if match:
                text = match.group(1) if match.lastindex else match.group(0)
                text = BeautifulSoup(text, 'html.parser').get_text(strip=True)
                if text:
                    return text[:300]
        # Fallback: extract APPLICATION ERROR block from plain text
        text = BeautifulSoup(html, 'html.parser').get_text(' ', strip=True)
        m = re.search(
            r'APPLICATION ERROR\s*#?\d*\s*(.{10,280}?)(?:Please use|Powered by|$)',
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            return re.sub(r'\s+', ' ', m.group(0)).strip()[:300]
        return 'Lỗi không xác định'

    def _check_csrf_invalid(self, html: str) -> bool:
        low = html.lower()
        return (
            'ERROR_FORM_TOKEN_INVALID' in html
            or 'form_token_invalid' in low
            or 'invalid form security token' in low
            or 'application error #2800' in low
        )

    def _extract_bug_id_from_response(self, resp) -> Optional[str]:
        """Extract created issue id from redirect Location or success HTML body.

        MantisBT 2.25.x bug_report.php typically returns HTTP 200 with
        html_meta_redirect + 'Operation successful / View Submitted Issue N'
        rather than a pure 302 Location header (when redirects are not followed).

        Important: do NOT scrape arbitrary bug_view_page.php?id= links from the
        chrome (Recently Visited) — that causes false success with stale ids.
        """
        location = resp.headers.get('Location', '') or ''
        m = self.LOCATION_BUG_PATTERN.search(location)
        if m:
            return m.group(1)

        body = resp.text or ''
        # Prefer plain-text confirmation label (works even if markup changes)
        text = BeautifulSoup(body, 'html.parser').get_text(' ', strip=True)
        for pattern in self.SUCCESS_BUG_ID_PATTERNS:
            m = pattern.search(text) or pattern.search(body)
            if m:
                return m.group(1)

        # Meta refresh only when confirmation page also says success
        if 'operation successful' in text.lower() or 'view submitted issue' in text.lower():
            m = re.search(
                r'content=["\']?\d+\s*;\s*url=([^"\'>\s]+)',
                body,
                re.IGNORECASE,
            )
            if m:
                target = m.group(1)
                m2 = self.LOCATION_BUG_PATTERN.search(target)
                if m2:
                    return m2.group(1)
                m2 = re.search(r'[?&]id=(\d+)', target)
                if m2:
                    return m2.group(1)
        return None

    # Canonical payload field order, mirrors MantisBT 2.25.5
    # bug_report_page.php form layout (Enter Issue Details panel).
    # Server-side: encodes order in HTTP body for log readability.
    PAYLOAD_ORDER = [
        'bug_report_token', 'm_id', 'project_id',
        'category_id', 'reproducibility', 'eta', 'severity', 'priority',
        'due_date', 'profile_id',
        'platform', 'os', 'os_build',
        'product_version', 'build',
        'handler_id', 'monitors',
        'status', 'resolution', 'target_version',
        'summary', 'description',
        'steps_to_reproduce', 'additional_info',
        'tag_string', 'view_state',
    ]

    @classmethod
    def _ordered_payload(cls, payload: dict) -> list:
        """Return payload items in canonical form order, then any extra keys."""
        ordered_keys = [k for k in cls.PAYLOAD_ORDER if k in payload]
        extra_keys = [k for k in payload if k not in cls.PAYLOAD_ORDER]
        return [(k, payload[k]) for k in ordered_keys + extra_keys]

    def submit_bug(self, fields: dict) -> dict:
        # project_id: required by MantisBT bug_report.php form
        project_id = fields.get('project_id', '0')

        def _str(v):
            """Normalize value to non-empty string; empty -> ''."""
            if v is None or v == '':
                return ''
            if isinstance(v, list):
                return ','.join(str(x) for x in v if x is not None and str(x).strip() != '')
            return str(v)

        def _build_form_data(csrf_token: str) -> list:
            """Build multipart/urlencoded pairs matching Enter Issue Details form.

            Uses list of tuples so multi-value fields (monitors[]) work like
            bug_report_page.php: <select name=\"monitors[]\" multiple>.
            """
            pairs = [
                ('bug_report_token', csrf_token or ''),
                ('m_id', str(self._enum_norm('m_id', fields.get('m_id', 0), 0))),
                ('project_id', _str(project_id)),
                ('category_id', str(self._enum_norm('category_id', fields.get('category_id'), 1))),
                ('reproducibility', str(self._enum_norm('reproducibility', fields.get('reproducibility'), 10))),
                ('eta', str(self._enum_norm('eta', fields.get('eta'), 10))),
                ('severity', str(self._enum_norm('severity', fields.get('severity'), 50))),
                ('priority', str(self._enum_norm('priority', fields.get('priority'), 30))),
                ('due_date', _str(fields.get('due_date', ''))),
                ('profile_id', str(self._enum_norm('profile_id', fields.get('profile_id'), 0))),
                ('platform', _str(fields.get('platform', ''))),
                ('os', _str(fields.get('os', ''))),
                ('os_build', _str(fields.get('os_build', ''))),
                ('product_version', _str(fields.get('product_version', fields.get('version', '')))),
                ('build', _str(fields.get('build', ''))),
                ('handler_id', str(self._enum_norm('handler_id', fields.get('handler_id'), 0))),
                ('target_version', _str(fields.get('target_version', ''))),
                ('status', str(self._enum_norm('status', fields.get('status'), 10))),
                ('resolution', str(self._enum_norm('resolution', fields.get('resolution'), 10))),
                ('summary', _str(fields.get('summary', ''))),
                ('description', _str(fields.get('description', ''))),
                ('steps_to_reproduce', _str(fields.get('steps_to_reproduce', ''))),
                ('additional_info', _str(fields.get('additional_info', ''))),
                ('tag_string', _str(fields.get('tag_string', fields.get('tags', '')))),
                ('view_state', str(self._enum_norm('view_state', fields.get('view_state'), 10))),
                ('report_stay', '0'),
            ]

            # monitors[] — only when non-empty (empty list must not be posted as scalar)
            monitors_raw = fields.get('monitors')
            monitor_ids = []
            if isinstance(monitors_raw, list):
                monitor_ids = [str(x).strip() for x in monitors_raw if str(x).strip() not in ('', '0')]
            elif monitors_raw not in (None, '', 0, '0'):
                # allow "1,2,3" or single id
                monitor_ids = [p.strip() for p in str(monitors_raw).replace(';', ',').split(',') if p.strip()]
            for mid in monitor_ids:
                pairs.append(('monitors[]', mid))

            for key, value in fields.items():
                if key.startswith('custom_field_'):
                    pairs.append((key, value if value is not None else ''))

            return pairs

        try:
            # Always take a fresh CSRF token for this project before submit.
            # Mantis purges the token after each successful bug_report.
            token = self.fetch_csrf_token(_str(project_id)) or self._csrf_token
            if not token:
                return {
                    'success': False,
                    'bug_id': None,
                    'error': 'Không lấy được CSRF token (chưa chọn project hoặc session hết hạn)',
                }

            form_data = _build_form_data(token)
            resp = self.session.post(
                f'{self.base_url}/bug_report.php',
                data=form_data,
                allow_redirects=False,
                timeout=30
            )

            bug_id = self._extract_bug_id_from_response(resp)
            if bug_id:
                return {'success': True, 'bug_id': bug_id, 'error': None}

            # CSRF token invalid - retry once with a brand-new token
            if resp.status_code == 200 and self._check_csrf_invalid(resp.text):
                new_token = self.fetch_csrf_token(_str(project_id))
                if new_token:
                    form_data = _build_form_data(new_token)
                    resp = self.session.post(
                        f'{self.base_url}/bug_report.php',
                        data=form_data,
                        allow_redirects=False,
                        timeout=30
                    )
                    bug_id = self._extract_bug_id_from_response(resp)
                    if bug_id:
                        return {'success': True, 'bug_id': bug_id, 'error': None}

            # Failure - parse error message
            if resp.status_code in (200, 302, 303):
                error_msg = self._parse_error(resp.text)
                if error_msg and 'không xác định' not in error_msg:
                    return {'success': False, 'bug_id': None, 'error': error_msg}
                # Success page text sometimes not matched — last chance
                if 'operation successful' in (resp.text or '').lower():
                    bug_id = self._extract_bug_id_from_response(resp)
                    if bug_id:
                        return {'success': True, 'bug_id': bug_id, 'error': None}
                    return {
                        'success': True,
                        'bug_id': None,
                        'error': None,
                    }

            return {'success': False, 'bug_id': None, 'error': f'HTTP {resp.status_code}'}

        except Exception as e:
            return {'success': False, 'bug_id': None, 'error': str(e)}

    @staticmethod
    def _clean_category_label(raw: str) -> str:
        """Strip Mantis prefixes like [All Projects] / [Project Name] for display."""
        name = (raw or '').strip()
        # "[All Projects] Foo" or "[CTUT fix] Foo" -> "Foo"
        name = re.sub(r'^\[[^\]]+\]\s*', '', name).strip()
        return name or raw.strip()

    def fetch_categories(self, project_id: str) -> dict:
        """Load categories available for the selected project only.

        Flow mirrors MantisUI:
          1) set current project
          2) open bug_report_page for that project
          3) scrape <select name=\"category_id\"> options
        """
        try:
            pid = str(project_id or '').strip()
            if not pid or pid == '0':
                return {
                    'success': False,
                    'message': 'Vui lòng chọn Project trước khi tải Category',
                    'categories': [],
                    'project_id': pid or '0',
                }

            # Pin current project so category list matches that project
            try:
                self.session.post(
                    f'{self.base_url}/set_project.php',
                    data={'project_id': pid, 'ref': 'bug_report_page.php'},
                    allow_redirects=True,
                    timeout=15,
                )
            except Exception:
                pass

            url = f'{self.base_url}/bug_report_page.php'
            resp = self.session.get(url, params={'project_id': pid}, timeout=15)
            if resp.status_code != 200:
                return {
                    'success': False,
                    'message': f'HTTP {resp.status_code}',
                    'categories': [],
                    'project_id': pid,
                }

            final = (resp.url or '').lower()
            if 'login_page' in final or 'login_select_proj' in final:
                return {
                    'success': False,
                    'message': 'Session hết hạn hoặc chưa chọn được project. Vui lòng đăng nhập lại.',
                    'categories': [],
                    'project_id': pid,
                }

            soup = BeautifulSoup(resp.text, 'html.parser')

            # Confirm hidden project_id on form matches selection
            hidden_proj = soup.find('input', {'name': 'project_id'})
            form_project = (hidden_proj.get('value') if hidden_proj else '') or pid

            select_el = soup.find('select', {'name': 'category_id'})
            if not select_el:
                select_el = soup.find('select', id='category_id')

            categories = []
            if select_el:
                for opt in select_el.find_all('option'):
                    val = (opt.get('value') or '').strip()
                    raw_txt = opt.get_text(' ', strip=True)
                    if not val or val == '0':
                        continue
                    low = raw_txt.lower()
                    if any(kw in low for kw in ('(select)', 'select a', 'chọn', 'choose', '--')):
                        continue
                    # Only options from this project's report form (already scoped by Mantis)
                    clean = self._clean_category_label(raw_txt)
                    is_global = raw_txt.strip().lower().startswith('[all projects]')
                    categories.append({
                        'id': val,
                        'name': clean,
                        'label': raw_txt,
                        'is_global': is_global,
                        'project_id': form_project,
                    })

            if not categories:
                return {
                    'success': False,
                    'message': (
                        f'Project ID {pid} không có category nào. '
                        'Hãy thêm Category trong Mantis: Manage → Manage Projects → Categories.'
                    ),
                    'categories': [],
                    'project_id': pid,
                }

            return {
                'success': True,
                'categories': categories,
                'project_id': pid,
                'message': f'Tải {len(categories)} category của project {pid}',
            }
        except Exception as e:
            return {
                'success': False,
                'message': str(e),
                'categories': [],
                'project_id': str(project_id or ''),
            }

    def delete_session(self):
        path = self._session_file_path()
        for f in [path, path.replace('.json', '_meta.json')]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
