# MantisBT Bulk Bug Import Tool

MantisBT Bulk Bug Import Tool là một ứng dụng web Flask giúp bạn nhanh chóng import hàng loạt báo cáo lỗi (bugs/issues) vào hệ thống Mantis Bug Tracker thông qua giao diện Web trực quan. 

Ứng dụng hỗ trợ kiểm tra kết nối, tự động lấy danh sách dự án (projects), kiểm tra tính hợp lệ của dữ liệu trước khi import và thực hiện gửi yêu cầu tuần tự để tránh quá tải hệ thống.

---

## 🌟 Tính năng chính

- **Đăng nhập & Quản lý Session:** Tự động duy trì trạng thái đăng nhập qua cookie. Đồng thời tự động dọn dẹp thư mục `sessions/` (giới hạn tối đa 5 file phiên làm việc mới nhất) để tiết kiệm dung lượng đĩa.
- **Kiểm tra kết nối (Test Connection):** Kiểm tra xem URL MantisBT có hoạt động hay không trước khi thực hiện import.
- **Tự động lấy danh sách dự án:** Sau khi đăng nhập thành công, hệ thống tự động tải và hiển thị danh sách các dự án khả dụng trên MantisBT.
- **Import hàng loạt:** Hỗ trợ nhập dữ liệu dạng JSON.
- **Kiểm tra dữ liệu đầu vào:** Xác thực các trường bắt buộc và định dạng của dữ liệu trước khi gửi đi.

---

## 🛠️ Yêu cầu hệ thống

- **Python:** Phiên bản 3.8 trở lên.
- **MantisBT:** Hệ thống Mantis Bug Tracker của bạn.

---

## 🚀 Hướng dẫn cài đặt và chạy trên Windows (CMD)

### Bước 1: Mở Command Prompt (cmd)
Nhấn phím `Windows`, nhập `cmd` và nhấn `Enter`.

### Bước 2: Di chuyển vào thư mục dự án
Chuyển đến thư mục chứa mã nguồn:
```cmd
cd /d "d:\CODE\Tool Manitis\mantisbt-import"
```

### Bước 3: Khởi tạo và kích hoạt môi trường ảo (Khuyến nghị)
Tạo môi trường ảo độc lập để tránh xung đột thư viện:
```cmd
python -m venv venv
venv\Scripts\activate
```

### Bước 4: Cài đặt các thư viện phụ thuộc
Cài đặt tất cả các thư viện cần thiết bằng tệp `requirements.txt`:
```cmd
pip install -r requirements.txt
```

### Bước 5: Chạy ứng dụng Flask
Khởi chạy ứng dụng bằng câu lệnh:
```cmd
python app.py
```
Sau khi khởi chạy thành công, màn hình sẽ hiển thị:
```text
 * Running on http://127.0.0.1:5030
```

### Bước 6: Truy cập giao diện
Mở trình duyệt web của bạn và truy cập địa chỉ:
👉 **[http://localhost:5030](http://localhost:5030)**

---

## 📊 Định dạng dữ liệu Import (JSON)

Dữ liệu JSON cần là một mảng các đối tượng (array of objects) hoặc một đối tượng duy nhất có các trường sau:

### Các trường bắt buộc
- `summary` (string): Tiêu đề ngắn gọn của lỗi.
- `description` (string): Mô tả chi tiết về lỗi.

### Các trường tùy chọn
- `category_id` (string/int/numeric): ID của phân loại (ví dụ: `1` cho General). Trường này là tùy chọn nếu bạn đã lựa chọn Category từ menu thả xuống trên giao diện web.
- `severity` (string/int): Độ nghiêm trọng (ví dụ: `minor`, `major`, `crash`, `block`, hoặc các mã số tương ứng).
- `priority` (string/int): Mức độ ưu tiên (ví dụ: `low`, `normal`, `high`, `urgent`, `immediate`).
- `platform` (string): Nền tảng gặp lỗi (ví dụ: `PC`, `Android`, `iOS`).
- `os` (string): Hệ điều hành (ví dụ: `Windows 11`, `macOS`).
- `os_build` (string): Bản build của hệ điều hành.
- `version` (string): Phiên bản phần mềm.
- `handler_id` (int): ID của user được phân công xử lý.
- `steps_to_reproduce` (string): Các bước tái hiện lỗi.
- `additional_info` (string): Thông tin bổ sung.
- `view_state` (string/int): Trạng thái hiển thị (`public` hoặc `private`).
- `project_id` (int): ID của dự án (nếu không chọn từ danh sách trên giao diện).
- `tags` (string): Danh sách tag, phân cách bằng dấu phẩy (ví dụ: `bug, ui, critical`).

#### Ví dụ mẫu JSON:
```json
[
  {
    "summary": "Lỗi giao diện không hiển thị nút Đăng nhập trên mobile",
    "description": "Khi truy cập bằng iPhone 13, nút Đăng nhập bị tràn viền và ẩn đi hoàn toàn.",
    "category_id": "1",
    "severity": "major",
    "priority": "high",
    "platform": "iOS",
    "os": "iOS 16",
    "tags": "mobile, ui"
  },
  {
    "summary": "Không thể tải lên tệp tin đính kèm định dạng .xlsx",
    "description": "Khi chọn file excel, hệ thống báo lỗi không xác định dù dung lượng nhỏ hơn 2MB.",
    "category_id": "1",
    "severity": "minor",
    "priority": "normal"
  }
]
```

---

## 📁 Cấu trúc thư mục dự án

```text
mantisbt-import/
│
├── app.py             # File khởi chạy Flask App chính và các API endpoint
├── config.py          # Cấu hình cổng chạy, thư mục session, danh sách cột bắt buộc/tùy chọn
├── mantis_client.py   # Lớp client xử lý HTTP request, cookie session, cào token CSRF và đăng lỗi
├── requirements.txt   # Danh sách các thư viện Python cần cài đặt
├── .gitignore         # File cấu hình bỏ qua các tệp không cần thiết khi đẩy lên Git
├── README.md          # Tài liệu hướng dẫn sử dụng (File này)
│
├── templates/
│   └── index.html     # Giao diện chính của ứng dụng web (Bootstrap & Vanilla JS)
│
└── sessions/          # Thư mục lưu trữ tạm thời các phiên làm việc (Được tự động dọn dẹp)
```
