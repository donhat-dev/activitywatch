# Knowledge Base

## Build unsigned DMG cho internal test (macOS)

### Lệnh build đầy đủ (từ project root)

```bash
# 1. Dùng Node đúng phiên bản (cần ≥12, khuyến nghị 24)
source ~/.nvm/nvm.sh && nvm use 24

# 2. Kích hoạt virtualenv
source venv/bin/activate

# 3. Build core modules (bỏ qua Rust vì chưa cài cargo)
make build SKIP_SERVER_RUST=true

# 4. Cài thủ công các Python watcher (không dùng AW_EXTRAS vì aw-notify cần Rust)
cd aw-watcher-input && poetry install && cd ..
cd aw-odoo-sync && poetry install && cd ..
cd aw-watcher-screenshot-mini && poetry install && cd ..

# 5. Build unsigned DMG
LC_ALL=C LANG=C make package-dmg-unsigned SKIP_SERVER_RUST=true
```

Output: `dist/activitywatch-<version>-macos-<arch>-unsigned.dmg` (~47MB)

> **QUAN TRỌNG:** Phải chạy `nvm use 24` TRƯỚC bước `make build`. Nếu quên, webui build sẽ fail silently → `aw_server/static/` bị clear nhưng không được copy lại → app bundle thiếu web UI → 404 khi mở localhost:5600.

---

### Vấn đề gặp phải và cách fix

| Vấn đề | Nguyên nhân | Cách fix |
|--------|-------------|----------|
| `vue-cli-service requires Node ^12.0.0` | Node mặc định là v10 (nvm default cũ) | `source ~/.nvm/nvm.sh && nvm use 24` trước khi build |
| `cargo: command not found` khi build aw-server-rust và aw-notify | Rust/cargo chưa được cài trên máy | Dùng `SKIP_SERVER_RUST=true`; không dùng `AW_EXTRAS=true` (aw-notify cần Rust) |
| aw-watcher-input, aw-odoo-sync, aw-watcher-screenshot-mini thiếu khi không dùng `AW_EXTRAS` | Ba watcher này không nằm trong SUBMODULES khi `AW_EXTRAS=false` | Chạy `poetry install` thủ công trong từng thư mục watcher sau `make build` |
| `Exception: lỗi nghiêm trọng: Không tìm thấy tên...` khi bump-version của aw-server | `aw-server/__about__.py` chỉ kiểm tra error message tiếng Anh của git, nhưng git trả về tiếng Việt | Chạy với `LC_ALL=C LANG=C` để git output bằng tiếng Anh |
| `make: No rule to make target 'package-dmg-unsigned'` | Working directory bị lệch sang `aw-server/` sau khi `cd` vào submodule | Dùng `make -C /path/to/activitywatch` hoặc đảm bảo đang ở project root trước khi chạy make |
| Version trong tên DMG bị thiếu prefix (`-.dev-xxxxx` thay vì `v0.x.x.dev+xxxxx`) | Root repo không có git tag nên `git describe` trả về rỗng | Bình thường khi build local không có tag; không ảnh hưởng chức năng |
| **`GET localhost:5600/ 404 (NOT FOUND)`** sau khi cài DMG | `aw_server/static/` trống rỗng khi PyInstaller build → web UI không được bundle vào `.app` | Xem mục "Troubleshoot 404" bên dưới |

---

### Troubleshoot: 404 khi mở localhost:5600

**Triệu chứng:**
```
GET http://localhost:5600/ 404 (NOT FOUND)
Unchecked runtime.lastError: Could not establish connection. Receiving end does not exist.
```

**Nguyên nhân:** `aw-server/aw_server/static/` trống → web UI không có trong `.app` bundle.

**Nguyên nhân gốc thường gặp:** Build bị interrupt/fail (vd: quên `nvm use 24` → webui build fail) → Makefile chạy `rm -rf aw_server/static/*` nhưng `cp -r aw-webui/dist/*` không chạy được.

**Cách kiểm tra nhanh:**
```bash
ls aw-server/aw_server/static/
# Nếu trống → đây là nguyên nhân
```

