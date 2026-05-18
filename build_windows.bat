@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "VENV_DIR=%ROOT_DIR%.venv-windows"
set "PYINSTALLER=%VENV_DIR%\Scripts\pyinstaller.exe"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "ZIP_PATH=%ROOT_DIR%dist\Inventory_Audit_v1_3-windows.zip"

if not exist "%PYINSTALLER%" (
  if not exist "%PYTHON_EXE%" (
    echo Creating Windows venv at %VENV_DIR%
    py -3.12 -m venv "%VENV_DIR%" || exit /b 1
  )
  echo Installing Windows build dependencies...
  "%PYTHON_EXE%" -m pip install --upgrade pip || exit /b 1
  "%PYTHON_EXE%" -m pip install -r "%ROOT_DIR%requirements.txt" || exit /b 1
)

cd /d "%ROOT_DIR%"

"%PYINSTALLER%" ^
  --noconfirm ^
  --windowed ^
  --name "Inventory Audit" ^
  --collect-submodules keyring.backends ^
  --collect-data keyring ^
  --collect-data boto3 ^
  --collect-data botocore ^
  --collect-data certifi ^
  --hidden-import tkinter ^
  --hidden-import openpyxl ^
  --hidden-import boto3 ^
  --hidden-import botocore ^
  --hidden-import keyring ^
  inventory_audit_app.py

if exist "%ZIP_PATH%" del "%ZIP_PATH%"
if exist "%ROOT_DIR%dist\Inventory Audit" (
  powershell -NoProfile -Command "Compress-Archive -Path '%ROOT_DIR%dist\Inventory Audit\*' -DestinationPath '%ZIP_PATH%' -Force" || exit /b 1
)

echo Build complete: %ROOT_DIR%dist\Inventory Audit\Inventory Audit.exe
if exist "%ZIP_PATH%" echo Packaged zip: %ZIP_PATH%
