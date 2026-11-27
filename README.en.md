# Novel Studio · A Writing Workbench for Web Serials

[简体中文](README.md) · [English](README.en.md)

A personal writing workbench for long-form Chinese web fiction. It turns *premise → outline → world bible → foreshadowing → beat sheets → prose → review → archive → memory write-back* into one reversible production line, instead of another chat box.

- **Prose always lives on disk as Markdown**: `chapters/NNN-title.md`, openable in any editor.
- **Settings, beat sheets, foreshadowing, and memory live in SQLite**: shared across books, read and written through one domain layer.
- **Continuity is computed, not remembered**: character state, departed cast, item holders, and foreshadow payoffs come from ledgers rather than model recall.
- **Structure is visible**: the character graph, organization chart, career ladder, and chapter graph are all derived from existing ledgers, not invented.
- **Review has two layers**: deterministic checks run offline; the AI pass only judges a fixed checklist item by item. The five aesthetic dimensions give opinions without blocking archiving.
- **Manual edits sync back**: edit prose outside the app and the index, chapter memory, and character state are realigned by content fingerprint.
- **One-click TXT export**: the whole book with chapter numbers and headings, written to `exports/` and downloaded as the same file.

Stack: Vue 3 + Pinia + Vite, FastAPI + SQLite. It grew out of the DeepSeek Harness plugin `novel-studio` and is now a standalone web app.

## Quick Start

