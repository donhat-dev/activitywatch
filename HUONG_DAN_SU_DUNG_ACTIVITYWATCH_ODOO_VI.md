# Hướng dẫn sử dụng ActivityWatch tích hợp Odoo

Tài liệu này hướng dẫn:
- cài đặt bộ cài Windows
- nhập thông tin Odoo trong installer
- kiểm tra watcher sau khi cài
- kiểm tra đồng bộ khi đã bật task trên Odoo
- xử lý lỗi thường gặp

---

## 1. Mục tiêu

Sau khi cài xong, hệ thống cần đạt các trạng thái sau:
- `aw-qt` chạy
- `aw-server` chạy
- `aw-watcher-screenshot-mini` chạy
- `aw-odoo-sync` chạy
- watcher screenshot đọc đúng `Odoo URL`
- watcher screenshot lấy được remote config từ Odoo
- dữ liệu hoạt động và ảnh chụp màn hình được đẩy lên Odoo

---

## 2. Chuẩn bị trước khi cài

Cần chuẩn bị:
- file installer Windows: `activitywatch-setup.exe`
- URL Odoo, ví dụ: `https://dev-hrm.lfglobaltech.com`
- mã PIN nhân viên nếu dùng mapping theo PIN
- hoặc `Employee ID / email fallback` nếu không dùng PIN
- tài khoản Odoo có thể mở task và bật activity tracking

Trước khi test, cần xác nhận phía Odoo:
- module activity tracking đã được cài
- cấu hình activity tracking đã bật
- công ty mặc định cho ingest đã cấu hình
- đang có task hoặc timesheet timer chạy

[Hình chụp màn hình cấu hình activity tracking trong Odoo]

---

## 3. Cài đặt bằng installer

### Bước 1. Chạy file cài đặt
Mở file:
- `activitywatch-setup.exe`

Nếu Windows hỏi quyền chạy ứng dụng, chọn cho phép.

[Hình chụp màn hình file installer Windows]

### Bước 2. Chọn thư mục cài đặt
Có thể giữ mặc định hoặc đổi thư mục cài.

[Hình chụp màn hình chọn thư mục cài đặt]

### Bước 3. Nhập thông tin Odoo
Tại màn hình `Odoo Sync Configuration`, nhập:
- **Odoo URL**: địa chỉ hệ thống Odoo, ví dụ `https://dev-hrm.lfglobaltech.com`
- **PIN code**: mã PIN nhân viên, nếu hệ thống dùng PIN
- **Employee ID or email fallback**: dùng khi không nhập PIN hoặc muốn map trực tiếp theo ID/email

Giá trị mặc định hiện tại của `Odoo URL` là:
- `https://dev-hrm.lfglobaltech.com`

Khuyến nghị:
- nếu có PIN chuẩn, nhập `PIN code`
- nếu không có PIN, nhập `Employee ID or email fallback`
- có thể nhập cả 2, hệ thống sẽ ưu tiên xử lý theo logic backend

[Hình chụp màn hình cấu hình Odoo host trong installer]

### Bước 4. Hoàn tất cài đặt
Tiếp tục đến cuối wizard và hoàn tất.

Có thể bật tùy chọn chạy ứng dụng ngay sau khi cài.

[Hình chụp màn hình hoàn tất cài đặt]

---

## 4. File cấu hình sau khi cài

### 4.1. Cấu hình watcher screenshot
File:
- `C:\Users\<User>\AppData\Local\activitywatch\activitywatch\aw-watcher-screenshot-mini\aw-watcher-screenshot-mini.toml`

Kỳ vọng có phần:

```toml
[odoo]
enabled = true
base_url = "https://dev-hrm.lfglobaltech.com"
token = ""
api_secret = ""
sign_requests = true
employee_id = ""
device_id = ""
device_name = ""
timeout_secs = 10
push_screenshots = true
push_metadata_events = false
```

### 4.2. Cấu hình sync service
File có thể nằm trong thư mục cài đặt ứng dụng của `aw-odoo-sync`, tùy cách đóng gói hiện tại.

Nếu cần kiểm tra runtime state của sync service, xem file:
- `C:\Users\<User>\AppData\Local\activitywatch\activitywatch\aw-odoo-sync\state.json`

---

## 5. Các bước kiểm tra sau khi cài

### Bước 1. Kiểm tra tiến trình đang chạy
Mở Task Manager hoặc dùng PowerShell, xác nhận có các process:
- `aw-qt`
- `aw-server`
- `aw-watcher-screenshot-mini`
- `aw-odoo-sync`

