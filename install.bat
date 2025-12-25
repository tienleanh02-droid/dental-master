@echo off
echo ========================================================
echo   Dental Master - Tu Dong Cai Dat (Auto Installer)
echo ========================================================
echo.

echo [1/3] Kiem tra Python...
set PYTHON_CMD=python
python --version >nul 2>&1
if %errorlevel% equ 0 goto found_python

echo 'python' khong tim thay. Dang thu 'py'...
set PYTHON_CMD=py
py --version >nul 2>&1
if %errorlevel% equ 0 goto found_python

echo LOI: Python chua duoc cai dat (ca 'python' va 'py' deu khong tim thay).
echo Vui long cai dat Python 3.10+ tu https://python.org va tich vao "Add Python to PATH".
pause
exit /b

:found_python
echo Python (%PYTHON_CMD%) OK.
echo.

echo [2/3] Tao moi truong ao (.venv)...
if not exist ".venv" (
    %PYTHON_CMD% -m venv .venv
    echo Da tao moi truong ao thanh cong.
) else (
    echo Moi truong ao da ton tai. Bo qua.
)
echo.

echo [3/3] Cai dat thu vien can thiet...
call .venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Checkpointing requirements...
copy /y requirements.txt ".venv\requirements.bak" >nul
echo.

echo ========================================================
echo   CAI DAT HOAN TAT! (SETUP COMPLETED)
echo ========================================================
echo Ban co the chay file 'run_app.bat' de mo ung dung.
echo.
pause
