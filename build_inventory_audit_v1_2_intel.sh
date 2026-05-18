#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="1.2"
ZIP_NAME="Inventory_Audit_v1_2-macOS-intel.zip"

SHARED_X86_PYINSTALLER="$ROOT_DIR/../s3_organizer_repo/.venv-x86/bin/pyinstaller"
LOCAL_X86_PYINSTALLER="$ROOT_DIR/.venv-x86/bin/pyinstaller"

if [[ -x "$LOCAL_X86_PYINSTALLER" ]]; then
  PYINSTALLER_BIN="$LOCAL_X86_PYINSTALLER"
elif [[ -x "$SHARED_X86_PYINSTALLER" ]]; then
  PYINSTALLER_BIN="$SHARED_X86_PYINSTALLER"
else
  echo "Intel PyInstaller not found."
  echo "Build an x86_64 Python/Rosetta environment first, then rerun this script."
  exit 1
fi

cd "$ROOT_DIR"

arch -x86_64 "$PYINSTALLER_BIN" \
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

ditto -c -k --keepParent "dist/Inventory Audit.app" "dist/$ZIP_NAME"

echo "Build complete: $ROOT_DIR/dist/Inventory Audit.app"
echo "Packaged: $ROOT_DIR/dist/$ZIP_NAME"
echo "Version: $VERSION"
file "$ROOT_DIR/dist/Inventory Audit.app/Contents/MacOS/Inventory Audit"
