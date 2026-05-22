#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="1.4.2"

if [[ -x "$ROOT_DIR/.venv/bin/pyinstaller" ]]; then
  PYINSTALLER_BIN="$ROOT_DIR/.venv/bin/pyinstaller"
elif [[ -x "$ROOT_DIR/../s3_copy_desktop_app/.venv/bin/pyinstaller" ]]; then
  PYINSTALLER_BIN="$ROOT_DIR/../s3_copy_desktop_app/.venv/bin/pyinstaller"
elif command -v pyinstaller >/dev/null 2>&1; then
  PYINSTALLER_BIN="$(command -v pyinstaller)"
else
  echo "PyInstaller not found. Install requirements first:"
  echo "python3 -m pip install -r requirements.txt"
  exit 1
fi

cd "$ROOT_DIR"

"$PYINSTALLER_BIN" \
  --noconfirm \
  --windowed \
  --name "Inventory Audit" \
  --collect-submodules keyring.backends \
  --collect-data keyring \
  --collect-data boto3 \
  --collect-data botocore \
  --collect-data certifi \
  --hidden-import tkinter \
  --hidden-import openpyxl \
  --hidden-import boto3 \
  --hidden-import botocore \
  --hidden-import keyring \
  inventory_audit_app.py

echo "Local app build complete: $ROOT_DIR/dist/Inventory Audit.app"
echo "Version: $VERSION"
echo "Architecture: $(uname -m)"