Requirements: Python ≥ 3.11, [uv](https://docs.astral.sh/uv/), Node.js ≥ 18, and npm.

```bash
./scripts/dev.sh          # start API + web, Ctrl-C stops both
./scripts/dev.sh open     # start and open the browser
./scripts/dev.sh status   # ports, health check, log locations
./scripts/dev.sh stop     # stop by port, including orphaned processes
```

- Web: <http://127.0.0.1:5180>
- API: <http://127.0.0.1:8010/api/ping>
- Logs and pid files live in `.run/` (gitignored).

Or run each side separately:

```bash
make api      # backend (uv + uvicorn, port 8010)
make web      # frontend (Vite, port 5180)
make test     # backend pytest + frontend vitest
make build    # frontend type-check + production build
```

The first start runs `uv sync` / `npm install` automatically. Model settings are entered on the Settings page and stored in `data/gateway.json` (gitignored, never committed).

## Workflow

| Step | Output | Notes |
|---|---|---|
| 1. Premise | Title, synopsis, chapter count, words per chapter | "Another batch" carries fingerprints of the previous batch so ideas do not collapse into one shape |
| 2. Outline + worldview | `outlineText` / `worldText` + volume table | Volumes split by conflict phase, not equal chapter counts |
| 3. Settings | Characters, relations, information gaps, factions, locations, items, rules, power system, society, history, glossary | Only fills empty fields; never overwrites existing entries |
| 3.5 Structure | Organizations, career ladders | Who reports to whom inside a faction and what promotion costs; organized from existing settings, never inventing people |
| 4. Foreshadowing | Core / volume / plot threads | Payoff chapter must be later than the setup chapter; **prose is blocked without at least one thread** |
| 5. Segment plan | One segment per 3–30 chapters (default 10) | Goal, turn, pacing, scene, cast |
| 6. Chapter beats | Per-chapter beats, pressure, opening and ending state | Review before writing prose; when chapter numbers pass the last volume, Rolling Plan adds the next volume first |
| 7. Prose | `chapters/NNN-title.md` | Streamed; a failed chapter can be retried or skipped |
| 8. Review | Deterministic checks, AI re-check, skill-based rewrite | New drafts return to "pending"; old drafts go to Discarded |
| 9. Archive | Index status + memory write-back | Position/item/state changes merge into the bible only after the whole batch is archived |

The writing panel runs the loop end to end: **pick chapters → confirm style → choose skills → inspect references → generate one chapter at a time**. A `runId` guard prevents two windows from writing the same chapter at once.

## Core Mechanics

### Three-layer character state

Character state is split into three non-overlapping layers:

- **Debut state** `appearanceStatus` + `firstChapter`: the state when the character first appears in prose.
- **Current state** `status` + `statusAt` / `statusLog`: only what has actually been written, recorded per chapter.
- **Exit and ending** `exitChapter` (occurred or planned) and `finalStatus` (state at the end of the book).

A character planned to die in chapter 76 still reads "present (dies from chapter 76)" while writing chapter 56, never "dead". Characters not yet introduced read "not yet introduced". Archive write-back only applies explicit life/death/exit facts from chapter memory; model guesses are ignored. Rejecting a chapter also rolls back its debut and death records. Explicit resurrections, rebirths, or body possessions with stated means and costs (e.g. in xianxia/fantasy) are excused from departed-character conflicts, and departed characters named in the current chapter's beats or focus are flagged in the pre-write constraint so the model explains their return clearly.

### Four kinds of rules

Every world rule carries an `enforce` level:

| Level | Breakable? | Cost |
|---|---|---|
| Iron law | No, only circumvented | Breaking it invalidates the world or the character |
| Contract | Yes | An explicit immediate cost (backlash, shortened lifespan, memory loss, retaliation) |
| Convention | Yes | Social cost (exile, lost credibility, offending a faction) |
| Rumor | Characters believe it is true | Breaking it reveals the truth |

Rules also carry `cost`, `boundary` (when it does not apply / where the loophole is), and `enforcer`. Costs and limits for a power system are **optional by genre**: dark fiction can make "power has a price" central; light power fantasy can leave them empty.

### Chapter truth and data safety

- "How far the book is written" comes only from the highest chapter number in `chapters/index.json` (`written_through()`). `project.currentChapter` and `gate.chapter` are derived values; archiving an older chapter never rolls the "next chapter" pointer back.
- Before a whole book is deleted, its directory is copied to `data/deleted/`, then the directory and database rows are removed. There is no in-app restore, but a complete disk copy remains.
- Before prose is overwritten, the old file is kept in `chapters/.versions/NNN/`, with the latest 20 versions per chapter.

### Memory

Memory is derived from prose. It is written back after every chapter lands, recomputed after a rewrite, and volume summaries update at the end of a volume.

- Chapter memory: in-story time, locations, cast, key events, who knows what, relationship changes; full flashback chapters carry `isFlashback` (skipped during bible state write-back) and partial flashback moves/state entries carry `flashback: true` so past events never overwrite current-timeline state. When the previous chapter is a flashback, the "previous chapter ending" context automatically links back to the most recent mainline chapter.
- Volume summary: main plot, subplots, relationships, reader knowledge, setup for the next volume, deviations from the outline.
- Timeline: projected per chapter, maintained only on the Memory page; individual events can be marked as flashbacks.
- A failed write-back never fails the chapter; it leaves a gap on the Memory page that can be filled for one chapter or in bulk.
- With automatic memory enabled, **a missing chapter memory blocks archiving** (409 `memory-gap`); an explicit force is required to archive anyway.

Set `DSH_NOVEL_AUTO_MEMORY=0` to disable automatic write-back (used by tests and offline environments).

### Organizations and careers

Split by responsibility, without storing the same fact twice:

- **Factions** answer which camps exist, how they feel about each other, and who leads them;
- **Organizations** (`bible.organizations`) answer who reports to whom inside a camp: `faction` links the camp, `parent` names the superior, `members` records each person's role and rank;
- **Careers** (`bible.careers`) answer what promotion requires: who it applies to, advancement rules, and the ladder from low to high with the gap at each step.

A top-level organization often is the faction itself: when the names match, its leader and description are read from the faction card instead of being stored twice, so the two pages cannot disagree. Sub-organizations keep their own leader and description. Grudges and hidden rules belong to the faction only and are never copied onto organizations.

"Organize from existing settings" reads characters, factions, and the power system, fills only empty fields, and never overwrites what the author wrote. Character names must come from existing data. Unknown factions, broken parents, members missing from the character list, and parent cycles are flagged on the page, with a link back to the faction card. Both layers also enter the prose reference pack.

### Rolling plan

`project.compassText` is the author's direction: what the protagonist wants, what must not change, and the conflict the author most wants to write now. When the written chapter passes the last volume, Rolling Plan in Outline → Structure:

1. Generates the next volume's heading and major beats from the compass, book-level outline, last volume, and the last six chapter memories, appends it to `outlineText`, and refreshes the volume index;
2. Then generates the next batch of per-chapter beats.

It only appends; existing volumes and beats are never rewritten. Choose 3/5/8/10 chapters per run, or force a re-plan.

### Chapter graph and related chapters

Outline → Chapter Graph draws written chapters from existing ledgers:

- Nodes: chapter length, verdict, volume, and cast;
- Upper arcs: foreshadowing from setup to payoff (open threads point at the due chapter; planned payoffs are dashed);
- Lower arcs: chapters within 10 of each other that share at least two cast members.

Related-chapter recommendations are pure rule scoring (no model): shared cast, foreshadow setup/payoff, continuing location/faction/item state, same volume, and recency, each with a readable reason. They enter the prose reference pack automatically and are also available from `GET /api/projects/related-chapters`.

### Manual-edit sync

Prose can be edited outside the app, but the index, chapter memory, and character state then lag behind. Progress → Sync Manual Edits finds differences by content fingerprint (`sha256`):

- `edited`: prose changed outside the app;
- `untracked`: a prose file exists but is not in the index;
- `baseline`: an old book with no fingerprint; the first pass only records one;
- `memory-stale`: prose unchanged, but chapter memory was not distilled from it;
- `missing`: indexed, but the prose file is gone (not processed).

For each selected chapter it runs `undo_chapter` → regenerate chapter memory → `reapply_chapter` → recompute length/verdict/hook. Memory regeneration can be turned off to only recompute index fields. A failed chapter does not block the rest, and its fingerprint is not advanced, so the next scan finds it again.

### Five aesthetic dimensions

Hard metrics are covered by deterministic checks and the fixed AI checklist; wording, rhythm, dialogue, imagery, and emotion get a separate lightweight review:

- Each scores 1–5, must quote 8–30 characters from the prose, keeps the comment under 60 characters, and gives one actionable fix;
- Results go to `ledger/aesthetic.jsonl`, folded per chapter, together with the prose fingerprint;
- If the prose changes without a re-review, the panel marks the comments as based on an old draft;
- It only gives opinions; it never edits prose or blocks archiving.

### Export

Progress → Export TXT lays out the whole book as plain text by chapter number: title, genre, and logline as a header, one "Chapter N Title" line per chapter, two blank lines between chapters. The file is written to `exports/title-time.txt`, and the browser downloads the same content. Missing prose files, empty chapters, and chapter-number gaps are reported.

### Review and rewrite

- **Deterministic checks** (no model): length, platform format, AI tells (category/count/quotes/paragraph and offset), chapter-end hook, hard rules, and departed characters reappearing. False positives can be dismissed per item and stop blocking archiving.
- **Quality supplements**: repeated six-character phrases across chapters, verbatim repeated sentences within a chapter, dialogue ratio, sentence/paragraph rhythm, lexical diversity, and whether every beat completed "who → wants → blocked → result".
- **AI re-check**: judges a fixed checklist item by item — required/forbidden beats, foreshadow setup/payoff, items/locations/factions against the bible, hard world rules, character state as of the previous chapter, continuity with the previous chapter's ending, in-chapter consistency, and limited POV. A failed item must quote the prose; the chapter passes only when the whole checklist passes.
- **Skill-based rewrite** changes only the paragraphs tied to findings, preserving established facts and reveal order. Before writing, hard guards re-run: too short, below the minimum length, hitting a rule, or visibly flattening rhythm/dialogue/lexical variety all reject the draft and leave the old text untouched.
- Re-checks are round-based: refreshing only removes resolved items without asking the model again; a full rewrite or a new round re-judges everything.
- Old drafts go to Discarded and can be restored. Rejecting a chapter frees its number for an immediate rewrite.

## Pages

The sidebar is grouped by how a writing day actually flows:

| Group | Pages |
|---|---|
| Workbench | **Today** (what to do now), **Start** (the pipeline), **Style** (book defaults + author references) |
| Writing | **Progress** (per-chapter review/checks/rewrite/archive), **Discarded** |
| Planning | **Outline** (structure/worldview/map/chapter graph + rolling plan), **Beats** (segment plan + references), **Foreshadowing** |
| Reference | **Characters** (cards/relationship matrix/graph/location trail), **Organizations** (org chart/career ladders), **Memory** (timeline/recap/search), **Bible** (rules/world depth/factions/locations/items/information gaps) |
| System | **Settings** (appearance/autosave/model/repair/usage) |

Appearance has three modes — follow system, light, dark — defined once with `light-dark()` tokens and stored in `localStorage`.

## Reference Pack

Before generating beats or prose, the app assembles exactly what will be injected: volume outline, current beat, foreshadowing, character cards (aliases/state/relations), rules, worldview, factions, locations, items, power system, organizations, career ladders, society, history, glossary, locations and item holders, information gaps, recent chapter memory, related-chapter recommendations, volume summaries, timeline, previous chapter ending, departed cast, style, and platform guidance.

`GET /api/projects/chapters/{n}/references` reports the same entry counts and missing items the prompt sees, powering the in-app "chapter references" panel. When the budget is tight, entries are packed whole by relevance; overflow is collapsed into a one-line roster instead of silently dropping characters. During prose generation, background-heavy sections (volume outline, other open threads, volume summaries, society, history) automatically use tighter stage budgets to avoid diluting model attention.

Before prose generation, an entity-resolution pass finds the people, places, items, factions, terms, and threads this chapter will use — from the beat sheet, segment step, previous chapter memory, recent cast, and author notes — each with its source. The author can exclude any entry in the panel.

## Model Configuration

Writing uses any OpenAI-compatible endpoint; configuration is shared across books:

- File: `data/gateway.json` (`NOVEL_STUDIO_HOME` can move the data directory).
- Settings page: Base URL, prose model, fast model, and "Test connection".
- The main long-running generations have SSE variants (premise, outline, settings, foreshadowing, beats, prose, rewrite): `stage`, `delta`, `reason` (thinking), `done`, and a unified `error`.
- Reasoning effort is routed by stage: blueprint/concepts/settings `high`; beats/foreshadowing/prose/rewrite `medium`; memory `none`. Override with `NOVEL_STUDIO_REASONING='{"prose":"high"}'`.
- The non-streaming prose endpoint accepts `candidates: 1–3`, writes several drafts, and picks one by length, AI tells, and rhythm. The UI streams, so it uses 1 draft by default.
- Unparseable model JSON gets one repair attempt (trailing commas, unescaped quotes); settings requests also get one retry.

Synchronous endpoints remain available for scripts and older callers.

## Storage

| Data | Location |
|---|---|
| Book settings, characters, worldview, factions/locations/items/rules, style | SQLite: `data/studio.db` |
| Volumes, beats, segment plans, foreshadowing, chapter/volume memory, character state, relations, timeline | SQLite (same file) |
| Prose | Book directory `chapters/NNN-title.md` |
| Chapter index | `chapters/index.json` (includes prose `sha256`, the baseline for manual-edit sync) |
| Prose version history | `chapters/.versions/NNN/*.md` (latest 20 per chapter) |
| Aesthetic reviews | `ledger/aesthetic.jsonl` (folded per chapter, carries the prose fingerprint) |
| Exports | Book directory `exports/title-time.txt` |
| Prompt modules | `prompts/*.md`; a same-named file in the book directory overrides it |
| Map / relationship graph | Book directory `map.json` / `relation_map.json` |
| Compatibility snapshots | Book directory `project.json` / `bible.json` |
| Pre-delete snapshots | `data/deleted/` |

Opening an old book imports it into SQLite on first read; `ledger/*.jsonl` is imported into the `ledger` table on first read and kept on disk for audit and export.

## Environment Variables

| Variable | Purpose |
|---|---|
| `NOVEL_STUDIO_HOME` | System data directory (SQLite / gateway.json / recent.json), default `<repo>/data` |
| `DSH_NOVEL_HOME` | Bookshelf root, default `~/Desktop/mine/xiaoshuo` |
| `DSH_NOVEL_ALLOWED_ROOTS` | Extra roots where new projects may be created (`:`-separated) |
| `DSH_NOVEL_DB` | Override only the SQLite file path |
| `DSH_NOVEL_RECENT_FILE` | Override the recent-books file |
| `DSH_NOVEL_AUTO_MEMORY` | `0` disables automatic memory write-back |
| `NOVEL_STUDIO_SNAPSHOT_DIR` | Pre-delete snapshot directory, default `<data>/deleted` |
| `NOVEL_STUDIO_REASONING` | Per-stage reasoning override, JSON |

## Project Layout

```text
backend/
  app/api/          # routes: books / studio / review / memory / style / extras / settings
  app/core/         # data home, book paths, delete and snapshot
  app/store/        # file layer + SQLite-compatible routing (project, chapters, ledger, locks, atomic writes)
  app/domain/       # writing, review, memory, continuity, quality, metrics, references…
                    #   structure: hierarchy, chapter_graph, related, rolling
                    #   book-wide: aesthetic, sync, export
  app/llm/          # OpenAI-compatible client, settings, stage routing
  tests/            # pytest (including golden comparisons)
frontend/
  src/views/        # 14 pages
  src/components/   # writing panel, review panel, memory components, command palette…
  src/api/          # backend data → view models
  src/stores/       # current book, writing runs, memory, checks, toasts
  src/design/       # theme tokens + component library
prompts/            # reusable writing-method modules
```

## Tests

```bash
make test        # backend pytest + frontend vitest
make test-store  # frontend only
```

Backend tests run fully offline (model calls are stubbed) and use temporary data directories and bookshelves; they never touch real data.

## Keyboard Shortcuts

- `⌘K` / `Ctrl K`: command palette — search pages, chapters, characters, foreshadowing, and actions.
- `/` opens the palette; `?` lists all shortcuts; `T` switches theme; `W` opens the writing panel.
- Press `G`, then `H/P/X/O/D/F/M/W/C/G/S/,` to jump between pages (the second `G` is Organizations).
- Progress page: `J/K` move between chapters, `↵` archives or expands, `R` rejects, `B` runs batch checks.

## Status

A personal project; the UI and wording are designed around Chinese web-serial writing habits. The domain layer was ported module by module from the former plugin's `lib/*.js`, with golden tests comparing key outputs; `make test` is the acceptance gate before every commit.

## License

Released under [AGPL-3.0](LICENSE). You may use, modify, and distribute it; if you offer a modified version as a network service, you must publish the source under the same license.
