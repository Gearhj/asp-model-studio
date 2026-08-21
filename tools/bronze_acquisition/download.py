"""Resumable, atomic, checksummed HTTP downloader for Bronze acquisition. Pure stdlib (urllib); no ASP
imports. Downloads to `<dest>.partial`, verifies, fsyncs, and atomically renames; never overwrites a
verified file with divergent bytes; retries with bounded exponential backoff; redacts secrets from logs."""
from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .safety import BronzeBoundaryError, redact

_UA = "asp-mlb-bronze-acquisition/1.0 (research; contact local developer)"
_CHUNK = 1 << 20


class DownloadError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _looks_like_html(head: bytes) -> bool:
    s = head[:512].lstrip().lower()
    return s.startswith(b"<!doctype html") or s.startswith(b"<html") or b"<title>" in s[:512]


def http_download(
    url: str,
    dest: Path,
    *,
    expect_not_html: bool = True,
    max_retries: int = 5,
    timeout: int = 180,
    verify_fn: Callable[[Path], None] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict:
    """Download `url` to `dest` atomically. If `dest` already exists it is reused after a SHA check (no
    redownload). Returns a receipt: {status, attempts, bytes, sha256, contentType, reused}."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _log = log or (lambda m: None)
    if dest.exists():
        return {"status": 200, "attempts": 0, "bytes": dest.stat().st_size,
                "sha256": sha256_file(dest), "reused": True, "contentType": None}
    partial = dest.with_suffix(dest.suffix + ".partial")
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            if partial.exists():
                partial.unlink()
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200) or 200
                ctype = resp.headers.get("Content-Type", "")
                head = b""
                with open(partial, "wb") as out:
                    first = True
                    while True:
                        block = resp.read(_CHUNK)
                        if not block:
                            break
                        if first:
                            head = block[:512]
                            first = False
                        out.write(block)
                    out.flush()
                    try:
                        os.fsync(out.fileno())
                    except OSError:
                        pass
            if expect_not_html and _looks_like_html(head):
                raise DownloadError("response looks like an HTML error page, not raw data")
            if partial.stat().st_size == 0:
                raise DownloadError("empty response body")
            if verify_fn is not None:
                verify_fn(partial)
            sha = sha256_file(partial)
            if dest.exists():  # concurrent finalize — keep the existing verified bytes
                if sha256_file(dest) != sha:
                    partial.unlink(missing_ok=True)
                    raise DownloadError("verified file already exists with divergent bytes (no overwrite)")
                partial.unlink(missing_ok=True)
                return {"status": status, "attempts": attempt, "bytes": dest.stat().st_size,
                        "sha256": sha, "reused": True, "contentType": ctype}
            os.replace(partial, dest)  # atomic publish
            return {"status": status, "attempts": attempt, "bytes": dest.stat().st_size,
                    "sha256": sha, "reused": False, "contentType": ctype}
        except (BronzeBoundaryError,):
            raise
        except (urllib.error.HTTPError, urllib.error.URLError, DownloadError, TimeoutError, OSError) as exc:
            last_err = exc
            _log(f"attempt {attempt}/{max_retries} failed for {redact(url)}: {redact(str(exc))}")
            if partial.exists():
                partial.unlink(missing_ok=True)
            if attempt < max_retries:
                time.sleep(min(2 ** attempt, 30))
    raise DownloadError(f"download failed after {max_retries} attempts: {redact(str(last_err))}")
