"""Read-only S3 inventory scanning for Inventory Audit."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from inventory_audit_core import InventoryAuditError, InventoryItem


MAX_RETRY_ATTEMPTS = 4
INITIAL_RETRY_DELAY_SECONDS = 1.0
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class S3Location:
    bucket: str
    prefix: str
    normalized_uri: str


@dataclass(frozen=True)
class SavedCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str = ""


def scan_inventory_to_csv(
    s3_uri: str,
    output_base: Path | str,
    progress_callback: ProgressCallback | None = None,
) -> tuple[Path, str, list[InventoryItem]]:
    """List every object under an S3 URI, write inventory CSV, and return rows."""

    location = parse_s3_inventory_uri(s3_uri)
    notify_progress(progress_callback, f"Normalized S3 URI: {location.normalized_uri}")
    notify_progress(progress_callback, "Step 1/2: creating raw S3 inventory CSV.")
    items = list_inventory_from_s3(location, progress_callback=progress_callback)
    inventory_csv_path = inventory_report_path(output_base)
    notify_progress(progress_callback, f"Writing raw inventory CSV to {inventory_csv_path}")
    write_inventory_report(location.normalized_uri, items, inventory_csv_path)
    notify_progress(
        progress_callback,
        f"Raw inventory CSV complete: {inventory_csv_path} ({len(items)} object(s))",
    )
    return inventory_csv_path, location.normalized_uri, items


def parse_s3_inventory_uri(value: str) -> S3Location:
    """Match S3 Organizer inventory URI parsing.

    Accepts bucket roots like ``s3://bucket`` and prefixes like
    ``s3://bucket/path/to/prefix/``. Prefixes are normalized to one trailing
    slash. Bucket roots normalize to ``s3://bucket/``.
    """

    cleaned = value.strip()
    if not cleaned:
        raise InventoryAuditError("S3 URI cannot be blank.")
    if not cleaned.lower().startswith("s3://"):
        raise InventoryAuditError(f"Invalid S3 URI: {cleaned}")

    remainder = cleaned[5:]
    bucket, separator, key = remainder.partition("/")
    bucket = bucket.strip()
    if not bucket:
        raise InventoryAuditError(f"Invalid S3 URI bucket: {cleaned}")

    if not separator or not key.strip():
        return S3Location(bucket=bucket, prefix="", normalized_uri=f"s3://{bucket}/")

    normalized_prefix = sanitize_folder_path(key)
    if not normalized_prefix:
        return S3Location(bucket=bucket, prefix="", normalized_uri=f"s3://{bucket}/")
    normalized_prefix = normalized_prefix.rstrip("/") + "/"
    return S3Location(bucket=bucket, prefix=normalized_prefix, normalized_uri=f"s3://{bucket}/{normalized_prefix}")


def sanitize_folder_path(value: str) -> str:
    cleaned = value.strip().replace("\\", "/")
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    return cleaned.strip("/")


def inventory_report_path(output_base: Path | str) -> Path:
    base = Path(output_base)
    if base.suffix:
        base = base.with_suffix("")
    return base.with_name(f"{base.name}_raw_inventory.csv")


def write_inventory_report(inventory_uri: str, items: list[InventoryItem], report_path: Path | str) -> Path:
    destination = Path(report_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.writer(file_handle)
        writer.writerow(["inventory_uri", inventory_uri])
        writer.writerow([])
        writer.writerow(["bucket", "key", "size_bytes", "last_modified", "s3_uri"])
        for item in items:
            writer.writerow([item.bucket, item.key, item.size_bytes, item.last_modified, f"s3://{item.bucket}/{item.key}"])
    return destination


def list_inventory_from_s3(
    location: S3Location,
    progress_callback: ProgressCallback | None = None,
) -> list[InventoryItem]:
    try:
        import boto3
        from botocore.config import Config as BotoConfig
        from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError, NoCredentialsError
    except ImportError as exc:  # pragma: no cover - depends on app packaging
        raise InventoryAuditError("boto3 is required for direct S3 scans. Install requirements.txt.") from exc

    os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

    notify_progress(progress_callback, "Reading S3 Organizer region and saved credentials.")
    credentials = load_s3_organizer_credentials()
    region = load_s3_organizer_region()
    if region:
        notify_progress(progress_callback, f"Using S3 Organizer/default AWS region: {region}")
    else:
        notify_progress(progress_callback, "No saved AWS region found; using boto3 default region behavior.")
    if credentials:
        notify_progress(progress_callback, "Using saved S3 Organizer credentials.")
    else:
        notify_progress(progress_callback, "No saved S3 Organizer credentials found; using default AWS credential chain.")

    session_kwargs: dict[str, str] = {}
    if region:
        session_kwargs["region_name"] = region
    if credentials:
        session_kwargs["aws_access_key_id"] = credentials.access_key_id
        session_kwargs["aws_secret_access_key"] = credentials.secret_access_key
        if credentials.session_token:
            session_kwargs["aws_session_token"] = credentials.session_token

    try:
        notify_progress(progress_callback, "Creating S3 client.")
        client = boto3.session.Session(**session_kwargs).client(
            "s3",
            config=BotoConfig(
                max_pool_connections=32,
                retries={"mode": "standard", "max_attempts": 6},
                connect_timeout=10,
                read_timeout=60,
            ),
        )
    except (BotoCoreError, NoCredentialsError) as exc:
        raise InventoryAuditError(map_aws_error(exc)) from exc

    items: list[InventoryItem] = []
    continuation_token: str | None = None
    page_number = 1

    notify_progress(progress_callback, f"Listing objects under {location.normalized_uri} (read-only).")

    while True:
        request_kwargs: dict[str, object] = {"Bucket": location.bucket, "Prefix": location.prefix, "MaxKeys": 1000}
        if continuation_token:
            request_kwargs["ContinuationToken"] = continuation_token

        try:
            notify_progress(progress_callback, f"Requesting S3 object page {page_number}...")
            response = call_with_retries(
                lambda: client.list_objects_v2(**request_kwargs),
                progress_callback=progress_callback,
                operation_name="list_objects_v2",
            )
        except (NoCredentialsError, EndpointConnectionError, BotoCoreError, ClientError) as exc:
            raise InventoryAuditError(map_aws_error(exc)) from exc

        for entry in response.get("Contents", []):
            key = str(entry.get("Key", "")).strip()
            if not key or key.endswith("/"):
                continue
            last_modified_value = entry.get("LastModified")
            last_modified = last_modified_value.isoformat() if hasattr(last_modified_value, "isoformat") else str(last_modified_value or "")
            items.append(
                InventoryItem(
                    bucket=location.bucket,
                    key=key,
                    size_bytes=int(entry.get("Size", 0) or 0),
                    last_modified=last_modified,
                    s3_uri=f"s3://{location.bucket}/{key}",
                )
            )

        notify_progress(progress_callback, f"Scanned {len(items)} object(s) so far after page {page_number}.")

        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")
        page_number += 1

    return items


def load_s3_organizer_region() -> str:
    config_path = Path(os.getenv("APPDATA", "")).joinpath("s3_copy_desktop_app", "config.json") if os.getenv("APPDATA") else Path.home() / ".s3_copy_desktop_app" / "config.json"
    if not config_path.exists():
        return ""
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("aws_region", "")).strip()


def load_s3_organizer_credentials() -> SavedCredentials | None:
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError:
        return None

    service_candidates = ("s3-copy-desktop-app-v2", "s3-copy-desktop-app")
    try:
        for service_name in service_candidates:
            combined_value = get_stored_password(keyring, service_name, "aws_credentials_json")
            if combined_value:
                payload = json.loads(combined_value)
                access_key = str(payload.get("access_key_id", "")).strip()
                secret_key = str(payload.get("secret_access_key", "")).strip()
                session_token = str(payload.get("session_token", "")).strip()
                if access_key and secret_key:
                    return SavedCredentials(access_key, secret_key, session_token)

        access_key = get_stored_password(keyring, "s3-copy-desktop-app", "aws_access_key_id")
        secret_key = get_stored_password(keyring, "s3-copy-desktop-app", "aws_secret_access_key")
        session_token = get_stored_password(keyring, "s3-copy-desktop-app", "aws_session_token")
    except (KeyringError, json.JSONDecodeError) as exc:
        raise InventoryAuditError(f"Could not read saved S3 Organizer credentials: {exc}") from exc

    if access_key and secret_key:
        return SavedCredentials(access_key, secret_key, session_token)
    return None


def get_stored_password(keyring_module, service_name: str, username: str) -> str:
    try:
        return (keyring_module.get_password(service_name, username) or "").strip()
    except Exception as exc:  # noqa: BLE001 - keyring backend errors vary by OS.
        if sys.platform == "darwin":
            value = get_macos_keychain_password(service_name, username)
            if value:
                return value
            return ""
        raise exc


def get_macos_keychain_password(service_name: str, username: str) -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service_name, "-a", username, "-w"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()

    combined_output = f"{result.stdout}\n{result.stderr}".lower()
    if "could not be found" in combined_output or "item could not be found" in combined_output:
        return ""
    return ""


def call_with_retries(
    operation,
    progress_callback: ProgressCallback | None = None,
    operation_name: str = "aws_operation",
):
    try:
        from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError, NoCredentialsError
    except ImportError as exc:  # pragma: no cover
        raise InventoryAuditError("botocore is required for direct S3 scans. Install requirements.txt.") from exc

    delay = INITIAL_RETRY_DELAY_SECONDS
    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        try:
            return operation()
        except (NoCredentialsError, EndpointConnectionError, BotoCoreError, ClientError) as exc:
            if attempt >= MAX_RETRY_ATTEMPTS or not is_retryable_exception(exc):
                raise
            notify_progress(
                progress_callback,
                f"Transient {operation_name} error. Retrying ({attempt + 1}/{MAX_RETRY_ATTEMPTS})...",
            )
            time.sleep(delay)
            delay *= 2


def is_retryable_exception(error: Exception) -> bool:
    try:
        from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError, NoCredentialsError
    except ImportError:
        return False

    if isinstance(error, NoCredentialsError):
        return False
    if isinstance(error, EndpointConnectionError):
        return True
    if isinstance(error, BotoCoreError):
        return True
    if isinstance(error, ClientError):
        error_code = str(error.response.get("Error", {}).get("Code", ""))
        return error_code in {
            "RequestTimeout",
            "RequestTimeoutException",
            "Throttling",
            "ThrottlingException",
            "SlowDown",
            "InternalError",
            "ServiceUnavailable",
            "500",
            "503",
        }
    return False


def notify_progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def map_aws_error(error: Exception) -> str:
    try:
        from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError, NoCredentialsError
    except ImportError:
        return f"Unexpected error: {error}"

    if isinstance(error, NoCredentialsError):
        return (
            "AWS credentials are missing. Save credentials in S3 Organizer, configure an AWS profile/default credentials "
            "on this machine, or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY."
        )

    if isinstance(error, EndpointConnectionError):
        return "Network issue: unable to reach AWS endpoint. Check internet/VPN connection and try again."

    if isinstance(error, BotoCoreError):
        return (
            "Network/transport error while communicating with AWS. Please retry. "
            "If this keeps happening, check VPN/proxy/network stability."
        )

    if isinstance(error, ClientError):
        error_code = str(error.response.get("Error", {}).get("Code", ""))
        if error_code in {"403", "AccessDenied"}:
            return "Access denied by AWS. Verify credentials and S3 list permissions for this bucket/prefix."
        if error_code in {"NoSuchBucket", "404", "NotFound"}:
            return "S3 bucket or prefix was not found. Check the S3 URI and try again."
        if error_code in {"InvalidAccessKeyId", "SignatureDoesNotMatch", "AuthFailure"}:
            return "AWS credentials look invalid. Update credentials in S3 Organizer or your AWS configuration and try again."

        message = str(error.response.get("Error", {}).get("Message", "")).strip()
        if message:
            return f"AWS error ({error_code}): {message}"
        return f"AWS error ({error_code})."

    return f"Unexpected error: {error}"
