# Changelog

All notable changes to ollama-cli are recorded here. A version is a proposal
until Julian pins it. The pinned version is the only version that counts as
current, regardless of how recent another file is.

## Update rule

Every change to the project, code, tests, or docs, adds an entry here before
it is pinned or delivered, in the same change, not afterwards. An entry must
state: the date, what changed and why, the affected files, the new main.py
hash and size if main.py changed, and the test result with the exact count.
A test-only change states that main.py is unchanged and the pin is unaffected.
A change with no entry is incomplete, even if the code works. This rule is
also recorded in AGENTS.md, so any agent working here follows it.

## v1.6, proposal, not pinned

- 2026-10-27, built from the v1.5 proposal (main_v1.5.py, SHA-256
  a20d85...), so the v1.5 think parameter is included. main_v1.6.py:
  2025 lines, 82,545 bytes, SHA-256 a4004e365f7369efbdb41ba04e4924a975d227224aac4c19a478f62cb0efae9e.
  Pinned main.py unchanged, hash still 257ff71c..., v1.2 still
  current. main_v1.5.py is preserved, not deleted, and neither
  proposal is pinned.
- Theme system with a cyberpunk scheme. Classic reproduces the
  pre-theme colours exactly. Cyberpunk is neon pink #ff2a6d, cyan
  #05d9e8, purple #b967ff, with success #00ff9f and warning #f9c80e,
  on the terminal's own background, so no background colour is
  forced. The theme recolours the startup banner, the input prompt,
  the help table header, the system-prompt panel, and the telemetry
  panel, and /tokens shows the current theme. Body success, warning,
  and error lines keep their semantic colours and are not yet
  theme-driven, stated as a limit. Surfaces use concrete palette
  colours, not named theme styles, because Rich parses table header
  styles strictly and a named style would fail on a console without
  that theme; that failure was caught by the help test and fixed.
- Switching and persistence: /theme with no argument shows the
  current and available themes, /theme cyberpunk and /theme classic
  switch, and --theme does the same at startup. The theme is a
  global preference in ~/.ollama_cli_history/theme.json, not session
  content, so switching sessions does not switch themes, and
  ephemeral mode does not block it, the same way saving a preset is
  not session state. An unknown theme changes nothing, and a missing
  or invalid theme file falls back to classic at startup.
- Verification on this VM: 83 tests passing (71 legacy plus 12 new
  v1.6 tests), ruff check and format check clean, main() callable,
  --help exits 0 without touching Ollama and lists --theme. Live
  behavior is still unverified, and the pin still rests on mocked
  tests only.
- README and AGENTS are not updated for v1.6 until a pin, so the
  pinned v1.2 docs stay accurate.

## v1.5, proposal, not pinned

- 2026-10-27, built from the v1.4 proposal (main_v1.4.py, SHA-256
  1bf67ce...), so the v1.4 template and ephemeral features are
  included. main_v1.5.py: 1853 lines, 75,236 bytes, SHA-256 a20d85ec9ccdfdc5da41f5878c409dbd7bc4332c190ee870855804fcc8c2550a.
  Pinned main.py unchanged, hash still 257ff71c..., v1.2 still
  current. main_v1.4.py is preserved, not deleted, and neither
  proposal is pinned.
- Think parameter: /params think off disables thinking mode by
  sending Ollama's top-level think:false on /api/chat. It is not
  put inside options, where Ollama would ignore it as a generation
  parameter. /params think on sends think:true, /params think unset
  (also none, clear, default) sends no think field, which is the
  default and the behavior of every earlier version. The interactive
  /params menu gains think as option 7, /tokens shows the think
  state, and the startup flag --no-think sets think to False for the
  run, which a tracked session then persists on its next save, like
  /params think off. The setting is saved in the session file as
  "think" and reloaded on /load; an invalid stored value falls back
  to unset with a warning, and an invalid /params value changes
  nothing and writes nothing.
- Verification on this VM: 71 tests passing (58 legacy plus 13 new
  v1.5 tests), ruff check and format check clean, main() callable,
  --help exits 0 without touching Ollama and lists --no-think. Live
  behavior is still unverified, and the pin still rests on mocked
  tests only.
