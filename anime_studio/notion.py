"""Notion adapter — the human approval/review surface.

Notion is NOT the engine and NOT the source of truth. It's a projection: the
engine pushes each story tier to a Notion database (content flows engine -> Notion),
and reads back one thing only — the `Approval` value — into state.json. The engine
refuses to descend past a *gate* tier until you flip it to "Approved" in Notion.

Stdlib-only: talks to Notion's REST API over urllib, no `requests` dependency.
The integration token is read from the ANIME_NOTION_TOKEN environment variable —
never stored in the repo or a project file.

Design notes:
- We use a *select* property ("Approval"), not Notion's native *status* type: the
  API can create select options on the fly, whereas status options can't be
  created via the API.
- notion.json (per project) stores the database id + a tier->page_id map so pushes
  are idempotent (update in place, never duplicate rows).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API_ROOT = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"          # stable; widely supported
TOKEN_ENV = "ANIME_NOTION_TOKEN"

APPROVAL_OPTIONS = ["Draft", "Needs changes", "Approved"]

# Human labels + which tiers the engine actually blocks on (the approval gates
# from story_engine.md: chapter breakdown, scene beats, timed transcript).
TIER_LABELS = {
    "concept": "Concept",
    "world_bible": "World bible",
    "character_bible": "Character bible",
    "series_arc": "Series arc",
    "chapter_breakdown": "Chapter breakdown",
    "continuity_ledger": "Continuity ledger",   # review artifact, not an approval gate
    "episode_plan": "Episode plan",
    "scene_beats": "Scene beats",
    "screenplay": "Screenplay",
    "timed_transcript": "Timed transcript",
}
GATE_TIERS = {"chapter_breakdown", "scene_beats", "timed_transcript"}


class NotionError(RuntimeError):
    pass


def token_from_env() -> str:
    tok = os.environ.get(TOKEN_ENV, "").strip()
    if not tok:
        raise NotionError(
            f"{TOKEN_ENV} is not set. Create an internal integration at "
            f"notion.so/my-integrations, then put it in studio/.env "
            f"({TOKEN_ENV}=ntn_...) or export it in your shell."
        )
    return tok


class NotionClient:
    def __init__(self, token: str | None = None):
        self.token = token or token_from_env()

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{API_ROOT}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Notion-Version", NOTION_VERSION)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(detail).get("message", detail)
            except Exception:
                msg = detail
            raise NotionError(f"Notion API {e.code}: {msg}") from None
        except urllib.error.URLError as e:
            raise NotionError(f"Could not reach Notion: {e.reason}") from None

    # -- calls we use ------------------------------------------------------ #

    def whoami(self) -> dict:
        return self._request("GET", "/users/me")

    def create_database(self, parent_page_id: str, title: str) -> str:
        body = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": {
                "Name": {"title": {}},
                "Tier": {"rich_text": {}},
                "Approval": {"select": {"options": [
                    {"name": o} for o in APPROVAL_OPTIONS]}},
                "Gate": {"checkbox": {}},
            },
        }
        return self._request("POST", "/databases", body)["id"]

    def create_page(self, database_id: str, tier: str, label: str,
                    is_gate: bool, blocks: list[dict]) -> str:
        body = {
            "parent": {"database_id": database_id},
            "properties": {
                "Name": {"title": [{"text": {"content": label}}]},
                "Tier": {"rich_text": [{"text": {"content": tier}}]},
                "Approval": {"select": {"name": "Draft"}},
                "Gate": {"checkbox": is_gate},
            },
            "children": blocks,
        }
        return self._request("POST", "/pages", body)["id"]

    def replace_page_content(self, page_id: str, blocks: list[dict]) -> None:
        """Clear a page's children and write fresh blocks. Preserves the row's
        Approval value so re-pushing content never resets an approval."""
        existing = self._request("GET", f"/blocks/{page_id}/children?page_size=100")
        for child in existing.get("results", []):
            self._request("DELETE", f"/blocks/{child['id']}")
        if blocks:
            self._request("PATCH", f"/blocks/{page_id}/children", {"children": blocks})

    def query_approvals(self, database_id: str) -> dict:
        """Return {tier_key: approval_string} for every row in the database."""
        out: dict = {}
        cursor = None
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            page = self._request("POST", f"/databases/{database_id}/query", body)
            for row in page.get("results", []):
                props = row.get("properties", {})
                tier = _plain_text(props.get("Tier", {}).get("rich_text", []))
                sel = (props.get("Approval", {}).get("select") or {}).get("name")
                if tier:
                    out[tier] = sel
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")
        return out


# --------------------------------------------------------------------------- #
# Block rendering (dict -> Notion blocks)
# --------------------------------------------------------------------------- #

def _plain_text(rich: list) -> str:
    return "".join(r.get("plain_text", r.get("text", {}).get("content", "")) for r in rich)


def _para(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text",
                                         "text": {"content": text[:1900]}}]}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text",
                                                  "text": {"content": text[:1900]}}]}}


def push_all(paths, client: "NotionClient | None" = None) -> int:
    """Mirror every tier's content to its Notion row (create-or-update). Idempotent
    via the tier->page map in notion.json. Returns the number of tiers pushed.
    Raises NotionError if Notion isn't initialized for this project."""
    from . import store  # local import avoids a module cycle
    if not paths.notion.exists():
        raise NotionError("Notion not initialized (no notion.json). Run `anime notion init`.")
    cfg = store.load_json(paths.notion)
    if not cfg.get("database_id"):
        raise NotionError("notion.json has no database_id. Run `anime notion init`.")
    client = client or NotionClient()
    pages = cfg.setdefault("pages", {})
    for tier, label in TIER_LABELS.items():
        blocks = render_tier_blocks(tier, store.tier_content(paths, tier))
        if tier in pages:
            client.replace_page_content(pages[tier], blocks)
        else:
            pages[tier] = client.create_page(
                cfg["database_id"], tier, label, tier in GATE_TIERS, blocks)
    store.save_json(paths.notion, cfg)
    return len(TIER_LABELS)


