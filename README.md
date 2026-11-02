# ollama-cli

Local-first terminal chat client for [Ollama](https://ollama.com) models.
Single-file Python application built on `rich` and `prompt_toolkit`, talking
only to a local Ollama server (default `http://localhost:11434`). No hosted
model, no telemetry upload, no shell execution.

**License:** Apache-2.0 (see `LICENSE`).

---

## Current repository state — read this first

This repo snapshot is **mid-transition**, and the files below do not all agree
with each other. The facts, verified against the working tree on 2026-11-03:

| Item | State in this repo |
| --- | --- |
| Newest code | `src/main_v1.6.py` — 2,018 lines, 82,153 bytes, SHA-256 `d6297bc6a8fbc8d08028a39720d00aef05cdbb0f495ed9ce155fa8b59dcae892` |
| Pinned build per project policy | v1.2, `main.py`, hash `257ff71c...` — **`main.py` does not exist in this tree** |
| Proposal history files | `main_v1.1.py` … `main_v1.5.py` referenced by the changelog — **none of these exist here either** |
| Tests present | `tests/test_main_v1_6.py` only (12 tests). The legacy suites it implies (v1.1–v1.5) are not in this tree. |
| `pyproject.toml` | Declares version `1.2`, entry point `main:main`, `py-modules = ["main"]` — none of which match the actual `src/main_v1.6.py` layout |
| Live verification (P10) | Still open. Everything below rests on mocked/unit tests only; no run against a real Ollama server has been recorded. |

Project rule (from `AGENTS.md`): *a new version is a proposal until Julian
pins it; never infer the release build from recency.* Under that rule the
current pin would be v1.2 — but the pinned artifact itself is absent from this
snapshot, so **there is nothing installable as "released" here**. Treat
`src/main_v1.6.py` as the latest proposal only.

---

## Features (as implemented in `src/main_v1.6.py`)

### Core REPL
- Streaming chat against Ollama's `/api/chat`, rendered with Rich (Markdown output, live streaming display).
- Session persistence: conversations saved as JSON under `~/.ollama_cli_history/sessions/<name>.json`, written atomically with `0600` permissions (POSIX; best-effort on Windows, where `os.chmod` sets no ACL).
- System-prompt presets (`coder`, `concise`, `academic`, `creative`, `tutor`, plus user-saved presets) stored in `~/.ollama_cli_history/system_prompts.json`.
- Tab completion for commands, models, sessions, presets, parameters, and paths (`prompt_toolkit` completer), with input history in `~/.ollama_cli_history/input_history.txt`.

### Safety & correctness hardening (added across v1.1–v1.2 proposals)
- **File injection safeguards** (`/file`): 256 KB size cap (refused, not truncated), binary-content refusal, credential/private-key warning with explicit confirmation before injection. Injected file content is untrusted input to the model, and it is saved into the session file.
- **Session recovery**: `/new` refuses an existing name instead of silently loading it; corrupted session files reset to an explicit empty state.
- **Failed-turn handling**: non-200 responses, network errors, empty/malformed/cancelled streams discard the turn rather than leaving it queued for resend.
- **Parameter validation and a single client**: one `OllamaClient` with explicit timeouts (3 s metadata/tags, 5 s connect + 60 s read for chat streaming, 5 s + 120 s for pulls); range-checked parameters (`num_ctx` 256–131072, `temperature` 0.0–2.0, `top_p` 0.0–1.0, `top_k` 1–100, `num_predict` 1–32768, `repeat_penalty` 0.0–2.0).
- **Context budget** (`/context`): fixed-order context build (system, history, injected files, current message), token estimate of ~1 token per 4 characters (an estimate, not a tokenizer count), oldest messages dropped first, over-budget turns refused.
- **Telemetry honesty** (`/tokens`, verbose metrics panel): per-turn durations and counts from the final streaming chunk; session prompt tokens report the last turn's full-context count (not an inflated sum); unavailable values show as `n/a`, not `0`.

### Newer proposal features (v1.3–v1.6, cumulative in `main_v1.6.py`)
- **v1.3 — Windows `/file` fix**: path splitting no longer uses POSIX `shlex`, so backslash paths survive; quoted paths with spaces still work.
- **v1.4 — Dynamic system-prompt variables**: `{{role}}`-style placeholders in presets/text, filled inline (`/system coder role=auditor`) or prompted once each; `/system vars`, `/system refill`; template and values persist in the session file.
- **v1.4 — Ephemeral chats**: `/newchat` (alias `/fresh`) starts a fresh chat keeping model, params, and system prompt, writing no session file; startup flag `--ephemeral` / `--fresh`.
- **v1.5 — Think parameter**: `/params think on|off|unset` sends Ollama's top-level `think` field on `/api/chat` (never inside `options`); `--no-think` startup flag; persisted per session.
- **v1.6 — Themes**: `/theme classic|cyberpunk` and `--theme`. Cyberpunk is neon pink `#ff2a6d`, cyan `#05d9e8`, purple `#b967ff` on the terminal's own background. Theme is a global preference in `~/.ollama_cli_history/theme.json`, not session state. Known limit: body success/warning/error lines keep semantic colours and are not yet theme-driven.

### Commands
`/help` `/system` (+ `vars`, `refill`) `/models` `/params` (+ `think`) `/theme`
`/verbose` `/file` `/sessions` `/new` `/newchat` `/load` `/multiline`
`/tokens` `/context` `/history` `/exit`

Startup flags: `--ephemeral` / `--fresh`, `--no-think`, `--theme {classic,cyberpunk}`.

---

## Requirements

- Python **3.12** only. `pyproject.toml` pins `>=3.12,<3.13` and the project
  policy forbids claiming any version not actually tested; the test result
  cited in the changelog was produced on 3.12.3.
- A running local Ollama server.
- Pinned runtime dependencies (`requirements.txt`, tested 2026-10-27):
  - `requests==2.34.2`
  - `rich==15.0.0`
  - `prompt_toolkit==3.0.53`
- Dev tooling (`requirements-dev.txt`): `ruff==0.8.0` (lint + format).

## Installation

**Note:** the packaged install path is currently broken in this snapshot —
`pyproject.toml` points at a `main` module that does not exist here (see
*Current repository state*). Until packaging is reconciled, run the source
file directly:

```bash
git clone <this repo> && cd ollama-cli
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

python src/main_v1.6.py            # start the REPL
python src/main_v1.6.py --help     # CLI flags, exits without touching Ollama
```

The intended (v1.2-era) packaged flow, once a pinned `main.py` is restored to
the tree root and `[tool.setuptools]` matches it:

```bash
pip install .
ollama-cli
```

## Running the tests

`tests/test_main_v1_6.py` resolves its target as `../main_v1.6.py` relative to
the `tests/` directory, i.e. it expects the source at the **repo root**, while
this snapshot keeps it under `src/`. As committed, discovery fails with
`FileNotFoundError`. Two ways to run it without moving tracked files:

```bash
# Option A: copy side-by-side into a scratch dir
mkdir -p /tmp/verify/tests
cp src/main_v1.6.py /tmp/verify/
cp tests/test_main_v1_6.py /tmp/verify/tests/
cd /tmp/verify && python -m unittest discover -s tests

# Option B: symlink at the repo root (untracked helper, delete when done)
ln -s src/main_v1.6.py main_v1.6.py
python -m unittest discover -s tests
rm main_v1.6.py
```

Verified result (2026-11-03, this VM, Python 3.12.10): **12 tests, all
passing** via Option A. This covers only the v1.6 test module; the larger
suites the changelog cites (up to 83 tests) are not present in this tree.

Lint/format gate (per `pyproject.toml`, applies to the active proposal and
tests):

```bash
pip install -r requirements-dev.txt
ruff check .
ruff format --check .
```

## Troubleshooting

- **"Connection refused" / model list empty** — Ollama isn't running or isn't
  on `http://localhost:11434` (hardcoded default in `OllamaRichCLI.__init__`).
  Start it with `ollama serve` and pull at least one model (`/models` also
  offers pull).
- **Chat aborts mid-generation** — the chat stream read timeout is 60 s; slow
  model loads or long pauses between tokens can trip it. Timeout policy is a
  known open decision.
- **A file won't inject** — `/file` refuses files over 256 KB and files with
  NUL bytes in the first 8 KB. Split the file or paste a smaller excerpt.
- **Windows** — partial fixes landed in the v1.3 proposal (path splitting),
  but Windows is **not a claimed supported platform**: `0600` permission
  enforcement is POSIX-only, and no live Windows run has been recorded.
- **Corrupted session file** — the CLI resets to an explicit empty state; the
  bad file is left on disk for you to inspect (session files contain full
  conversation content, including injected files — treat them as sensitive).

## Project governance notes

- `AGENTS.md` records the must-not-drift rules (local-first, no shell exec, no
  telemetry upload, no unverified claims) and the known bug list.
- `CHANGELOG.md` tracks every proposal and pin with hashes, sizes, and exact
  test counts. Per its own update rule, any change to code, tests, or docs
  requires a changelog entry in the same change. **This README update is
  documentation-only: no code changed, and the missing pin is a pre-existing
  condition, not something introduced here.** Flagging it for the owner: the
  changelog rule will need an entry recording this doc sync and the
  repo-state discrepancy.
- Open items owned by Julian: restoring/reconciling the pinned artifact and
  packaging layout, live verification (P10), supported platforms, and whether
  single-file distribution stays the release artifact.
