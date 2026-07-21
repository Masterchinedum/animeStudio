"""Shared Google Cloud auth for Vertex providers — a cached bearer token from the
gcloud CLI (`gcloud auth print-access-token`). Keeps the engine dependency-free
(no google client libraries); the user just needs gcloud installed + `gcloud auth login`.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
import shutil

from .base import ProviderError

_cache: dict = {"token": "", "exp": 0.0}


def _gcloud_command() -> str:
    """Find an existing Google Cloud SDK without assuming it is on PATH.

    The macOS SDK installer commonly places it under ``~/google-cloud-sdk``.  This
    keeps every Vertex-backed provider on the same existing login rather than
    requiring a duplicate installation just because an automation shell has a
    narrower PATH than the user's interactive terminal.
    """
    found = shutil.which("gcloud")
    if found:
        return found
    candidates = (
        Path.home() / "google-cloud-sdk" / "bin" / "gcloud",
        Path("/Library/Google/Cloud SDK/google-cloud-sdk/bin/gcloud"),
        Path("/opt/homebrew/bin/gcloud"),
        Path("/usr/local/bin/gcloud"),
    )
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_mode & 0o111:
            return str(candidate)
    raise FileNotFoundError("gcloud")


def access_token() -> str:
    if _cache["token"] and time.time() < _cache["exp"]:
        return _cache["token"]
    try:
        r = subprocess.run([_gcloud_command(), "auth", "print-access-token"],
                           capture_output=True, text=True, timeout=30, check=True)
    except FileNotFoundError:
        raise ProviderError("gcloud CLI not found. Install it and run `gcloud auth login`.") from None
    except subprocess.CalledProcessError as e:
        raise ProviderError(f"gcloud token failed ({e.stderr.strip()[:160]}). "
                            "Run `gcloud auth login`.") from None
    except subprocess.TimeoutExpired:
        raise ProviderError("gcloud token request timed out.") from None
    tok = r.stdout.strip()
    if not tok:
        raise ProviderError("gcloud returned an empty token. Run `gcloud auth login`.")
    _cache["token"], _cache["exp"] = tok, time.time() + 3000   # ~1h tokens; refresh at 50m
    return tok


def invalidate() -> None:
    _cache["token"], _cache["exp"] = "", 0.0
