@echo off
echo ========================================================
echo   Dental Master - Tu Dong Day Code Len GitHub
echo ========================================================
echo(

echo [1/3] Dang nhap vao GitHub...
echo (Ban hay chon 'GitHub.com' va 'Paste an authentication token' hoac 'Login with web browser')
gh auth login

echo(
echo [2/3] Tao kho chua tren GitHub...
REM Tao repo private mac dinh
call gh repo create dental-master --private --source=. --remote=origin

echo(
echo [3/3] Day code len mang...
REM Cau hinh Git tam thoi de commit duoc
call git config user.email "auto@deploy.local"
call git config user.name "Auto Deploy"

REM Commit code
call git add .
call git commit -m "Auto deployment commit"

REM Doi ten nhanh va day len
call git branch -M main
call git push -u origin main

echo(
echo ========================================================
echo   HOAN TAT!
echo ========================================================
echo Code cua ban da duoc dua len GitHub an toan.
echo Buoc tiep theo: Vao trang https://share.streamlit.io de Deploy.
echo(
pause
