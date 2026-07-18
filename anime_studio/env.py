""".env loading — one place for secrets, easy to swap.

Reads KEY=VALUE pairs from a .env file into the process environment so the engine
can pick up GEMINI_API_KEY / ANIME_NOTION_TOKEN without editing your shell profile.
Stdlib-only (no python-dotenv).

Semantics chosen for easy key-swapping:
  - a NON-EMPTY value in .env OVERRIDES the shell environment (so editing .env
    always takes effect, even if an old value lingers in ~/.zshrc);
  - a BLANK value is ignored (so an empty line never wipes a working shell var).

Load order (later wins): studio-root .env, then the current directory's .env.
"""
from __future__ import annotations

import os
from pathlib import Path

STUDIO_ROOT = Path(__file__).resolve().parents[1]   # dir containing the `anime` launcher


def _parse(path: Path) -> dict:
    out: dict = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key] = val
    return out


def load_dotenv(extra_dirs=None) -> list[str]:
    """Load .env files into os.environ. Returns the paths that were applied."""
    candidates = [STUDIO_ROOT / ".env"]
    for d in extra_dirs or []:
        candidates.append(Path(d) / ".env")
    candidates.append(Path.cwd() / ".env")

    applied: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        rp = str(path.resolve())
        if rp in seen or not path.exists():
            continue
        seen.add(rp)
        for key, val in _parse(path).items():
            if val:                       # non-empty overrides; blank leaves shell env intact
                os.environ[key] = val
        applied.append(rp)
    return applied
