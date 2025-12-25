@echo off
setlocal
echo ========================================================
echo   Dental Master - Khoi dong (Launcher)
echo ========================================================
echo.

set "VENV_PATH=.venv"
set "PYTHON_EXE=%VENV_PATH%\Scripts\python.exe"

REM 1. Kiem tra xem moi truong ao co ton tai khong
if not exist "%PYTHON_EXE%" (
    echo [THONG BAO] Chua tim thay moi truong chay.
    echo Dang tien hanh cai dat tu dong...
    goto :INSTALL_AND_RETRY
)

REM 2. Kiem tra xem moi truong co hop le khong (thu nhat dependencies)
"%PYTHON_EXE%" -c "import streamlit; import google.genai" >nul 2>&1
if %errorlevel% neq 0 (
    echo [CANH BAO] Moi truong bi loi hoac thieu thu vien.
    echo Dang tien hanh sua chua va cai dat lai...
    goto :INSTALL_AND_RETRY
)

REM 3. Kiem tra xem co thu vien moi can cap nhat khong
fc /b requirements.txt "%VENV_PATH%\requirements.bak" >nul 2>&1
if %errorlevel% neq 0 (
    echo [PHAT HIEN CAP NHAT] File requirements.txt da thay doi.
    echo Dang tu dong cap nhat thu vien moi...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    copy /y requirements.txt "%VENV_PATH%\requirements.bak" >nul
    echo Cap nhat hoan tat!
    echo.
)

goto :LAUNCH_APP

:INSTALL_AND_RETRY
REM Xoa moi truong cu neu co de cai moi hoan toan
if exist "%VENV_PATH%" (
    echo Dang don dep moi truong cu...
    rmdir /s /q "%VENV_PATH%"
)

REM Goi script cai dat
call install.bat

REM Kiem tra lai sau khi cai
if not exist "%PYTHON_EXE%" (
    echo.
    echo [LOI] Qua trinh cai dat that bai. Vui long kiem tra lai.
    pause
    exit /b
)

:LAUNCH_APP
echo.
echo Dang kich hoat moi truong...
echo Dang mo ung dung Streamlit...
echo Vui long cho trong giay lat...
echo.
echo --------------------------------------------------------
echo Nhan Ctrl+C de dung server.
echo --------------------------------------------------------

"%PYTHON_EXE%" -m streamlit run app.py

pause