- README and AGENTS are not updated for v1.5 until a pin, so the
  pinned v1.2 docs stay accurate.

## v1.4, proposal, not pinned

- 2026-10-27, built from the v1.3 proposal (main_v1.3.py, SHA-256
  4eff357e...), so the v1.3 Windows fixes are included. main_v1.4.py:
  1739 lines, 70,774 bytes, SHA-256 1bf67ce295857656cf2ba4522b633325688dfee7dfbcb8da35fdf7a4603f6176.
  Pinned main.py unchanged, hash still 257ff71c..., v1.2 still
  current. main_v1.3.py is preserved, not deleted, and neither
  proposal is pinned.
- Dynamic system-prompt variables: presets and custom text may
  contain {{role}}, {{context}}, and similar placeholders, where a
  name is [A-Za-z_][A-Za-z0-9_]*. Rendering never invents a value:
  missing variables are reported, and the caller prompts for them.
  Usage: /system coder role=auditor context=payments fills inline
  with no prompt; /system coder with a templated preset prompts for
  each missing variable once, in template order; /system vars shows
  the active template, variables, and values; /system refill re-asks
  every variable with the previous value as default. The template
  and values are saved in the session file alongside the rendered
  prompt, so a templated prompt survives a reload and can be
  refilled; old sessions without those fields load as plain prompts.
  Saving a templated prompt as a preset saves the template, not the
  rendered text. Text starting with a preset word but followed by
  non-assignment text stays literal text, not a preset lookup.
- Ephemeral new chat: /newchat (alias /fresh) starts a fresh chat
  with the same model, keeping model, parameters, and system prompt,
  clearing only messages and counters, and writing no session file
  while ephemeral. save_history is a no-op in that mode, so model,
  parameter, and prompt changes during it are also not persisted,
  while saving a preset to the preset library still works. /load and
  /new end ephemeral mode and return to tracked sessions; exiting
  loses the ephemeral chat. Startup flag --ephemeral (alias --fresh)
  reaches the same state, and main() now takes an optional argv for
  that flag. /tokens shows the session mode.
- Verification on this VM: 58 tests passing (44 legacy plus 14 new
  v1.4 tests), ruff check and format check clean, main() callable,
  --help exits 0 without touching Ollama. Live behavior is still
  unverified, and the pin still rests on mocked tests only.
- README and AGENTS are not updated for v1.4 until a pin, so the
  pinned v1.2 docs stay accurate.

## v1.3, proposal, not pinned

- 2026-10-27, built from pinned v1.2. main_v1.3.py: 1468 lines,
  59,244 bytes, SHA-256 4eff357eecd4053ac3ff16ba1c3afea6aaa491d9effbfd91785494a5caff6b8f.
  Pinned main.py unchanged, hash still 257ff71c..., v1.2 still current.
- Windows /file fix: attach_file no longer uses POSIX shlex.split,
  which stripped backslashes and turned a Windows path into a
  not-found path. New split_file_arg splits on whitespace only,
  keeps backslashes intact, and honors a quoted path with spaces.
  The shlex import is removed.
- Windows permission claim corrected, not papered over: SessionStore
  still calls os.chmod 0o600, which is POSIX-only. On Windows that
  call is best-effort and no Windows ACL is set here, because ACL
  code cannot be verified from the Muse VM. The docstring says so
  plainly, and the permission tests assert 0600 on POSIX only.
- Legacy tests made platform-aware: v1.1 file tests now pass
  forward-slash paths on Windows, which Windows accepts and POSIX
  shlex survives, so they test credential and refusal logic rather
  than failing on backslash parsing; backslash parsing is covered
  by the new v1.3 tests. v1.1 and v1.2 permission tests assert the
  mode on POSIX only.
