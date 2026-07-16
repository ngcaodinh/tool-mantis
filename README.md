# MantisBT Bulk Bug Import Tool

Ứng dụng web **Flask** giúp import hàng loạt issue/bug vào **Mantis Bug Tracker** (đã kiểm tra với MantisBT **2.25.x**) qua form web *Enter Issue Details*, không cần REST API.

Hỗ trợ đăng nhập, chọn Project/Category trên UI, dán hoặc nạp JSON, theo dõi progress realtime (overlay + bảng kết quả), và tạo issue tuần tự để tránh quá tải server.

---

## Tính năng chính

- **Đăng nhập & session:** Giữ cookie Mantis, lưu session tạm trong `sessions/` (tự dọn, tối đa ~5 file).
- **Test connection:** Kiểm tra URL + đăng nhập trước khi import.
- **Project & Category:** Tự load project; category **theo project đã chọn** (giống form Report Issue).
- **Import JSON hàng loạt:** Stream SSE — progress bar, ô “đang xử lý”, bảng kết quả realtime.
- **Overlay import:** Popup full màn khi bấm Import (không chỉ toast nhỏ).
- **CSRF & success detect:** Lấy `bug_report_token` mỗi lần submit; nhận issue ID từ trang *Operation successful / View Submitted Issue* (HTTP 200), không chỉ 302.
- **Copy nhanh trên UI:** Copy mẫu JSON, full sample, prompt AI, mô tả field, nội dung ô JSON.
- **Kiểm tra JSON:** Bắt buộc `summary` + `description` trước khi gửi.

---

## Yêu cầu

| Thành phần | Ghi chú |
|------------|---------|
| Python | 3.8+ |
| MantisBT | 2.x (khuyến nghị 2.25.x) |
| Trình duyệt | Chrome / Edge / Firefox |

---

## Cài đặt & chạy (Windows)

```cmd
cd /d "d:\CODE\Tool Manitis\mantisbt-import"

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt
python app.py
```

Mở trình duyệt:

- **http://localhost:5030**
- hoặc **http://127.0.0.1:5030**

Cổng mặc định: **5030** (`config.py`).

---

## Cách dùng nhanh

1. Nhập **URL Mantis** (vd. `http://localhost/mantisbt-2.25.5`).
2. Nhập **username / password** → **Kiểm tra kết nối**.
3. Chọn **Project** → chọn **Category** (dropdown chỉ category của project đó).
4. Dán JSON, hoặc:
   - **Load sample** / **Nạp vào ô JSON**
   - **Copy mẫu** / **Copy full sample**
5. **Áp dụng JSON** (xem trước) → **Bắt đầu Import**.
6. Theo dõi overlay progress + bảng kết quả → **Mở MantisBT** / **Import tiếp**.

> **Project** và **Category** chọn trên form UI. Không cần (và không nên) ghi `project_id` / `category_id` trong JSON mẫu mặc định.

---

## Định dạng JSON

### Bắt buộc

| Field | Kiểu | Mô tả |
|-------|------|--------|
| `summary` | string | Tiêu đề issue |
| `description` | string | Mô tả chi tiết |

### Tùy chọn (khớp form Enter Issue Details)

| Field | Ví dụ | Ghi chú |
|-------|--------|---------|
| `severity` | `minor`, `major`, `crash`, `block`… | Hoặc số enum Mantis |
| `priority` | `low`, `normal`, `high`, `urgent`… | |
| `reproducibility` | `always`, `sometimes`, `random`… | |
| `eta` | `none`, `< 1 day`, `2-3 days`… | |
| `platform` | `Web`, `Mobile Web`, `API`… | |
| `os` | `Windows 11`, `iOS 17`… | |
| `os_build` | `23H2` | |
| `due_date` | `2026-07-21` hoặc `""` | `YYYY-MM-DD` |
| `status` | `new` | |
| `resolution` | `open` | |
| `view_state` | `public`, `private` | |
| `steps_to_reproduce` | text, `\n` xuống dòng | |
| `additional_info` | text | |
| `tag_string` | `filter, tag, ui` | Tags, cách nhau bởi dấu phẩy |

