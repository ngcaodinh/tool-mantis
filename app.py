"""
MantisBT Bulk Bug Import Tool - Flask Web Application
Runs on http://0.0.0.0:5030
"""

import json
import logging
import time
import uuid
from flask import (
    Flask, render_template, request, jsonify,
    Response, stream_with_context
)
from mantis_client import MantisBTClient
from config import (
    HOST, PORT, SESSION_DIR, DEFAULT_DELAY,
    REQUIRED_COLUMNS, OPTIONAL_COLUMNS
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mantisbt-import-secret-key-2026'

# Show debug logs from mantisbt client in Flask console
logging.basicConfig(level=logging.DEBUG, format='[%(name)s] %(message)s')
logging.getLogger('mantisbt_fetch_projects').setLevel(logging.DEBUG)
# Also show requests redirect info
logging.getLogger('urllib3').setLevel(logging.WARNING)

# In-memory client registry: session_id -> client instance
_active_clients: dict = {}


def get_client(session_id: str) -> MantisBTClient | None:
    return _active_clients.get(session_id)


def parse_json(json_text: str, default_category_id: str = '') -> tuple:
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        return [], [f'JSON không hợp lệ: {e}']

    if isinstance(data, dict):
        data = [data]
    elif not isinstance(data, list):
        return [], ['JSON phải là một mảng objects hoặc một object duy nhất']

    errors = []
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            errors.append(f'Phần tử #{i}: Không phải object')
            continue
        
        # Điền category_id mặc định từ UI nếu trong JSON không có hoặc trống
        if ('category_id' not in item or not str(item['category_id']).strip() or str(item['category_id']) == '0') and default_category_id and default_category_id != '0':
            item['category_id'] = default_category_id

        for col in REQUIRED_COLUMNS:
            if col not in item or not str(item[col]).strip():
                errors.append(f'Phần tử #{i}: Thiếu trường bắt buộc "{col}"')

    return data, errors


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/test-connection', methods=['POST'])
def test_connection():
    data = request.get_json()
    url = data.get('url', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not url:
        return jsonify({'success': False, 'message': 'Vui lòng nhập URL MantisBT'})

    client = MantisBTClient(url)
    result = client.test_connection()

    if not result['success']:
        return jsonify(result)

    if username and password:
        login_result = client.login(username, password)
        if login_result['success']:
            session_id = client.session_id
            _active_clients[session_id] = client

            # Try to fetch projects list right after login
            projects_result = client.fetch_projects()
            return jsonify({
                'success': True,
                'message': f'{result["message"]} | Đăng nhập thành công với user "{username}"',
                'session_id': session_id,
                'projects': projects_result.get('projects', []),
                'projects_error': projects_result.get('message') if not projects_result.get('success') else None
            })
        return jsonify(login_result)

    return jsonify(result)


@app.route('/api/projects', methods=['POST'])
def fetch_projects():
    data = request.get_json() or {}
    session_id = data.get('session_id', '').strip()
    if not session_id or session_id not in _active_clients:
        return jsonify({'success': False, 'message': 'Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại', 'projects': []})

    client = _active_clients[session_id]
    result = client.fetch_projects()
    return jsonify(result)


@app.route('/api/categories', methods=['POST'])
def fetch_categories():
    data = request.get_json() or {}
    session_id = data.get('session_id', '').strip()
    project_id = str(data.get('project_id', '')).strip()
    if not session_id or session_id not in _active_clients:
        return jsonify({'success': False, 'message': 'Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại', 'categories': []})
    if not project_id:
        return jsonify({'success': False, 'message': 'Thiếu Project ID', 'categories': []})

    client = _active_clients[session_id]
    result = client.fetch_categories(project_id)
    return jsonify(result)


@app.route('/api/logout', methods=['POST'])
def logout():
    data = request.get_json() or {}
    session_id = data.get('session_id', '').strip()
    if not session_id:
        return jsonify({'success': False, 'message': 'Thiếu session_id'})

    removed = False
    if session_id in _active_clients:
        client = _active_clients.pop(session_id)
        try:
            client.delete_session()
        except Exception:
            pass
        removed = True

    if removed:
        return jsonify({'success': True, 'message': 'Đã đăng xuất và xóa session'})
    return jsonify({'success': True, 'message': 'Session không tồn tại (đã được dọn)'})


@app.route('/api/import', methods=['POST'])
def import_bugs():
    data = request.get_json()
    url = data.get('url', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    json_data = data.get('json_data', '')
    delay = float(data.get('delay', DEFAULT_DELAY))
    session_id = data.get('session_id', '')
    project_id = str(data.get('project_id', '0')).strip()
    category_id = str(data.get('category_id', '0')).strip()

    # Get or create client
    if session_id and session_id in _active_clients:
        client = _active_clients[session_id]
        if client.base_url.rstrip('/') != url.rstrip('/'):
            client = MantisBTClient(url, session_id)
            _active_clients[session_id] = client
    else:
        client = MantisBTClient(url, session_id or str(uuid.uuid4()))
        if session_id:
            _active_clients[session_id] = client

    def generate():
        # Login
        yield _sse({'type': 'status', 'message': 'Đang đăng nhập...', 'step': 'login'})

        if not username or not password:
            yield _sse({
                'type': 'error', 'message': 'Thiếu username hoặc password',
                'step': 'done', 'final': True
            })
            return

        login_result = client.login(username, password)
        if not login_result['success']:
            yield _sse({
                'type': 'error', 'message': f'Đăng nhập thất bại: {login_result["message"]}',
                'step': 'done', 'final': True
            })
            return

        yield _sse({'type': 'status', 'message': 'Đăng nhập thành công', 'step': 'parse'})

        # Parse JSON
        rows, parse_errors = parse_json(json_data, category_id)
        if parse_errors:
            for err in parse_errors:
                yield _sse({'type': 'error', 'message': err})
            yield _sse({
                'type': 'error',
                'message': 'Dừng import do lỗi JSON',
                'step': 'done',
                'final': True
            })
            return

        if not rows:
            yield _sse({
                'type': 'error', 'message': 'File JSON trống hoặc không có dữ liệu',
                'step': 'done', 'final': True
            })
            return

        total = len(rows)
        success_count = 0
        failed_count = 0
        results = []

        yield _sse({
            'type': 'status',
            'message': f'Bắt đầu import {total} bug...',
            'step': 'import',
            'total': total
        })

        # Preflight: ensure we can open bug report form (project selected / session OK).
        # Per-bug CSRF is fetched inside submit_bug (Mantis purges token after each success).
        csrf_ok = client.fetch_csrf_token(project_id if project_id and project_id != '0' else '')
        if not csrf_ok:
            yield _sse({
                'type': 'error',
                'message': 'Không lấy được CSRF token từ MantisBT. Hãy chọn Project trước khi import.',
                'step': 'done',
                'final': True
            })
            return

        for i, row in enumerate(rows, start=1):
            row_num = i

            # Báo UI biết đang bắt đầu dòng này (progress bar nhích trước khi HTTP xong)
            yield _sse({
                'type': 'status',
                'message': f'Đang gửi issue {i}/{total}: {(row.get("summary") or "")[:80]}',
                'step': 'import',
                'row': i,
                'total': total,
            })

            fields = {}
            for col in list(row.keys()):
                raw = row.get(col)
                if raw is None:
                    continue
                # JSON may contain lists (e.g. monitors: []) or numbers — never call .strip() blindly
                if isinstance(raw, list):
                    if col == 'monitors':
                        mon = [str(x).strip() for x in raw if x is not None and str(x).strip() != '']
                        if mon:
                            fields[col] = mon
                    else:
                        joined = ','.join(str(x).strip() for x in raw if x is not None and str(x).strip() != '')
                        if joined:
                            fields[col] = joined
                    continue
                if isinstance(raw, (int, float, bool)):
                    fields[col] = str(raw)
                    continue
                val = str(raw).strip()
                if val:
                    fields[col] = val

            # Alias: README uses "tags", form field is tag_string
            if 'tag_string' not in fields and fields.get('tags'):
                fields['tag_string'] = fields['tags']

            # Inject project_id from dropdown (priority: row's own project_id > dropdown selection)
            if 'project_id' not in fields or not fields['project_id'] or fields['project_id'] == '0':
                if project_id and project_id != '0':
                    fields['project_id'] = project_id

            # Ensure required fields
            if 'summary' not in fields or not fields['summary']:
                fields['summary'] = f'Bug import #{i}'
            if 'description' not in fields or not fields['description']:
                fields['description'] = fields.get('summary', '')
            if 'category_id' not in fields or not fields['category_id'] or fields['category_id'] == '0':
                if category_id and category_id != '0':
                    fields['category_id'] = category_id
                else:
                    fields['category_id'] = '1'

            time.sleep(delay)

            result = client.submit_bug(fields)
            bug_id = result.get('bug_id')
            error = result.get('error')

            if result['success']:
                success_count += 1
                status = 'success'
                status_text = f'Bug #{bug_id}'
            else:
                failed_count += 1
                status = 'failed'
                status_text = error or 'Lỗi không xác định'

            row_result = {
                'row': row_num,
                'summary': fields.get('summary', '')[:80],
                'status': status,
                'bug_id': bug_id,
                'error': error,
                'status_text': status_text
            }
            results.append(row_result)

            progress = int((i / total) * 100)
            yield _sse({
                'type': 'progress',
                'row': row_num,
                'total': total,
                'progress': progress,
                'success_count': success_count,
                'failed_count': failed_count,
                'result': row_result
            })

        # Final summary
        success_rate = round((success_count / total) * 100, 1) if total > 0 else 0
        yield _sse({
            'type': 'done',
            'step': 'done',
            'final': True,
            'total': total,
            'success_count': success_count,
            'failed_count': failed_count,
            'success_rate': success_rate,
            'base_url': url,
            'results': results
        })

    # SSE: tắt buffer để progress hiện realtime trên UI (không dồn 1 cục cuối)
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-transform',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
            'Content-Type': 'text/event-stream; charset=utf-8',
        },
        direct_passthrough=False,
    )


def _sse(data: dict) -> str:
    return f"data: {__import__('json').dumps(data)}\n\n"


if __name__ == '__main__':
    print(f"Starting MantisBT Import Tool at http://{HOST}:{PORT}")
    print(f"Open http://localhost:{PORT} in your browser")
    print("DEBUG mode ON — server will auto-reload on code changes")
    app.run(host=HOST, port=PORT, debug=True, threaded=True, use_reloader=True)