- Verification on this VM: 44 tests passing (36 legacy plus 8 new
  v1.3 tests), ruff check and format check clean, main() callable,
  diff against v1.2 limited to the header, split_file_arg, the
  SessionStore docstring and comment, and the attach_file call.
  Windows verification is Julian's step on the Surface: the same
  suite that failed 3 tests on v1.2 should now pass, with the
  permission tests exercising round-trip only on Windows.
- README and AGENTS are not updated for v1.3 until a pin, so the
  pinned v1.2 docs stay accurate.

## v1.2, 2026-10-27, pinned

- Pinned by Julian. main.py: 1447 lines, 58,363 bytes,
  SHA-256 257ff71c040dc8e6e814c5978eeeaee41ca98f9e4b5e5f97a631ad3c5aaf69ad.
  Identical copy kept as main_v1.2.py. Previous pin superseded: v1.1,
  997 lines, 47,277 bytes, SHA-256 664c1529....
- Built from the v1.2 proposal, then formatted and linted for P9:
  main_v1.2.py was reformatted with ruff 0.8.0 (1447 lines, up from
  1116, behavior unchanged) and unused imports removed from it and
  from the tests. The pre-format proposal hash ee0a4e88... is superseded.
- P9 completed except license: ruff config in pyproject.toml,
  requirements-dev.txt pins ruff 0.8.0, CI runs ruff check, ruff format
  check, the test suite, and a packaging check. pyproject.toml now
  declares requires-python >=3.12,<3.13 (tested only on 3.12.3) and
  the ollama-cli console script, which was deferred until this pin
  because v1.1 had no main() function. README install and
  troubleshooting sections updated; the stale "versions not yet pinned"
  section is corrected.
- Verification: 36 tests passing in a clean virtual environment with
  pinned dependencies, ruff check and ruff format check clean, syntax
  compile OK, and pip install . in a clean virtual environment
  produced the ollama-cli script and main() imported successfully.
  Pinned main.py and main_v1.2.py hashes match; main_v1.1.py unchanged.
- Still open, not assumed: live verification P10 (no Ollama server or binary on the
  Muse VM, checked 2026-10-27, so the pin rests on mocked tests only).
- 2026-10-27, license added, P9 closed: LICENSE added with the Apache
  License, Version 2.0 text, appendix copyright line filled as
  Copyright 2026 Julian Gonzalez, pyproject.toml declares Apache-2.0
  with the Apache classifier, README and AGENTS updated. main.py
  unchanged, pin unaffected, hash still 257ff71c....
- 2026-10-27, artifact saved: goals/ollama-cli/files/ollama-cli-v1-2/
  with ollama-cli-v1-2.py, byte-identical to pinned main.py, and
  meta.json, mirroring the v1.1 artifact. 36 tests passed against the
  artifact copy; main.py unchanged.
- 2026-10-27, Windows test on Julian's Surface Laptop, reported by
  him: 33 of 36 tests passed, 3 failures. Two are the 0600 permission
  tests reporting 0o666, because Python os.chmod on Windows does not
  set POSIX 0600. One is the credential-warning test, which traces to
  POSIX shlex.split mangling Windows backslash paths in attach_file,
  so the file is reported not found and never injected; the same
  shlex code is in pinned v1.2 main.py. Windows is not claimed
  supported, main.py unchanged, P10 still open, no live run reported.

## v1.2, proposal, superseded by the pin above

- 2026-10-27, built from pinned v1.1. main_v1.2.py: 1116 lines,
  SHA-256 ee0a4e88d5247fa26d2c6f8b5c1d7a14dfce3840b68d9698cfd82ca36b24195b.
  Pinned main.py unchanged, hash still 664c1529..., v1.1 still current.
- P6 Telemetry honesty: telemetry_summary extracted as a pure function
  with definitions, zero durations show as n/a, prompt counts per turn.
- P7 Context builder: build_context with fixed order, estimate of 1 token
  per 4 characters stated as an estimate only, oldest messages dropped
  first, last message kept, over-budget turns refused, /context command
  added to inspect the estimate without sending.
- P8 Modular split: SessionStore, OllamaClient, context builder, and
  telemetry helpers are separate from the REPL and testable without a
  terminal or model server. Single-file distribution kept.
