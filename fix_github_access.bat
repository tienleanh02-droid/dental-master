@echo off
echo ========================================================
echo   Dental Master - Sua Loi Quyen Truy Cap (GitHub)
echo ========================================================
echo.

echo [1/2] Dang chuyen kho chua sang che do PUBLIC...
echo (Ly do: Streamlit Cloud kho doc kho Private neu chua cap quyen)

REM Thay doi o dong duoi neu ten User khac
set "FULL_REPO_NAME=tienleanh02-droid/dental-master"

call gh repo edit %FULL_REPO_NAME% --visibility public

if %errorlevel% neq 0 (
    echo.
    echo [LOI] Van chua chuyen duoc. Dang thu lai voi cau hinh tu dong...
    REM Thu lay tu git config neu lenh tren that bai
    for /f "tokens=*" %%i in ('gh repo view --json dependency --template "{{.name}}" 2^>nul') do set REPO_NAME=%%i
    if not defined REPO_NAME set REPO_NAME=dental-master
    call gh repo edit %REPO_NAME% --visibility public
)

echo.
echo [2/2] Kiem tra lai...
echo Neu khong bao loi mau do o tren thi la OK.

echo.
echo ========================================================
echo   DA XONG!
echo ========================================================
echo Bay gio anh quay lai trang Streamlit, doi khoang 5 giay.
echo * Luu y: Nho chinh Branch thanh 'main' va Main file path thanh 'app.py' tren Web nhe!
echo.
pause