def render_tier_blocks(tier: str, content: dict) -> list[dict]:
    """Turn a tier's JSON into readable Notion blocks. Deliberately simple —
    a bullet per top-level field; nested values are shown as compact JSON.
    The continuity ledger gets a purpose-built, readable layout."""
    if not content:
        return [_para("(empty — not generated yet)")]
    if tier == "continuity_ledger":
        return _render_ledger_blocks(content)
    blocks: list[dict] = []
    for key, val in content.items():
        if isinstance(val, (dict, list)):
            val = json.dumps(val, ensure_ascii=False)
        blocks.append(_bullet(f"{key}: {val}"))
    return blocks


def _render_ledger_blocks(content: dict) -> list[dict]:
    """Readable ledger view. Caps long lists so a page stays under Notion's
    100-blocks-per-request limit; the complete record is always in ledger.json."""
    facts = content.get("facts", []) or []
    unresolved = content.get("unresolved", []) or []
    positions = content.get("positions", {}) or {}
    knowledge = content.get("knowledge", {}) or {}

    blocks: list[dict] = [_para(
        f"Timeline: {content.get('timeline') or '(unset)'}    |    "
        f"as of: {content.get('as_of') or '(start)'}"
    )]

    FACT_CAP = 50
    blocks.append(_para(f"Established facts ({len(facts)}):"))
    for f in facts[:FACT_CAP]:
        if isinstance(f, dict):
            since, text = f.get("since", ""), f.get("fact", "")
            blocks.append(_bullet(f"({since}) {text}" if since else text))
        else:
            blocks.append(_bullet(str(f)))
    if len(facts) > FACT_CAP:
        blocks.append(_para(f"… (+{len(facts) - FACT_CAP} more — full list in narrative/ledger.json)"))

    if unresolved:
        blocks.append(_para(f"Unresolved threads ({len(unresolved)}):"))
        for u in unresolved[:20]:
            blocks.append(_bullet(str(u)))

    if positions:
        blocks.append(_para("Positions: " + ", ".join(f"{k} @ {v}" for k, v in positions.items())))
    if knowledge:
        blocks.append(_para("Knowledge: " + "; ".join(f"{k} → {v}" for k, v in knowledge.items())))
    return blocks
