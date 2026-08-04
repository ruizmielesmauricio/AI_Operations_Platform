"""Direct boundary to the R2 SDK (boto3's S3-compatible client) — no other
module imports boto3 (CLAUDE.md: no provider SDK outside its dedicated
client module). One level below app/imports/service.py, mirroring the
app/billing/client.py <-> service.py split.
"""

import boto3

from app.settings.config import get_settings

_UPLOAD_URL_EXPIRY_SECONDS = 15 * 60


def _client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def generate_upload_url(*, storage_key: str) -> str:
    """A short-lived, single-object presigned PUT URL — the browser uploads
    the file bytes straight to R2, so the file never transits our backend.
    Content-Type is deliberately not part of the signature: it would force
    the browser to replay an exact header value to avoid a signature
    mismatch, for a field nothing downstream reads (B7 identifies format
    from the file's actual content, not a stored content type).
    """
    settings = get_settings()
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": storage_key},
        ExpiresIn=_UPLOAD_URL_EXPIRY_SECONDS,
    )


def get_object_size(*, storage_key: str) -> int:
    """A HEAD request, not a download — used to reject oversized files
    before detect-mapping parses them (see app/imports/service.py). Cheap
    to call before committing to the real download below.
    """
    settings = get_settings()
    response = _client().head_object(Bucket=settings.r2_bucket_name, Key=storage_key)
    return response["ContentLength"]


def download_object(*, storage_key: str) -> bytes:
    """The one place this backend reads an uploaded file's actual content —
    everything before B7 only ever dealt with presigned URLs, never bytes.
    """
    settings = get_settings()
    response = _client().get_object(Bucket=settings.r2_bucket_name, Key=storage_key)
    return response["Body"].read()


def delete_object(*, storage_key: str) -> None:
    """Only called after a successful import commits (PR-2.10, ADR-008) —
    once normalised data is in the database, the source file is retained
    nowhere else.
    """
    settings = get_settings()
    _client().delete_object(Bucket=settings.r2_bucket_name, Key=storage_key)
