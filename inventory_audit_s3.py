"""Direct S3 inventory scanning for Inventory Audit."""

from __future__ import annotations

from typing import Callable

from inventory_audit_core import InventoryAuditError, InventoryItem, split_s3_uri


ProgressCallback = Callable[[str], None]


def list_inventory_from_s3(
    s3_uri: str,
    profile: str = "",
    region: str = "",
    progress_callback: ProgressCallback | None = None,
) -> tuple[str, list[InventoryItem]]:
    """List objects under an S3 URI using boto3 and return inventory rows.

    This follows the same model as the PowerS3Browser/S3 Organizer inventory
    export: paginate list_objects_v2, keep object metadata, and rely on the
    default AWS credential chain unless a profile is supplied.
    """

    try:
        import boto3
        from botocore.config import Config as BotoConfig
        from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError, NoCredentialsError
    except ImportError as exc:  # pragma: no cover - depends on app packaging
        raise InventoryAuditError("boto3 is required for direct S3 scans. Install requirements.txt.") from exc

    bucket, prefix = split_s3_uri(s3_uri)
    if not bucket:
        raise InventoryAuditError("Enter a full S3 URI like s3://bucket/path/.")

    normalized_prefix = prefix.lstrip("/")
    normalized_uri = f"s3://{bucket}/{normalized_prefix}" if normalized_prefix else f"s3://{bucket}/"
    if normalized_prefix and not normalized_uri.endswith("/"):
        normalized_uri += "/"

    session_kwargs: dict[str, str] = {}
    if profile.strip():
        session_kwargs["profile_name"] = profile.strip()
    if region.strip():
        session_kwargs["region_name"] = region.strip()

    try:
        session = boto3.session.Session(**session_kwargs)
        client = session.client(
            "s3",
            config=BotoConfig(max_pool_connections=32, retries={"mode": "standard", "max_attempts": 6}),
        )
    except (BotoCoreError, NoCredentialsError) as exc:
        raise InventoryAuditError(_aws_error_message(exc)) from exc

    items: list[InventoryItem] = []
    continuation_token: str | None = None

    while True:
        request_kwargs: dict[str, object] = {"Bucket": bucket, "Prefix": normalized_prefix, "MaxKeys": 1000}
        if continuation_token:
            request_kwargs["ContinuationToken"] = continuation_token

        try:
            response = client.list_objects_v2(**request_kwargs)
        except (NoCredentialsError, EndpointConnectionError, BotoCoreError, ClientError) as exc:
            raise InventoryAuditError(_aws_error_message(exc)) from exc

        for entry in response.get("Contents", []):
            key = str(entry.get("Key", "")).strip()
            if not key or key.endswith("/"):
                continue
            last_modified_value = entry.get("LastModified")
            last_modified = last_modified_value.isoformat() if hasattr(last_modified_value, "isoformat") else str(last_modified_value or "")
            items.append(
                InventoryItem(
                    bucket=bucket,
                    key=key,
                    size_bytes=int(entry.get("Size", 0) or 0),
                    last_modified=last_modified,
                    s3_uri=f"s3://{bucket}/{key}",
                )
            )

        if progress_callback:
            progress_callback(f"Scanned {len(items)} object(s) so far...")

        if not response.get("IsTruncated"):
            break
        continuation_token = str(response.get("NextContinuationToken", "") or "")
        if not continuation_token:
            break

    return normalized_uri, items


def _aws_error_message(error: Exception) -> str:
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        error_info = response.get("Error", {})
        code = error_info.get("Code")
        message = error_info.get("Message")
        if code or message:
            return f"AWS S3 scan failed: {code or 'Error'} - {message or error}"
    return f"AWS S3 scan failed: {error}"