[Hình chụp màn hình Task Manager hiển thị các process ActivityWatch]

### Bước 2. Kiểm tra log của watcher screenshot
Thư mục log:
- `C:\Users\<User>\AppData\Local\activitywatch\activitywatch\Logs\aw-watcher-screenshot-mini`

Mở file log mới nhất. Kỳ vọng thấy các dòng như sau:

```text
Watcher config path: C:\Users\<User>\AppData\Local\activitywatch\activitywatch\aw-watcher-screenshot-mini\aw-watcher-screenshot-mini.toml
Odoo: enabled=True base_url=https://dev-hrm.lfglobaltech.com
Starting screenshot watcher
```

Nếu đang dùng public endpoint không cần token, có thể thấy thêm:

```text
Odoo token not set; using public activity tracking endpoints
```

[Hình chụp màn hình log watcher screenshot]

### Bước 3. Kiểm tra log của sync service
Thư mục log:
- `C:\Users\<User>\AppData\Local\activitywatch\activitywatch\Logs\aw-odoo-sync`

Kỳ vọng thấy:

```text
Logging initialized at ...\aw-odoo-sync.log
Starting aw-odoo-sync
```

[Hình chụp màn hình log aw-odoo-sync]

### Bước 4. Bật task trên Odoo
Trong Odoo:
- mở task cần theo dõi
- bắt đầu timer hoặc trạng thái làm việc tương ứng
- bảo đảm activity tracking đang cho phép ingest dữ liệu

[Hình chụp màn hình task đang chạy trong Odoo]

### Bước 5. Chờ watcher chạy 1-2 chu kỳ
Sau khi task đã chạy trên Odoo:
- chờ ít nhất 1 chu kỳ capture
- chờ thêm 1 chu kỳ để kiểm tra remote config hoặc đẩy dữ liệu

Nếu remote config hoạt động đúng, log watcher screenshot nên xuất hiện dòng dạng:

```text
Remote tracking config in use: {...}
```

Nếu chưa lấy được config từ Odoo, có thể thấy:

```text
Remote tracking config unavailable; using fallback config
```

Nếu capture thành công, có thể thấy dòng dạng:

```text
Queued screenshot event: 1 image(s)
```

[Hình chụp màn hình log khi remote config được áp dụng]

### Bước 6. Kiểm tra state của sync service
Mở file:
- `C:\Users\<User>\AppData\Local\activitywatch\activitywatch\aw-odoo-sync\state.json`

Kiểm tra:
- có bucket `aw-watcher-screenshot-mini`
- `last_timestamp` tăng sau khi watcher hoạt động
- danh sách `attachments` tăng khi có ảnh mới được ghi nhận

[Hình chụp màn hình state.json của aw-odoo-sync]

---

## 6. Dấu hiệu hệ thống hoạt động đúng

Hệ thống được xem là hoạt động đúng khi:
- installer ghi đúng `Odoo URL`
- log watcher hiển thị `enabled=True`
- watcher không còn dùng `localhost` nếu đã nhập host Odoo khác
- watcher lấy được remote config từ Odoo
- dữ liệu bucket hoặc screenshot được đẩy lên Odoo
- file `state.json` cập nhật theo thời gian

Ví dụ dấu hiệu tốt:
- `Odoo: enabled=True base_url=https://dev-hrm.lfglobaltech.com`
- `Remote tracking config in use: ...`
- `Queued screenshot event: ...`
- `Uploaded X screenshot attachments from aw-watcher-screenshot-mini`

---

## 7. Dấu hiệu lỗi thường gặp

### 7.1. Watcher vẫn dùng `localhost`
Triệu chứng:
- log có `base_url=http://localhost:8069`

Nguyên nhân thường gặp:
- cài bằng installer cũ
- file config cũ trong AppData chưa được cập nhật
- watcher đang đọc file config khác với file đang kiểm tra

Cách xử lý:
- cài lại bằng installer mới
- mở file `aw-watcher-screenshot-mini.toml` trong AppData để xác nhận nội dung
- khởi động lại ứng dụng sau khi cài

### 7.2. Watcher bật Odoo nhưng không lấy được remote config
Triệu chứng:
- log có `enabled=True`
- nhưng vẫn chạy theo fallback như `interval_secs=60`
- không có `Remote tracking config in use`

Nguyên nhân thường gặp:
- Odoo endpoint `/api/v1/activity_tracking/config` không trả dữ liệu hợp lệ
- không map được employee do thiếu `PIN` hoặc `employee_id/email`
- task trên Odoo chưa thật sự ở trạng thái đang chạy
- activity tracking chưa bật phía Odoo