- P9 Release readiness, except license: requirements.txt pinned
  (requests 2.34.2, rich 15.0.0, prompt_toolkit 3.0.53, tested on Python
  3.12.3), pyproject.toml added, CI workflow added running the test
  suite on Python 3.12, pip install verified for pinned main.py.
  Console script deferred: main() exists only in v1.2, so adding it now
  would break installs of pinned v1.1. License still unchosen, his
  decision, so P9 is not complete.
- P10 Live verification: LIVE_VERIFICATION.md checklist and
  tests/live_verification.py helper prepared for the GEM12 run. No live
  run has been made, so P10 is not complete.
- Tests: 36 tests total, all passing, 25 v1.1 tests also passing
  against v1.2 code as a regression check, plus 11 new v1.2 tests.

## Unreleased

- 2026-10-27, docs only: compact SVG system diagram added at
  system-diagram.svg, showing the REPL, OllamaRichCLI, SessionStore,
  context builder, OllamaClient, telemetry, local Ollama server, and
  disk state, with v1.2-only pieces marked. main.py unchanged, pin
  unaffected, v1.1 still current. No code changed, so no test run
  applies to this change.
- 2026-10-27, docs only: system-diagram.svg revised to a black
  background with bright arrows (cyan, magenta, yellow, lime, orange,
  violet) and dark boxes with light text. main.py unchanged, pin
  unaffected, v1.1 still current. No code changed, so no test run
  applies to this change.
- 2026-10-27, tests only: REPL dispatch and session-switch tests added,
  closing the P1 gap for command parsing and session switching. Full suite
  is now 25 tests, all passing, up from 19. main.py unchanged, pin
  unaffected, v1.1 still current.
- 2026-10-27, docs only: CHANGELOG.md created with the initial pin and
  v1.1 history, plus the update rule that every change adds an entry here
  before pinning or delivery. AGENTS.md updated with the same rule.
- 2026-10-27, status only: sub-goals P1 to P5 marked complete against
  pinned v1.1 and the 25-test suite. main.py unchanged, pin unaffected.
  P6 to P10 remain open.

## v1.1, 2026-10-27, pinned

- Pinned by Julian. main.py: 997 lines, 47,277 bytes,
  SHA-256 664c1529078783245da51ceebbe383fb109689e7214c0ae7aa0e6cb50a7083cc.
  Identical copy kept as main_v1.1.py, and as the goal artifact
  ollama-cli-v1-1.
- P1 Tests and failure handling: tests/test_main_v1_1.py added, 19 tests,
  stdlib unittest, mocked Ollama API, no live server required.
- P2 File injection safeguards: 256 KB cap, binary refusal, credential
  and private-key warning with confirmation before injection.
- P3 Session recovery: /new refuses an existing name instead of loading
  it, corrupted session files reset to an explicit empty state, session
  writes are atomic with 0600 permissions.
- P4 Failed-turn handling: non-200, network error, empty, malformed, and
  cancelled turns are discarded, not left in history to be resent.
- P5 Parameter validation and single Ollama client: one OllamaClient with
  explicit timeouts (3s model list, 5s connect plus 60s read for chat),
  range-checked parameters, invalid session parameters dropped to defaults.
- P6 Telemetry honesty: session prompt tokens report the last turn's full
  context count instead of an inflated sum, completion tokens are summed,
  unavailable durations and rates show as n/a.
- P7 to P10 remain open. Live verification against a real Ollama server
  is still outstanding, so the v1.1 pin rests on mocked tests only.

## Initial pin, 2026-10-27, superseded

- First pinned build, from the upload ollama_rich_cli_0_mp3g.py.
  main.py: 783 lines, 37,726 bytes,
  SHA-256 4d907a7776045b34b8ac8e96155c4e8ae110a2318cd567c54b84a593adb94583.
- Single-file Rich plus prompt_toolkit CLI with sessions, system prompt
  presets, file injection, runtime parameters, and telemetry.
- No test suite, no parameter ranges, no file size cap, no failed-turn
  handling, and no context budget. Those gaps became P1 to P6.
