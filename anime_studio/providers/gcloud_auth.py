"""Shared Google Cloud auth for Vertex providers — a cached bearer token from the
gcloud CLI (`gcloud auth print-access-token`). Keeps the engine dependency-free
(no google client libraries); the user just needs gcloud installed + `gcloud auth login`.
"""
from __future__ import annotations

import subprocess
import time

from .base import ProviderError

_cache: dict = {"token": "", "exp": 0.0}


def access_token() -> str:
    if _cache["token"] and time.time() < _cache["exp"]:
        return _cache["token"]
    try:
        r = subprocess.run(["gcloud", "auth", "print-access-token"],
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
