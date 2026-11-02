# ollama-cli

Local-first terminal chat client for Ollama models. Rich terminal UI, prompt_toolkit input with history and tab completion, session persistence, system prompt presets, file injection, runtime parameter control, and inference telemetry.

Status: early, single-file build. Pinned v1.2, not yet live-tested against an Ollama server from this workspace.

## Pinned build

- Version: v1.2, pinned 2026-10-27 at Julian's direction
- File: `main.py`, with `main_v1.2.py` kept as the identical version copy
- Previous pin, superseded: v1.1, 997 lines, 47,277 bytes, SHA-256 `664c1529078783245da51ceebbe383fb109689e7214c0ae7aa0e6cb50a7083cc`
- Size: 1447 lines, 58,363 bytes
- SHA-256: `257ff71c040dc8e6e814c5978eeeaee41ca98f9e4b5e5f97a631ad3c5aaf69ad`
- Verification done here: syntax compile check, 36 unit and mocked-API tests passing, ruff lint and format clean, and a clean-virtual-environment `pip install .` check that produced the `ollama-cli` console script. No live Ollama run was made from this workspace, so live behavior is unverified, and the pin rests on mocked tests only.
- v1.2 implements P1 to P9: tests and failure handling, file injection safeguards, session recovery, failed-turn handling, parameter validation with a single Ollama client, honest telemetry, a context builder with a `num_ctx` budget, a modular split for testability, pinned dependencies, Apache-2.0 license, CI, and packaging with the console script.
- A new version is a proposal until Julian pins it. Do not overwrite `main.py` on recency alone.

## Requirements

- Ollama server, default `http://localhost:11434`
- Python 3.12, tested on 3.12.3 only. Do not assume another version works until it is tested.
- Pinned runtime dependencies in `requirements.txt` and `pyproject.toml`: `requests==2.34.2`, `rich==15.0.0`, `prompt_toolkit==3.0.53`. Development tooling (ruff 0.8.0) is pinned separately in `requirements-dev.txt` and is not a runtime dependency.

## Install and run

From a checkout, in a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Or install the pinned module into the environment, which provides the `ollama-cli` console script:

```bash
pip install .
ollama-cli
```

`python main.py` and `python -m main` still work from a checkout.

On first start it loads the `default` session if one exists, otherwise it picks the first model returned by Ollama. If no model is available, set one with `/models` after starting Ollama.

## Troubleshooting

- `Connection refused` or an empty model list: Ollama is not running, or not on `http://localhost:11434`. Start Ollama first, then check `curl http://localhost:11434/api/tags` returns a model list.
- No models listed: pull one with Ollama first (for example `ollama pull <model>`), then use `/models` in the CLI to select it. The CLI does not download models on its own except through its `/models` pull path.
- A chat turn fails or times out: the failed turn is discarded, not left in history to be resent. Check Ollama is up, the model is loaded, and the context estimate from `/context` is within `num_ctx` (default 4096).
- A file will not inject with `/file`: files over 256 KB are refused, binary files are refused, and apparent credentials or private keys trigger a warning with confirmation. Those are deliberate safeguards, not a bug.
- A session will not load: a corrupted session file resets to an explicit empty state instead of silently keeping stale state. `/new` refuses an existing name instead of loading it and printing a clean-session message.
- Tests fail with `ModuleNotFoundError: No module named 'rich'` (or `requests`, `prompt_toolkit`): the test run used a Python without the pinned dependencies installed. Install `requirements.txt` into the test environment first, then run `python -m unittest discover -s tests -v`. Live-model tests are not a CI gate, because model load time and hardware vary.

## What it does now

- Chat with streaming Markdown output against Ollama `/api/chat`
- Model list, switch, pull, and delete through `/models`
- Sessions in `~/.ollama_cli_history/sessions/`, with `/sessions`, `/load`, and `/new`
- System prompt presets through `/system`, including `coder`, `concise`, `academic`, `creative`, and `tutor`, plus saved custom presets in `~/.ollama_cli_history/system_prompts.json`
- Runtime parameters through `/params`: `num_ctx` (default 4096), `num_predict` (512), `temperature` (0.7), `top_p` (0.9), `top_k` (40), `repeat_penalty` (1.1)
- File injection through `/file <path> [query]`, which reads a file and sends it as model context
- Token and timing telemetry after each turn through `/verbose` and `/tokens`
- Context estimate and dropped-message report through `/context`, with oldest messages dropped first and over-budget turns refused
- Multiline input through `/multiline` and triple-quoted blocks
- Tab completion for commands, models, sessions, presets, parameters, and file paths

## Commands

| Command | Use |
|---|---|
| `/help` | Command reference |
| `/models [name]` | List, switch, pull, or delete models |
| `/params [key value]` | View or set generation parameters |
| `/system [preset or text]` | Manage the active system prompt |
| `/file <path> [query]` | Inject a local file into context |
| `/sessions`, `/load <name>`, `/new <name>` | List, switch, or start sessions |
| `/tokens`, `/verbose`, `/history`, `/multiline` | Telemetry, history, and input mode |
| `/context` | Context estimate, budget, and dropped messages |
| `/exit` | Quit |

## Proposal verdict, in brief

Analyzed against the actual code on 2026-10-27. Full reasoning is in `AGENTS.md`.

Adopt now, because the code has the gap today:

- Tests for command parsing, session save/load/switch, and failure paths, plus mocked Ollama API tests. There is no test suite at all.
- File injection safeguards: a size cap, a binary-file check, and a warning for apparent credentials or keys. `/file` currently reads any readable file without a cap and stores its content in the session file.
- Session recovery: atomic writes, corrupted-file handling, and a fix for `/new` loading an existing session instead of starting clean.
- Parameter validation with real ranges, and one consistent Ollama client with explicit timeouts and error handling. Timeouts today are 2s, 3s, and 10s in different places, and a failed chat turn stays in history.
- Telemetry definitions and honest missing values. Session prompt tokens currently re-count the full context on every turn, so the session total inflates.

Adopt next, after the above:

- A dedicated context builder with a token budget, truncation, and a report of what was dropped.
- A modular split (CLI, session store, Ollama client, context, telemetry) only as far as it makes the services testable without the terminal.
- CI, pinned dependencies, and packaging.

Defer until the core is reliable:

- Tool registry, agent loop, retrieval, provider abstraction, and an evaluation suite. The proposal itself puts these in Phase 5, and that ordering is right.

Already done, or not a gap:

- No shell execution from user input. The code uses HTTP requests only.
- Session names are sanitized to alphanumerics, `-`, and `_`, which blocks path traversal in session files.
- Streaming output, model switching, and preset handling already work in code, subject to live testing.

Not decided, and not assumed:

- License. Apache-2.0, chosen by Julian 2026-10-27, see `LICENSE`.
- Supported platforms and Python versions. Do not claim Windows, Linux, and macOS support until tested on each.

## Known limits

- Context estimate is 1 token per 4 characters, stated as an estimate only. It is not an exact tokenizer count for the model in use.
- No quiet logging level. Telemetry is on by default.
- Session files are written atomically with 0600 permissions, but preset files use default permissions and nothing is encrypted. They contain conversation content, including injected files.
- License: Apache-2.0, see `LICENSE`. Copyright 2026 Julian Gonzalez.
- A document loaded with `/file` becomes model context. Treat untrusted local documents as untrusted input, not as instructions.
