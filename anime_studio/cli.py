"""`anime` — the command surface over the memory bank.

Step 1 ships two commands:
  anime init <name>     scaffold a new project (the memory bank)
  anime status [dir]    read the project and print where every stage stands

More stage-runner commands (story / art / animate / sound / assemble) land in
later build steps — each an independent, resumable pass over the shot list.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import art as art_stage
from . import notion as notion_mod
from . import orchestrator as orch
from . import store
from . import story as story_mod
from .paths import ProjectPaths
from .providers import build_text_provider
from .providers.base import ProviderError


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.strip().lower()).strip("_")


def cmd_init(args) -> int:
    project_id = _slug(args.name)
    root = Path(args.path).expanduser() / project_id if args.path else Path.cwd() / project_id
    paths = store.create_project(root, title=args.name, project_id=project_id,
                                 logline=args.logline or "")
    print(f"Created project '{args.name}' at {paths.root}\n")
    _print_tree(paths)
    print("\nNext: fill the concept, then run `anime status` to see the cascade.")
    return 0


def cmd_status(args) -> int:
    paths = ProjectPaths.of(args.path or Path.cwd())
    if not paths.project.exists():
        print(f"No project.json under {paths.root}. Run `anime init <name>` first.",
              file=sys.stderr)
        return 1

    project = store.load_project(paths)
    state = store.load_json(paths.state)

    print(f"# {project.title or project.id}")
    if project.logline:
        print(f"  {project.logline}")
    print(f"  {paths.root}\n")

    print("Assets")
    print(f"  characters : {_count(paths.characters)}")
    print(f"  scenes     : {_count(paths.scenes)}")
    print(f"  shots      : {_count(paths.shots)}")
    print(f"  keyframes  : {_count(paths.keyframes, '*.png')}")
    print(f"  clips      : {_count(paths.clips, '*.mp4')}\n")

    print("Story cascade (tier : status : approved)")
    for tier, s in state.get("tiers", {}).items():
        mark = "OK " if s.get("approved") else "-- "
        print(f"  {mark} {tier:<18} {s.get('status', 'empty')}")

    shots = state.get("shots", {})
    if shots:
        done = sum(1 for v in shots.values()
                   if isinstance(v, dict) and v.get("clip") == "done")
        print(f"\nRender: {done}/{len(shots)} shots have clips")
    return 0


# --------------------------------------------------------------------------- #
# Autopilot — one command, whole cascade
# --------------------------------------------------------------------------- #

def cmd_run(args) -> int:
    paths = _resolve(args)
    if not paths.project.exists():
        print("No project here. cd into a project or pass --project.", file=sys.stderr)
        return 1
    if args.premise:                      # seed/override the premise, then persist it
        project = store.load_project(paths)
        project.logline = args.premise
        store.save_json(paths.project, project)

    print("Anime studio — autopilot run\n")
    results = orch.run(paths, force=args.force, push=not args.no_notion, only=args.only)
    generated = [k for k, v in results if v not in ("skipped",)]
    print(f"\nDone — {len(generated)} tier(s) generated. "
          "Review in Notion anytime (non-blocking); `anime status` for the summary.")
    return 0


# --------------------------------------------------------------------------- #
# Art stage — shots -> keyframes (local ComfyUI)
# --------------------------------------------------------------------------- #

def cmd_refs(args) -> int:
    paths = _resolve(args)
    if not paths.project.exists():
        print("No project here. cd into a project or pass --project.", file=sys.stderr)
        return 1
    if not list(paths.characters.glob("*.json")):
        print("No characters yet. Run `anime run` to generate the cast first.", file=sys.stderr)
        return 1
    print("Anime studio — character reference portraits (locks each character's look)\n")
    r = art_stage.run_refs(paths, force=args.force, only=args.only)
    print(f"\nDone — {r['rendered']} references rendered, {r['skipped']} already locked "
          f"({r['total']} characters).")
    print("Review assets/refs/. Re-roll any with `anime refs --force --only <char_id>`.\n"
          "Then `anime art` locks every shot of each character to their reference.")
    return 0


def cmd_art(args) -> int:
    paths = _resolve(args)
    if not paths.project.exists():
        print("No project here. cd into a project or pass --project.", file=sys.stderr)
        return 1
    if not list(paths.shots.glob("*.json")):
        print("No shots yet. Run `anime run` to generate the shooting script first.",
              file=sys.stderr)
        return 1
    print("Anime studio — art stage (keyframes via local ComfyUI)\n")
    r = art_stage.run_art(paths, force=args.force, only=args.only, limit=args.limit)
    print(f"\nDone — rendered {r['rendered']}, skipped {r['skipped']}, "
          f"failed {r['failed']} of {r['total']} shots.")
    print("Keyframes in assets/keyframes/. Review them, then the (paid) video stage animates the approved ones.")
    return 0


# --------------------------------------------------------------------------- #
# Story stage — the writers' room
# --------------------------------------------------------------------------- #

def cmd_story_concept(args) -> int:
    paths = _resolve(args)
    if not paths.project.exists():
        print("No project here. cd into a project or pass --project.", file=sys.stderr)
        return 1
    project = store.load_project(paths)
    premise = args.premise or project.logline
    if not premise:
        print("No premise. Pass one: anime story concept \"<premise>\"", file=sys.stderr)
        return 1

    provider = build_text_provider(paths)
    print(f"Generating concept with {provider.name} ...")
    concept = story_mod.generate_concept(provider, premise, project)
    store.save_json(paths.concept, concept)

    # record progress; approval still happens in Notion (status stays un-approved)
    state = store.load_json(paths.state)
    node = state.setdefault("tiers", {}).setdefault("concept", {"approved": False})
    node["status"] = "generated"
    store.save_json(paths.state, state)

    print(f"\n  title   : {concept.title}")
    print(f"  logline : {concept.logline}")
    print(f"  theme   : {concept.theme}")
    print(f"  genre   : {concept.genre}")
    print(f"  tone    : {concept.tone}")
    print(f"  format  : {concept.format}  ({concept.length})")
    print(f"\nWrote {paths.concept.name}. Next: `anime notion push`, review + approve in Notion,\n"
          "then `anime notion pull`.")
    return 0


# --------------------------------------------------------------------------- #
# Notion — the approval/review surface
# --------------------------------------------------------------------------- #

def _resolve(args) -> ProjectPaths:
    return ProjectPaths.of(getattr(args, "project", None) or Path.cwd())


def _normalize_id(s: str) -> str:
    """Accept a raw Notion id (with/without dashes) or a full page/db URL."""
    hexes = re.findall(r"[0-9a-fA-F]{32}", s.replace("-", ""))
    return hexes[-1] if hexes else s.strip()


def cmd_notion_verify(args) -> int:
    paths = _resolve(args)
    client = notion_mod.NotionClient()
    me = client.whoami()
    print(f"Token OK — connected as: {me.get('name') or me.get('id')}")
    if paths.notion.exists():
        cfg = store.load_json(paths.notion)
        if cfg.get("database_id"):
            appr = client.query_approvals(cfg["database_id"])
            print(f"Database reachable — {len(appr)} tier rows.")
    else:
        print("No notion.json yet — run `anime notion init --parent <page_id>`.")
    return 0


def cmd_notion_init(args) -> int:
    paths = _resolve(args)
    if not paths.project.exists():
        print("No project here. cd into a project or pass --project.", file=sys.stderr)
        return 1
    cfg = store.load_json(paths.notion) if paths.notion.exists() else {}
    if cfg.get("database_id") and not args.force:
        print("Already initialized. Use --force to recreate the database.", file=sys.stderr)
        return 1
    parent = args.parent or cfg.get("parent_page_id")
    if not parent:
        print("Need a parent page: --parent <page_id/URL> (share it with your integration first).",
              file=sys.stderr)
        return 1
    parent = _normalize_id(parent)
    client = notion_mod.NotionClient()
    project = store.load_project(paths)
    title = f"Story Cascade — {project.title or project.id}"
    db_id = client.create_database(parent, title)
    cfg = {"parent_page_id": parent, "database_id": db_id, "pages": {}}
    store.save_json(paths.notion, cfg)
    print(f"Created Notion database '{title}'.")
    return _push(paths, client, cfg)


def cmd_notion_push(args) -> int:
    paths = _resolve(args)
    if not paths.notion.exists():
        print("Run `anime notion init` first.", file=sys.stderr)
        return 1
    return _push(paths, notion_mod.NotionClient(), store.load_json(paths.notion))


def _push(paths: ProjectPaths, client, cfg: dict) -> int:
    pages = cfg.setdefault("pages", {})
    for tier, label in notion_mod.TIER_LABELS.items():
        blocks = notion_mod.render_tier_blocks(tier, store.tier_content(paths, tier))
        if tier in pages:
            client.replace_page_content(pages[tier], blocks)
            action = "updated"
        else:
            pages[tier] = client.create_page(
                cfg["database_id"], tier, label, tier in notion_mod.GATE_TIERS, blocks)
            action = "created"
        gate = " [GATE]" if tier in notion_mod.GATE_TIERS else ""
        print(f"  {action:<7} {label}{gate}")
    store.save_json(paths.notion, cfg)
    print("\nPushed. Review in Notion; set Approval = Approved on the gate tiers,\n"
          "then run `anime notion pull` to bring approvals back.")
    return 0


def cmd_notion_pull(args) -> int:
    paths = _resolve(args)
    if not paths.notion.exists():
        print("Run `anime notion init` first.", file=sys.stderr)
        return 1
    cfg = store.load_json(paths.notion)
    approvals = notion_mod.NotionClient().query_approvals(cfg["database_id"])
    state = store.load_json(paths.state)
    tiers = state.setdefault("tiers", {})
    for tier, appr in approvals.items():
        node = tiers.setdefault(tier, {"status": "empty", "approved": False})
        node["approved"] = (appr == "Approved")
        node["notion_approval"] = appr
    store.save_json(paths.state, state)
    approved = [t for t, a in approvals.items() if a == "Approved"]
    print(f"Pulled {len(approvals)} rows. Approved: {', '.join(approved) or '(none)'}")
    return 0


def _count(directory: Path, pattern: str = "*.json") -> int:
    return len(list(directory.glob(pattern))) if directory.exists() else 0


def _print_tree(paths: ProjectPaths) -> None:
    rel = [p.relative_to(paths.root) for p in paths.all_dirs() if p != paths.root]
    print("  memory bank:")
    for d in sorted(rel, key=str):
        print(f"    {d}/")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="anime", description="Anime studio engine")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="scaffold a new project (the memory bank)")
    pi.add_argument("name", help="project title, e.g. \"City of Glass\"")
    pi.add_argument("--path", help="parent directory (default: current dir)")
    pi.add_argument("--logline", help="one-line premise")
    pi.set_defaults(func=cmd_init)

    ps = sub.add_parser("status", help="show where every stage stands")
    ps.add_argument("path", nargs="?", help="project directory (default: current dir)")
    ps.set_defaults(func=cmd_status)

    proj_parent = argparse.ArgumentParser(add_help=False)
    proj_parent.add_argument("--project", help="project directory (default: current dir)")

    # run — autopilot over the whole cascade
    prun = sub.add_parser("run", parents=[proj_parent],
                          help="autopilot: generate the whole cascade end-to-end")
    prun.add_argument("premise", nargs="?", help="premise (seeds/overrides the concept)")
    prun.add_argument("--only", help="run just one tier by key (e.g. world_bible)")
    prun.add_argument("--force", action="store_true", help="regenerate even completed tiers")
    prun.add_argument("--no-notion", action="store_true", help="skip mirroring to Notion")
    prun.set_defaults(func=cmd_run)

    # refs — lock each character's look with a reference portrait
    pref = sub.add_parser("refs", parents=[proj_parent],
                          help="render a locked reference portrait per character (IP-adapter)")
    pref.add_argument("--only", help="just one character by id")
    pref.add_argument("--force", action="store_true", help="re-roll even locked references")
    pref.set_defaults(func=cmd_refs)

    # art — render keyframes from shots
    part = sub.add_parser("art", parents=[proj_parent],
                          help="render keyframes from shots (local ComfyUI)")
    part.add_argument("--only", help="render just one shot by id")
    part.add_argument("--limit", type=int, help="render at most N shots (great for a quick test)")
    part.add_argument("--force", action="store_true", help="re-render even completed keyframes")
    part.set_defaults(func=cmd_art)

    # story <concept|...>
    pstory = sub.add_parser("story", help="the writers' room — generate narrative tiers")
    pstorysub = pstory.add_subparsers(dest="story_cmd", required=True)
    psc = pstorysub.add_parser("concept", parents=[proj_parent],
                               help="tier 1 — premise -> structured concept")
    psc.add_argument("premise", nargs="?", help="one-line premise (default: project logline)")
    psc.set_defaults(func=cmd_story_concept)

    # notion <verify|init|push|pull>

    pn = sub.add_parser("notion", help="sync the story cascade to Notion (approval surface)")
    pnsub = pn.add_subparsers(dest="notion_cmd", required=True)

    pnsub.add_parser("verify", parents=[proj_parent],
                     help="check the token + database access").set_defaults(func=cmd_notion_verify)

    pni = pnsub.add_parser("init", parents=[proj_parent], help="create the Notion database + rows")
    pni.add_argument("--parent", help="Notion parent page id or URL (shared with the integration)")
    pni.add_argument("--force", action="store_true", help="recreate even if already initialized")
    pni.set_defaults(func=cmd_notion_init)

    pnsub.add_parser("push", parents=[proj_parent],
                     help="push tiers -> Notion pages").set_defaults(func=cmd_notion_push)
    pnsub.add_parser("pull", parents=[proj_parent],
                     help="read approvals Notion -> state.json").set_defaults(func=cmd_notion_pull)

    return p


def main(argv=None) -> int:
    from .env import load_dotenv
    load_dotenv()                    # secrets from studio/.env before anything reads them
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except notion_mod.NotionError as e:
        print(f"Notion error: {e}", file=sys.stderr)
        return 2
    except ProviderError as e:
        print(f"Provider error: {e}", file=sys.stderr)
        return 2
    except orch.OrchestratorError as e:
        print(f"Run error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
