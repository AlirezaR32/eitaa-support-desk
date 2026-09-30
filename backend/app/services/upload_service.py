"""Upload validation: size limit, extension allowlist, magic-byte sniffing."""

from __future__ import annotations

import secrets
import uuid
from pathlib import Path

import filetype

from app.core.config import settings
from app.services.errors import ValidationError

# sniffing library only detects media types; documents are trusted by extension
_MEDIA_KIND_BY_MIME = {
    "image/": "photo",
    "audio/": "audio",
    "video/": "video",
}


def _guess_kind(mime_type: str, file_name: str) -> str:
    for prefix, kind in _MEDIA_KIND_BY_MIME.items():
        if mime_type.startswith(prefix):
            return kind
    return "document"


def validate_and_store(
    *,
    file_name: str,
    content: bytes,
    declared_mime: str,
    as_voice: bool = False,
) -> tuple[Path, dict]:
    """Validate an upload and persist it under UPLOADS_DIR.

    Returns (stored_path, meta). Raises ValidationError on policy violations.
    """
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValidationError(
            f"File too large: {len(content) / 1024 / 1024:.1f} MB "
            f"(limit {settings.max_upload_size_mb} MB)"
        )
    if not content:
        raise ValidationError("Empty file")

    safe_name = Path(file_name or "file").name or "file"
    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if extension not in settings.allowed_extension_list:
        raise ValidationError(
            f"File type .{extension} is not allowed. Allowed: "
            + ", ".join(sorted(settings.allowed_extension_list))
        )

    # magic-byte sniffing for media (filetype covers image/audio/video/zip types)
    sniffed = filetype.guess(content)
    sniffed_mime = sniffed.mime if sniffed else None
    mime_type = (
        sniffed_mime or (declared_mime or "").split(";")[0].strip() or ("application/octet-stream")
    )

    if sniffed_mime and (
        sniffed_mime.startswith("image/")
        or sniffed_mime.startswith("audio/")
        or sniffed_mime.startswith("video/")
    ):
        # enforce consistency between sniffed type and extension family
        if extension in {"png", "jpg", "jpeg", "gif", "webp"} and not sniffed_mime.startswith(
            "image/"
        ):
            raise ValidationError("File content does not match its image extension")
        if extension in {"mp3", "ogg", "oga", "opus", "wav", "m4a"} and not sniffed_mime.startswith(
            "audio/"
        ):
            raise ValidationError("File content does not match its audio extension")
        if extension in {"mp4", "webm", "mov"} and not sniffed_mime.startswith("video/"):
            raise ValidationError("File content does not match its video extension")

    kind = "voice" if as_voice else _guess_kind(mime_type, safe_name)

    # storage layout: uploads/YYYY/MM/uuid__safename
    now_dir = (
        Path(settings.uploads_path) / f"{uuid.uuid4().hex[:8]}"
    )  # flat, unguessable per-file dir
    now_dir.mkdir(parents=True, exist_ok=True)
    stored = now_dir / f"{secrets.token_hex(8)}__{safe_name}"
    stored.write_bytes(content)
    return stored, {
        "kind": kind,
        "file_name": safe_name,
        "mime_type": mime_type,
        "size_bytes": len(content),
    }
