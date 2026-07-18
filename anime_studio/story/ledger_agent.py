"""Tier 6 — Continuity ledger maintenance (the Script supervisor).

The ledger is the anti-contradiction engine: a running record of established canon.
This agent reads the canon so far plus a newly written unit (a chapter now; scenes
later) and reports ONLY the deltas — new facts, who learned what, who moved where,
time passing, threads opened/closed. Those deltas are applied to the ledger, which
lower tiers then query so they can't reveal an already-revealed secret, put a
character in two places, or break the timeline.
"""
from __future__ import annotations

from ..ledger import ContinuityLedger
from ..providers.base import TextProvider
from ..schema import Chapter

SYSTEM = (
    "You are the Script supervisor — the keeper of continuity in a writers' room. "
    "Given the canon established so far and a newly written chapter, report ONLY what "
    "NEWLY changes: facts that become true, knowledge characters gain, where characters "
    "end up, how much time passes, and story threads that open or resolve. Do not restate "
    "old canon. Be precise and conservative — if something isn't clearly established, "
    "leave it out."
)

PROMPT = """\
CANON SO FAR:
{context}

NEWLY WRITTEN — {chapter_id}:
  synopsis: {synopsis}
  character_states: {states}
  time_span: {time_span}

Report the continuity deltas as a JSON object with EXACTLY these fields:
- "facts": array of short strings — new canonical facts established this chapter.
- "knowledge": object mapping a short fact_key to an array of character_ids who now know it.
- "positions": object mapping character_id -> location/situation they end this chapter in.
- "timeline": a string for the current in-story time after this chapter (or "" if unchanged).
- "open_threads": array of unresolved questions this chapter raises.
- "resolved_threads": array of previously-open questions this chapter answers.

Return ONLY the JSON object. Empty arrays/objects are fine when nothing changed.
"""


def apply_delta_dict(ledger: ContinuityLedger, data: dict, since: str) -> None:
    """Apply a deltas dict (the shape the prompt above returns) to the ledger.
    Shared by chapter-level (t6) and scene-level (t8) continuity maintenance."""
    for fact in data.get("facts", []) or []:
        if str(fact).strip():
            ledger.establish(str(fact).strip(), since=since)
    for key, who in (data.get("knowledge") or {}).items():
        who_list = who if isinstance(who, list) else [who]
        ledger.learns(str(key), [str(w) for w in who_list])
    for char_id, loc in (data.get("positions") or {}).items():
        ledger.move(str(char_id), str(loc))
    if str(data.get("timeline", "")).strip():
        ledger.advance_time(str(data["timeline"]).strip())
    for t in data.get("open_threads", []) or []:
        if str(t).strip():
            ledger.open_thread(str(t).strip())
    for t in data.get("resolved_threads", []) or []:
        ledger.resolve_thread(str(t).strip())


def apply_chapter(provider: TextProvider, ledger: ContinuityLedger, chapter: Chapter) -> None:
    """Advance the ledger to the end of `chapter` by extracting and applying its deltas."""
    ledger.set_as_of(chapter.id)
    prompt = PROMPT.format(
        context=ledger.context_block(),
        chapter_id=chapter.id,
        synopsis=chapter.synopsis,
        states=chapter.character_states,
        time_span=chapter.time_span,
    )
    data = provider.generate_json(prompt, system=SYSTEM, temperature=0.4)  # low temp: bookkeeping
    apply_delta_dict(ledger, data, since=chapter.id)


def build_ledger(provider: TextProvider, chapters: list[Chapter]) -> ContinuityLedger:
    """Walk chapters in order, accumulating canon into a fresh ledger."""
    ledger = ContinuityLedger()
    for chapter in chapters:
        apply_chapter(provider, ledger, chapter)
    return ledger
