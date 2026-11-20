"""Private file storage for visitor photos (and ID images, if an org turns that on).

* ``s3``: S3 / MinIO, read through 5-minute presigned URLs.
* ``local``: files under LOCAL_MEDIA_DIR, read through a signed API URL. For dev
  without MinIO and for tests.

Every image is decoded and re-encoded before it is stored. That strips EXIF (GPS,
device), rejects files that are not images and caps the size.
"""

import io
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from app.core import tokens
from app.core.config import get_settings
from app.core.errors import AppError

URL_TTL_SECONDS = 300
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard


def sanitize_image(raw: bytes, max_side: int) -> bytes:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AppError(413, "file_too_large", "The photo is too large (max 8 MB)")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AppError(422, "not_an_image", "That file is not a photo") from exc
    img = ImageOps.exif_transpose(img)  # keep orientation, then drop all metadata
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=78, method=4)  # new file: no EXIF carried over
    return out.getvalue()


def sanitize_logo(raw: bytes) -> bytes:
    """A logo: PNG (keeps transparency), at most 512 px, metadata dropped."""
    if len(raw) > 2 * 1024 * 1024:
        raise AppError(413, "file_too_large", "The logo is too large (max 2 MB)")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AppError(422, "not_an_image", "Use a PNG or JPEG image") from exc
    img = ImageOps.exif_transpose(img).convert("RGBA")
    img.thumbnail((512, 512))
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


class _Local:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise AppError(400, "bad_key", "Invalid file key")
        return p

    def put(self, key: str, data: bytes, content_type: str) -> None:  # noqa: ARG002
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def read(self, key: str) -> bytes:
        p = self._path(key)
        if not p.is_file():
            raise AppError(404, "not_found", "File not found")
        return p.read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[tuple[str, datetime]]:
        base = self._path(prefix) if prefix else self.root
        if not base.is_dir():
            return []
        return [
            (p.relative_to(self.root).as_posix(), datetime.fromtimestamp(p.stat().st_mtime, UTC))
            for p in base.rglob("*")
            if p.is_file()
        ]

    def url(self, key: str) -> str:
        t = tokens.sign("media", {"k": key}, timedelta(seconds=URL_TTL_SECONDS))
        return f"/api/v1/public/media/{t}"


class _S3:
    def __init__(self) -> None:
        import boto3

        s = get_settings()
        self.bucket = s.s3_bucket

        def client(endpoint: str | None) -> Any:
            return boto3.client(
                "s3",
                endpoint_url=endpoint or None,
                region_name=s.s3_region,
                aws_access_key_id=s.s3_access_key,
                aws_secret_access_key=s.s3_secret_key,
            )

        self.client = client(s.s3_endpoint_url)
        # Presigning is local (no network call), so a second client for the public host is cheap.
        self.signer = client(s.s3_public_endpoint_url or s.s3_endpoint_url)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def list(self, prefix: str) -> list[tuple[str, datetime]]:
        out = []
        for page in self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        ):
            out += [(o["Key"], o["LastModified"]) for o in page.get("Contents", [])]
        return out

    def url(self, key: str) -> str:
        return self.signer.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=URL_TTL_SECONDS
        )


@lru_cache
def backend() -> _Local | _S3:
    s = get_settings()
    return _Local(s.local_media_dir) if s.storage_backend == "local" else _S3()


async def put(key: str, data: bytes, content_type: str = "image/webp") -> None:
    await run_in_threadpool(backend().put, key, data, content_type)


async def delete(key: str) -> None:
    await run_in_threadpool(backend().delete, key)


async def list_keys(prefix: str) -> list[tuple[str, datetime]]:
    """(key, last modified) for every file under ``prefix``."""
    return await run_in_threadpool(backend().list, prefix)


async def signed_url(key: str | None) -> str | None:
    if not key:
        return None
    return await run_in_threadpool(backend().url, key)


async def read_local(token: str) -> bytes:
    b = backend()
    if not isinstance(b, _Local):
        raise AppError(404, "not_found", "File not found")
    claims = tokens.verify("media", token)
    return await run_in_threadpool(b.read, claims["k"])


async def read(key: str) -> bytes:
    return await run_in_threadpool(backend().read, key)