**Có thể có thêm** (nâng cao): `category_id`, `project_id`, `handler_id`, `product_version`, `build`, `target_version`, `monitors`, `tags` (alias `tag_string`) — chỉ dùng khi biết đúng ID/tên trên Mantis.

**Lưu ý:**

- Để trống `product_version` nếu project **chưa có version** đó (Mantis báo *Invalid value for version*).
- `monitors: []` hợp lệ (mảng rỗng).
- Timezone hiển thị ngày trên Mantis phụ thuộc `config_inc.php` (`$g_default_timezone`, khuyến nghị `Asia/Ho_Chi_Minh` nếu dùng ở VN).

### Ví dụ (giống `samples/sample_test.json`)

```json
[
  {
    "summary": "Lọc View Issues theo tag không trả về kết quả dù issue có tag",
    "description": "Khi gắn tag 'regression' cho issue và lọc View Issues theo tag đó, danh sách trống. Issue vẫn hiện khi bỏ filter tag. Dữ liệu tag trong DB vẫn còn.",
    "severity": "major",
    "priority": "high",
    "reproducibility": "always",
    "eta": "< 1 day",
    "platform": "Web",
    "os": "Windows 11",
    "os_build": "23H2",
    "due_date": "2026-07-21",
    "status": "new",
    "resolution": "open",
    "view_state": "public",
    "steps_to_reproduce": "1. Mở một issue bất kỳ.\n2. Gắn tag regression.\n3. Vào View Issues.\n4. Filter theo tag = regression.\n5. Quan sát: danh sách rỗng dù issue vừa gắn tag.",
    "additional_info": "Tái hiện trên Chrome và Edge. Filter theo status/category vẫn hoạt động bình thường.",
    "tag_string": "filter, tag, view-issues"
  }
]
```

File mẫu đầy đủ (5 issue): [`samples/sample_test.json`](samples/sample_test.json).

---

## Cấu trúc thư mục

```text
mantisbt-import/
├── app.py                 # Flask app + API (test-connection, projects, categories, import SSE)
├── config.py              # HOST, PORT, session dir, cột bắt buộc/tùy chọn
├── mantis_client.py       # Login, CSRF, submit bug_report.php, parse project/category
├── requirements.txt
├── .gitignore
├── README.md
├── samples/
│   └── sample_test.json   # JSON mẫu (không project_id / category_id)
├── templates/
│   └── index.html         # UI (Bootstrap + JS)
└── sessions/              # Cookie session tạm (gitignore, tự dọn)
```

---

## API nội bộ (tham khảo)

| Method | Path | Mô tả |
|--------|------|--------|
| `POST` | `/api/test-connection` | Test URL + login, trả `session_id`, projects |
| `POST` | `/api/projects` | Danh sách project |
| `POST` | `/api/categories` | Category theo `project_id` đã chọn |
| `POST` | `/api/import` | Import SSE (`text/event-stream`) |
| `POST` | `/api/logout` | Xóa session |

---

## Phụ thuộc Python

```text
flask>=3.0.0
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
```

---

## Lưu ý vận hành

1. User Mantis cần quyền **Report Issue** trên project đích.
2. Nên chọn **Category** trên UI trước khi import (nếu project bắt buộc category).
3. Tăng *delay* giữa các request nếu server chậm / bị rate-limit.
4. Sau khi sửa UI, dùng **Ctrl+F5** nếu trình duyệt cache `index.html`.
5. Không commit `sessions/`, `venv/`, file `_debug_*` / `_test_*` tạm.

---

## License / nguồn

Tool import phụ trợ cho MantisBT. MantisBT giữ license riêng của dự án upstream.
