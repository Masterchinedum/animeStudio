# anime_studio — the engine

A provider-agnostic anime studio system. The durable asset is the **project state**
(the *memory bank*, a folder of human-readable JSON), not any model. Models (local
Google Nano Banana image generation, Alibaba video API, and an LLM writers' room are
swappable contractors plugged
in behind common provider interfaces.

Design docs live one level up: `../anime_studio_architecture.md` (the system) and
`../story_engine.md` (the 10-tier narrative cascade).

## Status — Step 1 (foundation)

Built:
- **Schema** (`schema.py`) — every durable shape: Project/StyleGuide, Character,
  World, Scene, Shot, and the narrative tiers (Concept → … → TimedTranscript).
- **Continuity ledger** (`ledger.py`) — the anti-contradiction engine (tier 6),
  with delta (`establish`/`learns`/`move`/`advance_time`) and query methods.
- **Scaffolding + load/save** (`store.py`, `paths.py`, `serde.py`).
- **CLI** (`cli.py`) — `init` and `status`.

Also built:
- **Notion adapter** (`notion.py`) — the human approval surface. Pushes each story
  tier to a Notion database ("Story Cascade"); reads the `Approval` select back into
  `state.json`. Stdlib-only (urllib). Content flows engine → Notion; only approval
  flows back, so the JSON files stay the source of truth.

Not built yet (later steps): provider layer, story stage, art/animate/sound/assemble.

## Secrets (`.env`)

Keys live in `studio/.env` (gitignored) — one place to edit, easy to swap:

```
GEMINI_API_KEY=your-google-ai-studio-key
ANIME_NOTION_TOKEN=ntn_your-notion-token
```

A **filled** value overrides your shell (`~/.zshrc`), so editing `.env` always takes
effect. A **blank** value falls back to the shell, so you only manage what you want
here. See `.env.example` for the template.

## Notion (approval surface)

One-time setup (see `../HANDOFF.md` for the fuller note):
1. Create an internal integration at **notion.so/my-integrations**, copy its token.
2. Create a parent page in Notion, share it with the integration (⋯ → Connections).
3. `export ANIME_NOTION_TOKEN="secret_..."` (never commit the token).

Then, from inside a project folder:
```bash
../anime notion verify                       # check the token
../anime notion init --parent <page_id/URL>  # create the "Story Cascade" database + rows
../anime notion push                          # memory bank -> Notion (re-run to update)
# ...review in Notion, set Approval = Approved on the [GATE] rows...
../anime notion pull                          # approvals -> state.json (gates the engine)
```
`notion.json` (per project) stores the database id + tier→page mapping so pushes are
idempotent. Gate tiers (chapter breakdown, scene beats, timed transcript) are the ones
the engine will block on.

## Autopilot — one command (the whole point)

Once a project is set up (below) and your `GEMINI_API_KEY` is set, a single command
drives the whole narrative cascade end-to-end — generate, validate + auto-retry,
checkpoint after each tier, resume on re-run, and mirror to Notion for review:

```bash
cd ~/anime-ai-workspace/studio/<project>
../anime run "your premise here"     # concept -> world -> characters, unattended
../anime run                          # continue where it left off (skips done tiers)
../anime run --force                  # regenerate everything from scratch
../anime run --only world_bible       # just one tier
```

The narrative cascade runs with no human stops. The only gate (coming with the video
stage) is an optional keyframe approval before the *paid* cloud-video render — the one
pause that saves money rather than costing time.

## Set up a project (no install, no venv — stdlib only)

```bash
cd ~/anime-ai-workspace/studio
./anime init "Working Title" --logline "one-line premise"
cd working_title
../anime status
```

`init` scaffolds the memory-bank folder and is **idempotent** — re-running never
clobbers existing files. `status` reads the project and shows where every stage and
story tier stands.

## The memory-bank layout

```
myproject/
├── project.json          title, logline, global style guide, config
├── bible/
│   ├── characters/<id>.json
│   └── world.json
├── narrative/            the story-engine cascade
│   ├── concept.json      tier 1
│   ├── series_arc.json   tier 4
│   ├── chapters/         tier 5
│   ├── episodes/         tier 7
│   ├── beats/            tier 8
│   ├── transcript/       tier 10  ← the render spec
│   └── ledger.json       tier 6
├── script/{story.json,scenes/}
├── shots/<id>.json       the atomic render unit
├── assets/{keyframes,refs,clips,audio}/
├── state.json            pipeline progress + tier approval gates (resumable)
└── providers.json        provider routing + failover
```