Cách xử lý:
- kiểm tra `PIN code` hoặc `Employee ID or email fallback`
- kiểm tra task/timer trên Odoo đã start
- kiểm tra cấu hình activity tracking phía Odoo
- xem log backend Odoo nếu cần

### 7.3. `aw-odoo-sync` chạy nhưng không có log sync mới
Triệu chứng:
- chỉ thấy `Starting aw-odoo-sync`
- không thấy log upload hoặc sync

Nguyên nhân thường gặp:
- chưa có event mới trong bucket
- cursor trong `state.json` đã ở cuối
- chưa có screenshot/event mới để đồng bộ
- log mức `INFO` chưa đủ chi tiết

Cách xử lý:
- tạo hoạt động mới trên máy
- chờ thêm 1-2 chu kỳ
- kiểm tra `state.json` có tăng `last_timestamp`
- nếu cần, bật thêm log debug trong watcher

### 7.4. Odoo không nhận đúng nhân viên
Triệu chứng:
- task đang chạy nhưng watcher không lấy đúng config theo nhân viên
- ingest không áp đúng dữ liệu mong muốn

Nguyên nhân thường gặp:
- không nhập `PIN code`
- `Employee ID or email fallback` không đúng
- dữ liệu nhân viên trong Odoo không khớp company hoặc user mapping

Cách xử lý:
- ưu tiên dùng `PIN code` nếu có
- nếu dùng fallback, kiểm tra chính xác `employee id`, `work email`, `login`, hoặc `user email`

---

## 8. Quy trình kiểm tra khuyến nghị

Quy trình đề xuất cho người dùng cuối:

1. Cài bằng `activitywatch-setup.exe`
2. Nhập `Odoo URL`
3. Nhập `PIN code` hoặc `Employee ID / email fallback`
4. Mở ActivityWatch
5. Kiểm tra process đang chạy
6. Mở log watcher screenshot
7. Xác nhận `enabled=True` và đúng `base_url`
8. Start task trên Odoo
9. Chờ 1-2 chu kỳ capture
10. Kiểm tra log có `Remote tracking config in use`
11. Kiểm tra Odoo đã nhận dữ liệu hoặc ảnh
12. Nếu lỗi, kiểm tra `state.json` và log backend Odoo

---

## 9. Mẫu checklist nghiệm thu nhanh

### Sau khi cài
- [ ] Installer mở bình thường
- [ ] `Odoo URL` mặc định đúng
- [ ] Nhập được `PIN code` hoặc `Employee ID / email fallback`
- [ ] Cài đặt hoàn tất

### Sau khi chạy ứng dụng
- [ ] Có process `aw-qt`
- [ ] Có process `aw-server`
- [ ] Có process `aw-watcher-screenshot-mini`
- [ ] Có process `aw-odoo-sync`

### Kiểm tra log
- [ ] Log watcher screenshot tạo mới
- [ ] `enabled=True`
- [ ] `base_url` đúng host Odoo
- [ ] Không còn `localhost` nếu không mong muốn
- [ ] Có dấu hiệu lấy remote config hoặc fallback rõ ràng

### Kiểm tra Odoo
- [ ] Task đã start
- [ ] Activity tracking đã bật
- [ ] Dữ liệu ingest về đúng nhân viên
- [ ] Có dữ liệu hoặc ảnh được ghi nhận

---

## 10. Gợi ý bổ sung ảnh sau này

Có thể bổ sung ảnh thật vào các vị trí placeholder sau:
- `[Hình chụp màn hình file installer Windows]`
- `[Hình chụp màn hình cấu hình Odoo host trong installer]`
- `[Hình chụp màn hình log watcher screenshot]`
- `[Hình chụp màn hình log aw-odoo-sync]`
- `[Hình chụp màn hình task đang chạy trong Odoo]`
- `[Hình chụp màn hình log khi remote config được áp dụng]`
- `[Hình chụp màn hình state.json của aw-odoo-sync]`

---

## 11. Ghi chú

Tài liệu này mô tả luồng hiện tại của bản tích hợp ActivityWatch + Odoo trong repo này. Nếu logic installer, vị trí config, hoặc cách auth Odoo thay đổi trong tương lai, cần cập nhật lại tài liệu tương ứng.

Nếu cần, có thể tạo thêm:
- bản hướng dẫn ngắn cho end-user
- bản hướng dẫn kỹ thuật cho đội support
- bản checklist UAT riêng cho QA
