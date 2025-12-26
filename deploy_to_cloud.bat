@echo off
chcp 65001 >nul
title Deploy Code lên Cloud

echo ========================================
echo   DEPLOY CODE LÊN STREAMLIT CLOUD
echo ========================================
echo.

REM 1. Kiểm tra Git đã cài chưa
where git >nul 2>nul
if errorlevel 1 (
    echo [LỖI] Chưa cài Git!
    echo.
    echo Tải Git tại: https://git-scm.com/download/win
    echo Cài xong rồi chạy lại file này.
    pause
    exit /b 1
)

echo [OK] Git đã được cài đặt.
echo.

REM 2. Kiểm tra thư mục .git
if not exist ".git" (
    echo [INFO] Chưa có Git repo. Đang khởi tạo...
    git init
    git remote add origin https://github.com/tienleanh02-droid/dental-master.git
    echo [OK] Đã kết nối với GitHub repo.
) else (
    echo [OK] Git repo đã tồn tại.
)

echo.

REM 3. Cấu hình user (nếu chưa có)
git config user.email >nul 2>nul
if errorlevel 1 (
    echo [INFO] Cấu hình Git user...
    git config user.email "deploy@local.machine"
    git config user.name "Local Deploy"
)

REM 4. Add tất cả thay đổi
echo [INFO] Đang chuẩn bị code...
git add .

REM 5. Commit
echo [INFO] Đang tạo bản ghi...
git commit -m "Update from local machine - %date% %time%"

REM 6. Push lên Cloud
echo.
echo [INFO] Đang đẩy code lên Cloud...
echo (Có thể cần đăng nhập GitHub lần đầu)
echo.
git push -u origin main --force

if errorlevel 1 (
    echo.
    echo [LỖI] Push thất bại! Thử các cách sau:
    echo   1. Kiểm tra kết nối mạng
    echo   2. Đăng nhập GitHub: gh auth login
    echo   3. Hoặc dùng: git push --set-upstream origin main
    pause
    exit /b 1
)

echo.
echo ========================================
echo   THÀNH CÔNG!
echo ========================================
echo.
echo Code đã được đẩy lên GitHub.
echo Streamlit Cloud sẽ tự động cập nhật trong 1-2 phút.
echo.
echo Link app: https://dental-master.streamlit.app
echo.
pause
