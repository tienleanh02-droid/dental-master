# Dental Master - Ứng dụng Flashcard Y Khoa

## Cài đặt nhanh

### Windows
1. **Giải nén** thư mục vào vị trí bất kỳ
2. **Chạy file `install.bat`** (chỉ cần lần đầu)
3. **Chạy file `run_app.bat`** để mở ứng dụng

### Yêu cầu
- Python 3.10+ (Tải tại https://python.org, nhớ tích "Add Python to PATH")

## Cấu hình Cloud Sync (Tùy chọn)

Để sử dụng tính năng đồng bộ Cloud:

1. **Tạo Service Account** tại Google Cloud Console
2. **Đặt file** `credentials.json` vào thư mục ứng dụng
3. **Bật APIs**: Google Sheets API, Google Drive API

### Đồng bộ hình ảnh
1. Tạo folder `Dental_Anki_Images` trên Google Drive cá nhân
2. Share folder đó với email Service Account (quyền Editor)

## File quan trọng

| File | Mô tả |
|------|-------|
| `install.bat` | Cài đặt môi trường và thư viện |
| `run_app.bat` | Khởi động ứng dụng |
| `credentials.json` | Thông tin xác thực Google (tự tạo) |
| `data.json` | Dữ liệu flashcard (tự tạo khi sử dụng) |

## Hỗ trợ
- Phiên bản: 2.6 | SRS Medical Mode
