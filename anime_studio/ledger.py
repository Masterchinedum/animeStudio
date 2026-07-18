"""The continuity ledger (tier 6) — the anti-contradiction engine.

A running record of established canon. Each written beat emits *deltas* (a fact
learned, time passing, a character moving); lower-tier generations *query* it
"as of" their point in the timeline so they can't reveal an already-revealed
secret, put a character in two places, or break the clock.

The ledger is the single most important consistency mechanism, so it carries
behavior (apply/query), not just data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LedgerFact:
    since: str = ""     # e.g. "chapter_01" or "chapter_02, scene_003"
    fact: str = ""


@dataclass
class ContinuityLedger:
    as_of: str = ""                                     # current point in the timeline
    facts: list[LedgerFact] = field(default_factory=list)
    knowledge: dict = field(default_factory=dict)       # {fact_key: [char_ids who know]}
    positions: dict = field(default_factory=dict)       # {char_id: location_id}
    timeline: str = ""                                  # human-readable clock, e.g. "day 1, dusk"
    unresolved: list[str] = field(default_factory=list) # open questions the story still owes

    # -- deltas emitted while writing a beat ------------------------------- #

    def establish(self, fact: str, since: Optional[str] = None) -> None:
        """Record a new canonical fact as of `since` (defaults to as_of)."""
        self.facts.append(LedgerFact(since=since or self.as_of, fact=fact))

    def learns(self, fact_key: str, who) -> None:
        """Grant one or more characters knowledge of a fact."""
        who = [who] if isinstance(who, str) else list(who)
        known = set(self.knowledge.get(fact_key, []))
        known.update(who)
        known.discard("none_yet")
        self.knowledge[fact_key] = sorted(known)

    def move(self, char_id: str, location_id: str) -> None:
        self.positions[char_id] = location_id

    def advance_time(self, timeline: str) -> None:
        self.timeline = timeline

    def open_thread(self, question: str) -> None:
        if question not in self.unresolved:
            self.unresolved.append(question)

    def resolve_thread(self, question: str) -> None:
        self.unresolved = [q for q in self.unresolved if q != question]

    def set_as_of(self, point: str) -> None:
        self.as_of = point

    # -- queries lower tiers run before generating ------------------------- #

    def knows(self, fact_key: str, char_id: str) -> bool:
        return char_id in self.knowledge.get(fact_key, [])

    def where_is(self, char_id: str) -> Optional[str]:
        return self.positions.get(char_id)

    def established_facts(self) -> list[str]:
        return [f.fact for f in self.facts]

    def context_block(self) -> str:
        """A compact, injectable summary for a generation prompt."""
        lines = [f"AS OF: {self.as_of or '(start)'}  |  TIME: {self.timeline or '(unset)'}"]
        if self.facts:
            lines.append("ESTABLISHED:")
            lines += [f"  - ({f.since}) {f.fact}" for f in self.facts]
        if self.positions:
            lines.append("POSITIONS: " + ", ".join(f"{c}@{l}" for c, l in self.positions.items()))
        if self.knowledge:
            lines.append("KNOWS: " + "; ".join(f"{k} -> {v}" for k, v in self.knowledge.items()))
        if self.unresolved:
            lines.append("UNRESOLVED: " + "; ".join(self.unresolved))
        return "\n".join(lines)
