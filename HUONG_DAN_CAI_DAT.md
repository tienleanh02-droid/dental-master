# 🦷 Dental Master - Hướng dẫn Cài đặt & Sử dụng

## 📋 Giới thiệu
**Dental Master** là ứng dụng học tập thông minh dành cho sinh viên Nha khoa, sử dụng hệ thống **Spaced Repetition System (SRS)** giúp ghi nhớ kiến thức lâu dài.

### Tính năng chính:
- 📚 **Thư viện thẻ** - Quản lý câu hỏi theo Môn/Chủ đề dạng cây thư mục
- 🧠 **Học SRS** - Hệ thống lặp lại ngắt quãng thông minh (Again/Hard/Good/Easy)
- 🏆 **Thi thử Mock Exam** - Kiểm tra kiến thức với đề thi ngẫu nhiên
- ✨ **AI Vision Creator** - Tạo thẻ tự động từ hình ảnh (X-quang, sơ đồ...)
- 👁️ **Slide Vision** - Xây dựng câu hỏi từ PDF bài giảng (Visual Diagnosis)
- 📥 **Import Excel** - Nhập dữ liệu từ file Excel/CSV
- ⚙️ **Quản lý thư viện** - Di chuyển, xóa, tạo thư mục

---

## 🚀 Cài đặt

### Yêu cầu hệ thống:
- **Python 3.10** trở lên
- **Kết nối Internet** (để dùng tính năng AI)
- **API Key Gemini** (miễn phí tại [Google AI Studio](https://aistudio.google.com/))

### Thư viện cần thiết (requirements.txt):
```
streamlit
google-genai
pandas
pillow
openpyxl
streamlit-drawable-canvas
pymupdf
msal
```

---

## 📦 Bước 1: Đóng gói (Khi di chuyển sang máy mới)

1. Tại máy hiện tại, nén toàn bộ thư mục `word_to_anki` thành file `.zip`.
2. **Quan trọng:** Đảm bảo các thư mục sau được nén theo:
   - `user_profiles/` - Chứa dữ liệu người dùng
   - `static/images/` - Chứa hình ảnh câu hỏi
   - `config.json` - Cấu hình API Key

---

## 💻 Bước 2: Cài đặt (Tự động)
Chỉ cần chạy file đã chuẩn bị sẵn:

1. Chạy file `install.bat` (Click đúp chuột).
   - Đợi cửa sổ đen chạy xong và báo "CAI DAT HOAN TAT".
   - Bước này sẽ tự tạo môi trường ảo và cài thư viện.

*(Lưu ý: Nếu máy chưa có Python, file install.bat sẽ báo lỗi và yêu cầu bạn tải Python từ python.org trước)*

---

## ▶️ Bước 3: Chạy ứng dụng

1. Chạy file `run_app.bat` (Click đúp chuột).
2. Trình duyệt sẽ tự động mở trang web ứng dụng.

---

## 📖 Hướng dẫn sử dụng

### 🏠 Thư viện
- Bấm vào **tên deck** để xem chi tiết
- Số **xanh lá (Due)** = Số thẻ cần ôn hôm nay
- Số **xanh dương (New)** = Số thẻ mới chưa học

### 🧠 Học với SRS
Khi học, đánh giá độ khó của mỗi thẻ:
| Nút | Ý nghĩa | Khoảng cách tiếp theo |
|-----|---------|----------------------|
| **Again** | Quên/Sai | Ôn lại ngay (1-10 phút) |
| **Hard** | Nhớ mang máng | Ôn sớm hơn (1.2x) |
| **Good** | Nhớ tốt | Ôn theo lịch (2.5x) |
| **Easy** | Quá dễ | Dãn xa ra (bonus 1.3x) |

### 📥 Import dữ liệu
Chuẩn bị file Excel với các cột:
- `Question` - Câu hỏi
- `Option A`, `Option B`, `Option C`, `Option D` - 4 đáp án
- `Correct Answer` - Đáp án đúng (A/B/C/D)
- `Explanation` - Giải thích
- `Subject` - Môn học (VD: "Nha chu/Giải phẫu")
- `Topic` - Chủ đề
- `Image Q`, `Image A` - Tên file ảnh (optional)

### ✨ AI Vision Creator
1. Upload ảnh (X-quang, sơ đồ giải phẫu...)
2. Vẽ khung chữ nhật bao vùng cần che
3. Nhập tên nhãn
4. AI tự động tạo thẻ điền khuyết

### 👁️ Slide Vision (Mới)
Tính năng tạo câu hỏi chẩn đoán hình ảnh từ file bài giảng (PDF):
1. **Upload PDF**: Chọn file bài giảng.
2. **Pass 1 - Chọn Trang (Screening)**: Hệ thống hiển thị thumbnail. Bạn tích chọn các trang có hình ảnh lâm sàng/X-quang giá trị.
3. **Pass 2 - Generate**: AI "nhìn" vào hình ảnh chất lượng cao (đã che tiêu đề/footer để tránh lộ đáp án) và tạo câu hỏi chẩn đoán visual.
4. **Lưu thẻ**: Chọn các câu hỏi ưng ý và lưu vào kho.

---

## 💡 Lưu ý quan trọng

| Vấn đề | Giải pháp |
|--------|-----------|
| Mất dữ liệu khi chuyển máy | Đảm bảo copy thư mục `user_profiles/` |
| API Key không hoạt động | Nhập lại Key trong mục cấu hình sidebar |
| Ảnh không hiển thị | Kiểm tra thư mục `static/images/` |
| Lỗi import Excel | Đảm bảo tên cột tiếng Anh chính xác |

---

## 📞 Hỗ trợ

Nếu gặp lỗi, hãy kiểm tra:
1. Python đã được thêm vào PATH chưa
2. Tất cả thư viện đã cài đầy đủ chưa (`pip install -r requirements.txt`)
3. File `app.py` có tồn tại trong thư mục không

---


**Phiên bản:** v2.7 | SRS Medical Mode  
**Cập nhật:** 24/12/2024