**Cách fix:**
```bash
# Bước 1: Copy webui đã build vào static
cp -r aw-server/aw-webui/dist/* aw-server/aw_server/static/

# Bước 2: Xoá .app và DMG cũ
rm -rf dist/ActivityWatch.app dist/activitywatch-*-unsigned.dmg

# Bước 3: Rebuild (KHÔNG cần chạy lại make build)
source venv/bin/activate
LC_ALL=C LANG=C make -C /path/to/activitywatch package-dmg-unsigned SKIP_SERVER_RUST=true
```

**Phòng tránh:** Luôn kích hoạt `nvm use 24` trước khi bắt đầu build sequence. Nếu `make build` exit với lỗi, KHÔNG chạy `make package-dmg-unsigned` tiếp — fix lỗi build trước.

---

### Ghi chú kiến trúc build

- **`make build`**: Cài Python packages cho các submodule (aw-core, aw-client, aw-qt, aw-server).
- **`make package`**: Build flat bundle từng submodule (dùng cho Linux AppImage/deb/zip), KHÔNG cần cho DMG.
- **`make package-dmg-unsigned`** → `dist/ActivityWatch.app` → `dist/ActivityWatch.dmg`:
  - Dùng PyInstaller với `aw.spec` ở root để bundle tất cả thành `.app`.
  - `aw.spec` tự động include aw-odoo-sync, aw-watcher-input, aw-watcher-screenshot-mini.
  - `aw.spec` tự động skip aw-notify nếu phát hiện là Rust-based.
- **`aw-notify`** là Rust binary — không cần thiết cho bản internal test.
- **`aw-server-rust`** là Rust binary — skip bằng `SKIP_SERVER_RUST=true`.

---

### Troubleshoot: Input data toàn 0 (clicks/presses/deltaX/Y đều = 0)

**Triệu chứng:**
```json
{ "clicks": 0, "deltaX": 0, "deltaY": 0, "presses": 0, "scrollX": 0, "scrollY": 0 }
```
Dù thực tế đang di chuột/gõ phím.

**Nguyên nhân:** pynput (thư viện bắt input events) dùng `CGEventTapCreate()` của macOS. Hàm này trả về `None` và **không throw exception** khi app không có Accessibility/Input Monitoring permission → listener chạy nhưng không nhận được event nào → luôn trả về 0.

**macOS permissions cần grant (thủ công):**

1. **System Preferences → Privacy & Security → Accessibility** → thêm `ActivityWatch`
2. **System Preferences → Privacy & Security → Input Monitoring** → thêm `ActivityWatch` *(bắt buộc trên macOS 12+/Apple Silicon)*

> **Lưu ý với unsigned app:** Phải kéo app từ DMG vào `/Applications/` trước, rồi mới tìm thấy trong danh sách. Sau khi grant permission cần **restart aw-watcher-input** (tắt/bật lại từ menu bar).

---

### Troubleshoot: aw-watcher-screenshot không hoạt động

**Triệu chứng:** Screenshot không được chụp, watcher báo lỗi hoặc chạy nhưng không có ảnh.

**Nguyên nhân:** macOS `screencapture` command bị TCC (Transparency, Consent & Control) framework chặn khi app không có Screen Recording permission. Command chạy thành công nhưng tạo file rỗng → watcher nhận `ScreenshotCaptureError("screencapture produced no output")`.

**Permission cần grant (thủ công):**
- **System Preferences → Privacy & Security → Screen Recording** → thêm `ActivityWatch`

**Fix code đã apply (cho lần build sau):**
- Đã thêm `NSScreenRecordingUsageDescription` vào `info_plist` trong [aw.spec](aw.spec) → macOS sẽ tự prompt xin permission khi app cần chụp màn hình.
- *Lưu ý: Accessibility và Input Monitoring không có usage description API — luôn phải grant thủ công.*

---

### GitHub Actions workflow

File: `.github/workflows/build-unsigned-dmg.yml`

Trigger thủ công qua **Actions → "Build Unsigned DMG (Internal Test)" → Run workflow**.
Có thể chọn branch/tag muốn build. Artifact được giữ 30 ngày.
