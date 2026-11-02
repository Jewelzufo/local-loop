import os
import re
import glob
import json
import tempfile
import requests
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme
from rich.live import Live
from rich.markdown import Markdown
from rich.prompt import Prompt, IntPrompt, FloatPrompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML


DEFAULT_PRESETS = {
    "coder": "You are an expert software engineer. Write clean, idiomatic, well-documented, and performant code. Focus on best practices and provide concise explanations.",
    "concise": "You are a direct, concise assistant. Provide answers without preambles, pleasantries, or filler text.",
    "academic": "You are a rigorous academic researcher. Provide detailed, well-reasoned explanations supported by formal logic, foundational theory, and technical depth.",
    "creative": "You are an imaginative creative writer. Provide expressive, nuanced, and evocative prose with vivid descriptive details.",
    "tutor": "You are a patient Socratic tutor. Guide the user by asking thoughtful questions and breaking complex topics into intuitive steps.",
}

# v1.6: themes. Styles are concrete Rich colours from the palette,
# used directly by the banner, help, and panels, so switching a theme
# recolours those surfaces without touching their text. They are also
# installed as a console theme for named styles, but surfaces do not
# rely on named styles, because Rich parses table header styles
# strictly and a named style would fail on a console without that
# theme. Classic reproduces the pre-theme colours exactly. Cyberpunk
# is neon pink, cyan, and purple on the terminal's own background: no
# background colour is forced, so the scheme works on light and dark
# terminals alike. Prompt colours are separate prompt_toolkit ANSI
# names, because the input prompt is HTML, not Rich markup. Body
# success, warning, and error lines keep their semantic colours and
# are not yet theme-driven; that is a stated limit, not an oversight.
THEMES = {
    "classic": {
        "label": "Classic",
        "styles": {
            "accent": "magenta",
            "primary": "cyan",
            "success": "green",
            "warning": "yellow",
            "error": "red",
            "muted": "dim",
            "banner": "green",
        },
        "prompt": {
            "title": "ansicyan",
            "session": "ansiblue",
            "model": "ansimagenta",
            "sys": "ansigreen",
        },
    },
    "cyberpunk": {
        "label": "Cyberpunk",
        "styles": {
            "accent": "#b967ff",
            "primary": "#05d9e8",
            "success": "#00ff9f",
            "warning": "#f9c80e",
            "error": "#ff2a6d",
            "muted": "#8a8aa3",
            "banner": "#ff2a6d",
        },
        "prompt": {
            "title": "ansibrightcyan",
            "session": "ansibrightmagenta",
            "model": "ansibrightyellow",
            "sys": "ansibrightgreen",
        },
    },
}


def load_theme_name(theme_file):
    """v1.6: read a saved theme name. Unknown, missing, or unreadable
    files fall back to classic, never to an error at startup."""
    try:
        with open(theme_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        name = data.get("theme", "classic") if isinstance(data, dict) else "classic"
        return name if name in THEMES else "classic"
    except Exception:
        return "classic"


# v1.1: validated parameter defaults and ranges. A value outside its range
# is rejected, never sent to Ollama and never saved to a session file.
PARAM_DEFAULTS = {
    "num_ctx": 4096,
    "num_predict": 512,
    "temperature": 0.7,
    "top_p": 0.9,
    "top_k": 40,
    "repeat_penalty": 1.1,
}
PARAM_INT_KEYS = ("num_ctx", "num_predict", "top_k")
PARAM_RANGES = {
    "num_ctx": (256, 131072),
    "num_predict": (1, 32768),
    "temperature": (0.0, 2.0),
    "top_p": (0.0, 1.0),
    "top_k": (1, 100),
    "repeat_penalty": (0.0, 2.0),
}

# v1.1: file injection cap. Files larger than this are refused, not truncated,
# so a partial file is never silently sent as if it were the whole file.
MAX_FILE_BYTES = 256 * 1024

_CREDENTIAL_PATTERNS = [
    re.compile(
        r"(?i)\b(api[_-]?key|secret|password|passwd|private[_-]?key|access[_-]?token|auth[_-]?token)\b\s*[:=]\s*\S+"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
]


def coerce_param(key, raw):
    """Coerce and range-check one parameter. Raises ValueError on any failure."""
    if key not in PARAM_DEFAULTS:
        raise ValueError(f"Unknown parameter '{key}'")
    if isinstance(raw, bool):
        raise ValueError(f"Invalid value for {key}: booleans are not accepted")
    try:
        if key in PARAM_INT_KEYS:
            if isinstance(raw, float):
                if not raw.is_integer():
                    raise ValueError(f"{key} must be an integer")
                value = int(raw)
            else:
                value = int(str(raw).strip())
        else:
            value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid numeric value for {key}: '{raw}'")
    low, high = PARAM_RANGES[key]
    if not (low <= value <= high):
        raise ValueError(f"{key} must be between {low} and {high}, got {value}")
    return value


def validate_params(raw_params):
    """Sanitize a params dict from a session file. Returns (cleaned, warnings)."""
    cleaned = {}
    warnings = []
    if not isinstance(raw_params, dict):
        return cleaned, ["Session params were not a mapping; defaults kept"]
    for key, value in raw_params.items():
        if key not in PARAM_DEFAULTS:
            warnings.append(f"Ignored unknown session parameter '{key}'")
            continue
        try:
            cleaned[key] = coerce_param(key, value)
        except ValueError as e:
            warnings.append(f"Ignored invalid session parameter: {e}; default kept")
    return cleaned, warnings


def parse_think_value(raw):
    """v1.5: parse a think setting. Returns True, False, or None (unset).

    True and False are sent to Ollama as the top-level think field.
    None means no think field is sent and Ollama decides, which is the
    default and the behavior of every earlier version. A bool passes
    through; an unknown value raises ValueError and changes nothing.
    """
    if raw is None or isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("true", "1", "on", "yes", "enabled", "enable"):
        return True
    if text in ("false", "0", "off", "no", "disabled", "disable"):
        return False
    if text in ("unset", "none", "clear", "default"):
        return None
    raise ValueError(f"Invalid think value '{raw}': use on, off, or unset")


def think_label(value):
    """v1.5: display label for a think setting."""
    if value is True:
        return "on"
    if value is False:
        return "off"
    return "unset (model default)"


def looks_like_credential(text):
    return any(pattern.search(text) for pattern in _CREDENTIAL_PATTERNS)


def split_file_arg(arg):
    """Split a /file argument into (path, query).

    v1.3: POSIX shlex.split stripped backslashes, so a Windows path like
    C:\\Users\\panda\\file.txt became C:Userspandafile.txt and was reported
    not found. This parser splits on whitespace only, keeps backslashes
    intact, and honors a quoted path that contains spaces. It does not
    interpret escapes, quotes inside a path, or shell syntax.
    """
    arg = arg.strip()
    if not arg:
        return "", ""
    if arg[0] in ("'", '"'):
        quote = arg[0]
        end = arg.find(quote, 1)
        if end == -1:
            return arg[1:], ""
        return arg[1:end], arg[end + 1 :].strip()
    parts = arg.split(None, 1)
    return parts[0], parts[1].strip() if len(parts) > 1 else ""


# v1.4: dynamic system-prompt variables. A template may contain
# {{name}} placeholders, where name is [A-Za-z_][A-Za-z0-9_]*. Anything
# else in double braces is left untouched, so it is never silently
# treated as a variable. Rendering never invents a value: a variable
# with no supplied value is reported as missing, and the caller decides
# whether to prompt for it.
_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_ASSIGNMENT_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\"([^\"]*)\"|'([^']*)'|(\S+))"
)


def extract_template_variables(template):
    """Return template variables in first-appearance order, deduplicated."""
    seen = []
    for match in _TEMPLATE_VAR_RE.finditer(template or ""):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def render_template(template, values):
    """Render a template with values. Returns (rendered, missing).

    A supplied value replaces every occurrence of its variable, with or
    without surrounding spaces inside the braces. A missing variable is
    left as written and listed in missing, in first-appearance order.
    """
    values = values or {}
    missing = extract_template_variables(template)
    missing = [name for name in missing if name not in values]

    def replace(match):
        name = match.group(1)
        return str(values[name]) if name in values else match.group(0)

    return _TEMPLATE_VAR_RE.sub(replace, template or ""), missing


def parse_variable_assignments(text):
    """Parse key=value pairs from text. Quoted values may contain spaces.

    Later assignments win. Text that is not a key=value pair is ignored,
    so this is only used where the first token is already known, such as
    the preset name in '/system coder role=auditor context=payments'.
    """
    assignments = {}
    for match in _ASSIGNMENT_RE.finditer(text or ""):
        value = match.group(3)
        if value is None:
            value = match.group(4)
        if value is None:
            value = match.group(5)
        assignments[match.group(1)] = value
    return assignments


class OllamaClient:
    """v1.1: the single place that talks to Ollama. Timeouts are explicit here
    and nowhere else: 3s for metadata, 5s connect plus 60s read for chat
    streaming, 5s connect plus 120s read for model pulls."""

    def __init__(
        self, api_url, tags_timeout=3, chat_timeout=(5, 60), pull_timeout=(5, 120)
    ):
        self.api_url = api_url
        self.tags_timeout = tags_timeout
        self.chat_timeout = chat_timeout
        self.pull_timeout = pull_timeout

    def list_models(self):
        res = requests.get(f"{self.api_url}/api/tags", timeout=self.tags_timeout)
        if res.status_code != 200:
            raise requests.exceptions.HTTPError(
                f"Ollama returned {res.status_code} for /api/tags"
            )
        return res.json().get("models", [])

    def model_names(self):
        try:
            return [m["name"] for m in self.list_models()]
        except Exception:
            return []

    def chat_stream(self, model, messages, options, think=None):
        # v1.5: think is a top-level /api/chat field, not a member of
        # options. It is only sent when set, so the default (None)
        # preserves the payload of every earlier version exactly.
        payload = {
            "model": model,
            "messages": messages,
            "options": options,
            "stream": True,
        }
        if think is not None:
            payload["think"] = think
        return requests.post(
            f"{self.api_url}/api/chat",
            json=payload,
            stream=True,
            timeout=self.chat_timeout,
        )

    def pull_stream(self, model_name):
        return requests.post(
            f"{self.api_url}/api/pull",
            json={"name": model_name},
            stream=True,
            timeout=self.pull_timeout,
        )

    def delete_model(self, model_name):
        res = requests.delete(
            f"{self.api_url}/api/delete",
            json={"name": model_name},
            timeout=self.tags_timeout,
        )
        if res.status_code != 200:
            raise requests.exceptions.HTTPError(
                f"Ollama returned {res.status_code} for /api/delete"
            )
        return res


def estimate_tokens(text):
    """v1.2: token estimate, not a count. 1 token is about 4 characters.
    No model tokenizer is used, so this is a budget guard, not an exact
    measure. Empty text is 0, any non-empty text is at least 1."""
    if not text:
        return 0
    return max(1, (len(str(text)) + 3) // 4)


def build_context(system_prompt, messages, num_ctx):
    """v1.2: inspectable context builder. Fixed order: system prompt first,
    then history in order, with the last message always kept. If the estimate
    exceeds num_ctx, oldest messages are dropped first and the drop is
    reported. If even the system prompt plus the last message exceeds
    num_ctx, over_budget is True and the caller must refuse to send."""
    system_msg = {"role": "system", "content": system_prompt} if system_prompt else None
    system_tokens = estimate_tokens(system_prompt) if system_prompt else 0
    kept = list(messages)
    dropped = []

    def total(msgs):
        return system_tokens + sum(estimate_tokens(m.get("content", "")) for m in msgs)

    while kept and total(kept) > num_ctx and len(kept) > 1:
        dropped.append(kept.pop(0))
    estimated = total(kept)
    payload = ([system_msg] if system_msg else []) + kept
    return {
        "payload_messages": payload,
        "estimated_tokens": estimated,
        "num_ctx": num_ctx,
        "dropped_count": len(dropped),
        "dropped_estimated_tokens": sum(
            estimate_tokens(m.get("content", "")) for m in dropped
        ),
        "over_budget": estimated > num_ctx,
        "method": "1 token is about 4 characters, estimate only, no model tokenizer",
    }


def telemetry_summary(m):
    """v1.2: pure telemetry formatting. Definitions: total_duration is the
    whole turn, load_duration is model load, prompt_eval is prompt processing
    with prompt_eval_count tokens, eval is generation with eval_count tokens.
    A zero duration means the value was not reported, so it shows as n/a,
    never as a false 0.0 tok/s. Prompt counts are per turn, not session sums."""
    total_dur_s = m.get("total_duration", 0) / 1e9
    load_dur_ms = m.get("load_duration", 0) / 1e6
    p_eval_cnt = m.get("prompt_eval_count", 0)
    p_eval_dur_s = m.get("prompt_eval_duration", 0) / 1e9
    eval_cnt = m.get("eval_count", 0)
    eval_dur_s = m.get("eval_duration", 0) / 1e9
    return {
        "total_dur_str": f"{total_dur_s:.2f} s" if total_dur_s > 0 else "n/a",
        "load_str": f"{load_dur_ms:.1f} ms" if load_dur_ms > 0 else "n/a",
        "p_dur_str": f"{p_eval_dur_s:.2f} s" if p_eval_dur_s > 0 else "n/a",
        "eval_dur_str": f"{eval_dur_s:.2f} s" if eval_dur_s > 0 else "n/a",
        "p_rate_str": f"{(p_eval_cnt / p_eval_dur_s):.1f} tok/s"
        if p_eval_dur_s > 0
        else "n/a",
        "eval_rate_str": f"{(eval_cnt / eval_dur_s):.1f} tok/s"
        if eval_dur_s > 0
        else "n/a",
        "p_eval_cnt": p_eval_cnt,
        "eval_cnt": eval_cnt,
        "total_tokens": p_eval_cnt + eval_cnt,
        "reason": m.get("done_reason", "completed"),
    }


class SessionStore:
    """v1.2: session file storage, extracted from the REPL. Owns path
    sanitization, atomic writes, and 0600 permissions on POSIX. On Windows
    os.chmod does not enforce POSIX 0600, so the write is best-effort
    there and the real boundary is the user's NTFS profile, not the mode
    bits. It does not validate params or interpret message content; the
    CLI does that on load."""

    def __init__(self, sessions_dir):
        self.sessions_dir = sessions_dir

    def get_path(self, session_name):
        safe_name = "".join(
            c for c in session_name if c.isalnum() or c in ("-", "_")
        ).strip()
        return os.path.join(self.sessions_dir, f"{safe_name or 'default'}.json")

    def exists(self, session_name):
        return os.path.exists(self.get_path(session_name))

    def list_names(self):
        files = glob.glob(os.path.join(self.sessions_dir, "*.json"))
        return sorted([os.path.splitext(os.path.basename(f))[0] for f in files])

    def read(self, session_name):
        with open(self.get_path(session_name), "r", encoding="utf-8") as f:
            return json.load(f)

    def write(self, session_name, payload):
        path = self.get_path(session_name)
        os.makedirs(self.sessions_dir, exist_ok=True)
        tmp_path = None
        fd, tmp_path = tempfile.mkstemp(
            dir=self.sessions_dir, prefix=".tmp-", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            # POSIX 0600. On Windows this is best-effort only; see the
            # SessionStore docstring. No Windows ACL is set here.
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, path)
            tmp_path = None
        finally:
            if tmp_path is not None and os.path.exists(tmp_path):
                os.remove(tmp_path)


class OllamaCompleter(Completer):
    """Dynamic tab-completer for commands, models, files, params, sessions, and system presets."""

    def __init__(self, cli):
        self.cli = cli
        self.path_completer = PathCompleter(expanduser=True)
        self.commands = [
            "/help",
            "/models",
            "/params",
            "/tokens",
            "/verbose",
            "/system",
            "/file",
            "/history",
            "/sessions",
            "/new",
            "/newchat",
            "/fresh",
            "/context",
            "/load",
            "/multiline",
            "/theme",
            "/exit",
        ]
        self.param_keys = [
            "num_ctx",
            "num_predict",
            "temperature",
            "top_p",
            "top_k",
            "repeat_penalty",
            "think",
        ]
        self.system_subcommands = [
            "clear",
            "reset",
            "load",
            "set",
            "presets",
            "vars",
            "refill",
        ]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        stripped = text.lstrip()

        if not stripped.startswith("/"):
            return

        parts = stripped.split(maxsplit=1)
        cmd = parts[0]

        # 1. Complete main slash command
        if len(parts) == 1 and not text.endswith(" "):
            for c in self.commands:
                if c.startswith(cmd):
                    yield Completion(c, start_position=-len(cmd))
            return

        # 2. Complete arguments based on the active command
        arg_text = parts[1] if len(parts) > 1 else ""

        if cmd == "/models":
            for m in self.cli.get_model_names():
                if m.startswith(arg_text):
                    yield Completion(m, start_position=-len(arg_text))

        elif cmd == "/load":
            for s in self.cli.get_saved_session_names():
                if s.startswith(arg_text):
                    yield Completion(s, start_position=-len(arg_text))

        elif cmd == "/system":
            # Suggest subcommands and preset names
            suggestions = self.system_subcommands + list(self.cli.presets.keys())
            for s in suggestions:
                if s.startswith(arg_text):
                    yield Completion(s, start_position=-len(arg_text))

        elif cmd == "/theme":
            for name in THEMES.keys():
                if name.startswith(arg_text):
                    yield Completion(name, start_position=-len(arg_text))

        elif cmd == "/params":
            p_parts = arg_text.split()
            if len(p_parts) == 0 or (len(p_parts) == 1 and not arg_text.endswith(" ")):
                prefix = p_parts[0] if p_parts else ""
                for k in self.param_keys:
                    if k.startswith(prefix):
                        yield Completion(k, start_position=-len(prefix))

        elif cmd == "/file":
            path_part = arg_text.split()[0] if arg_text else ""
            sub_doc = Document(path_part, cursor_position=len(path_part))
            for comp in self.path_completer.get_completions(sub_doc, complete_event):
                yield comp


class OllamaRichCLI:
    def __init__(self):
        self.api_url = "http://localhost:11434"
        self.client = OllamaClient(self.api_url)

        # Directory structure
        self.base_dir = os.path.expanduser("~/.ollama_cli_history")
        self.sessions_dir = os.path.join(self.base_dir, "sessions")
        self.prompts_file = os.path.join(self.base_dir, "system_prompts.json")
        self.theme_file = os.path.join(self.base_dir, "theme.json")
        os.makedirs(self.sessions_dir, exist_ok=True)
        self.store = SessionStore(self.sessions_dir)

        # v1.6: theme is a global UI preference, not session content,
        # so it is read before the console is created and is not reset
        # by session switches or by _reset_session_state.
        self.theme_name = load_theme_name(self.theme_file)
        self.theme = THEMES[self.theme_name]
        self.console = Console(theme=Theme(self.theme["styles"]))

        self.current_session = "default"
        self.current_model = None
        self.messages = []
        self.system_prompt = None
        self.system_prompt_template = None
        self.system_prompt_values = {}
        self.ephemeral = False
        self.multiline_mode = False
        self.verbose_metrics = True
        self.last_metrics = {}
        self.last_context_report = {}

        # Load presets library
        self.presets = self.load_presets()

        # Model hyperparameters
        self.params = dict(PARAM_DEFAULTS)
        # v1.5: think is separate from params because Ollama takes it
        # top-level, not inside options. None is unset, the default.
        self.think = None

        # Token counters. v1.1 honesty rule: session_prompt_tokens is the
        # LAST turn's full-context prompt count, not a sum. Ollama reports
        # the whole context on every turn, so summing it inflates the total.
        # Completion tokens are genuinely additive and are summed.
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0

        # Load session state & connect model
        self.load_session(self.current_session)
        if not self.current_model:
            self.auto_select_model()

        # Initialize prompt_toolkit session
        input_history_path = os.path.join(self.base_dir, "input_history.txt")
        self.pt_session = PromptSession(
            history=FileHistory(input_history_path),
            auto_suggest=AutoSuggestFromHistory(),
            completer=OllamaCompleter(self),
            complete_while_typing=True,
        )

    # ----------------- PRESETS MANAGEMENT ----------------- #

    def load_presets(self):
        presets = dict(DEFAULT_PRESETS)
        if os.path.exists(self.prompts_file):
            try:
                with open(self.prompts_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    if isinstance(saved, dict):
                        presets.update(saved)
            except Exception:
                pass
        return presets

    def save_presets(self):
        try:
            with open(self.prompts_file, "w", encoding="utf-8") as f:
                json.dump(self.presets, f, indent=2)
        except Exception as e:
            self.console.print(f"[bold red]Failed to save presets:[/bold red] {e}")

    # ----------------- THEME MANAGEMENT ----------------- #

    def set_theme(self, name):
        """v1.6: switch theme and persist it as a global preference.

        The theme file is separate from session files, so switching
        sessions does not switch themes, and ephemeral mode does not
        block it, the same way saving a preset is not session state.
        Returns False for an unknown theme, changing nothing.
        """
        name = (name or "").strip().lower()
        if name not in THEMES:
            self.console.print(
                f"[bold red]Unknown theme '{name}'. Available: {list(THEMES.keys())}[/bold red]"
            )
            return False
        self.theme_name = name
        self.theme = THEMES[name]
        try:
            self.console.theme = Theme(self.theme["styles"])
        except Exception:
            pass
        theme_file = getattr(self, "theme_file", None)
        if theme_file:
            try:
                with open(theme_file, "w", encoding="utf-8") as f:
                    json.dump({"theme": name}, f, indent=2)
            except Exception as e:
                self.console.print(f"[bold red]Failed to save theme:[/bold red] {e}")
                return False
        self.console.print(
            f"[bold success]Theme set to {THEMES[name]['label']}.[/bold success]"
        )
        return True

    def manage_theme(self, arg=None):
        """v1.6: /theme with no argument shows the current theme and
        the available themes; /theme <name> switches to it."""
        if not arg:
            self.console.print(
                f"Current theme: {getattr(self, 'theme_name', 'classic')} "
                f"({THEMES.get(getattr(self, 'theme_name', 'classic'), {}).get('label', '')}). "
                f"Available: {', '.join(THEMES.keys())}. "
                "Use /theme cyberpunk or /theme classic to switch."
            )
            return
        self.set_theme(arg)

    # ----------------- SESSION PERSISTENCE ----------------- #

    def _get_store(self):
        if not hasattr(self, "store") or self.store is None:
            self.store = SessionStore(self.sessions_dir)
        return self.store

    def _get_session_path(self, session_name: str) -> str:
        return self._get_store().get_path(session_name)

    def get_saved_session_names(self):
        return self._get_store().list_names()

    def _reset_session_state(self, session_name: str):
        self.current_session = session_name
        self.messages = []
        self.system_prompt = None
        self.system_prompt_template = None
        self.system_prompt_values = {}
        self.think = None
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.last_metrics = {}
        self.last_context_report = {}

    def load_session(self, session_name: str):
        # Loading a tracked session always ends ephemeral mode.
        self.ephemeral = False
        if not self._get_store().exists(session_name):
            self._reset_session_state(session_name)
            return False
        try:
            data = self._get_store().read(session_name)
            if not isinstance(data, dict):
                raise ValueError("session file is not a JSON object")
            messages = data.get("messages", [])
            if not isinstance(messages, list) or not all(
                isinstance(m, dict) for m in messages
            ):
                raise ValueError("session messages are not a list of message objects")
            cleaned_params, warnings = validate_params(data.get("params", {}))
            for warning in warnings:
                self.console.print(f"[bold yellow]Warning:[/bold yellow] {warning}")
            self.messages = messages
            self.params = {**dict(PARAM_DEFAULTS), **cleaned_params}
            # v1.5: only a real bool is a think setting. Anything else
            # in an old or edited session file falls back to unset.
            raw_think = data.get("think", None)
            if isinstance(raw_think, bool):
                self.think = raw_think
            else:
                if "think" in data and raw_think is not None:
                    self.console.print(
                        "[bold yellow]Warning:[/bold yellow] Ignored invalid "
                        "session think value; unset kept"
                    )
                self.think = None
            model = data.get("current_model", self.current_model)
            self.current_model = model if isinstance(model, str) else self.current_model
            prompt = data.get("system_prompt", None)
            self.system_prompt = prompt if isinstance(prompt, str) else None
            # v1.4: a templated prompt is stored as template plus values,
            # so it can be refilled later. Old sessions have neither field
            # and keep the plain rendered prompt above.
            template = data.get("system_prompt_template", None)
            self.system_prompt_template = (
                template if isinstance(template, str) else None
            )
            raw_values = data.get("system_prompt_values", {})
            values = (
                {k: v for k, v in raw_values.items() if isinstance(v, str)}
                if isinstance(raw_values, dict)
                else {}
            )
            self.system_prompt_values = values
            if self.system_prompt_template:
                rendered, missing = render_template(self.system_prompt_template, values)
                if not missing:
                    self.system_prompt = rendered
            self.session_prompt_tokens = data.get("session_prompt_tokens", 0)
            if not isinstance(self.session_prompt_tokens, int):
                self.session_prompt_tokens = 0
            self.session_completion_tokens = data.get("session_completion_tokens", 0)
            if not isinstance(self.session_completion_tokens, int):
                self.session_completion_tokens = 0
            self.current_session = session_name
            return True
        except Exception as e:
            self.console.print(
                f"[bold red]Failed to load session '{session_name}':[/bold red] {e}"
            )
            self._reset_session_state(session_name)
            return False

    def create_new_session(self, session_name: str):
        """v1.1: /new must start empty. If a file already exists, refuse
        instead of silently loading it and calling it clean."""
        if self._get_store().exists(session_name):
            self.console.print(
                f"[bold red]Session '{session_name}' already exists. Use /load to open it, or choose a new name.[/bold red]"
            )
            return False
        self.ephemeral = False
        self._reset_session_state(session_name)
        self.save_history()
        return True

    def start_ephemeral_chat(self):
        """v1.4: start a fresh chat with the same model, in memory only.

        Messages, counters, and last-turn reports are cleared. Model,
        parameters, and the active system prompt are kept. Nothing is
        written to a session file while ephemeral is set, and the
        previous session file is left untouched, because save_history
        becomes a no-op. /load and /new end ephemeral mode; exiting
        loses the ephemeral chat, which is the point of it.
        """
        self.messages = []
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.last_metrics = {}
        self.last_context_report = {}
        self.ephemeral = True
        self.current_session = "ephemeral"
        return True

    def save_history(self):
        # v1.4: ephemeral chats are never persisted, not even by the
        # callers that save after a model, parameter, or prompt change.
        # Saving a preset to the preset library is separate and still
        # works, because save_presets does not go through here.
        if getattr(self, "ephemeral", False):
            return
        payload = {
            "session_name": self.current_session,
            "updated_at": datetime.now().isoformat(),
            "messages": self.messages,
            "system_prompt": self.system_prompt,
            "system_prompt_template": getattr(self, "system_prompt_template", None),
            "system_prompt_values": getattr(self, "system_prompt_values", {}),
            "params": self.params,
            "think": getattr(self, "think", None),
            "current_model": self.current_model,
            "session_prompt_tokens": self.session_prompt_tokens,
            "session_completion_tokens": self.session_completion_tokens,
        }
        try:
            self._get_store().write(self.current_session, payload)
        except Exception as e:
            self.console.print(f"[bold red]Failed to persist session:[/bold red] {e}")

    # ----------------- OLLAMA API HELPERS ----------------- #

    def get_model_names(self):
        return self.client.model_names()

    def auto_select_model(self):
        models = self.get_model_names()
        if models:
            self.current_model = models[0]

    # ----------------- SYSTEM PROMPT MANAGER ----------------- #

    def apply_system_template(self, template, assignments=None):
        """v1.4: render a template, prompting only for missing variables.

        Assignments supplied inline fill their variables without a
        prompt. Every other variable is asked for once, in template
        order, with an empty answer rendering as an empty string. A
        template with no variables is stored as a plain prompt, with
        no template or values kept. Returns True on success.
        """
        values = dict(assignments or {})
        for name in extract_template_variables(template):
            if name not in values:
                values[name] = Prompt.ask(f"Value for {{{{{name}}}}}", default="")
        rendered, missing = render_template(template, values)
        if missing:
            self.console.print(
                f"[bold red]Could not render system prompt, missing: {missing}[/bold red]"
            )
            return False
        self.system_prompt = rendered
        if extract_template_variables(template):
            self.system_prompt_template = template
            self.system_prompt_values = values
        else:
            self.system_prompt_template = None
            self.system_prompt_values = {}
        self.save_history()
        return True

    def show_template_variables(self):
        """v1.4: show the active template, its variables, and values."""
        template = getattr(self, "system_prompt_template", None)
        if not template:
            self.console.print(
                "[dim]No templated system prompt is active. "
                "Use /system with a preset or text containing {{variable}} "
                "to start one.[/dim]"
            )
            return
        values = getattr(self, "system_prompt_values", {})
        lines = [f"Template: {template}"]
        for name in extract_template_variables(template):
            lines.append(f"  {{{{{name}}}}}: {values.get(name, '')}")
        lines.append(f"Rendered: {self.system_prompt}")
        self.console.print("\n".join(lines))

    def refill_template_variables(self):
        """v1.4: re-ask every variable of the active template, keeping
        the previous value as the default for each one."""
        template = getattr(self, "system_prompt_template", None)
        if not template:
            self.console.print(
                "[bold red]No templated system prompt to refill.[/bold red]"
            )
            return False
        values = dict(getattr(self, "system_prompt_values", {}))
        for name in extract_template_variables(template):
            values[name] = Prompt.ask(
                f"Value for {{{{{name}}}}}", default=values.get(name, "")
            )
        rendered, missing = render_template(template, values)
        if missing:
            self.console.print(
                f"[bold red]Could not render system prompt, missing: {missing}[/bold red]"
            )
            return False
        self.system_prompt = rendered
        self.system_prompt_values = values
        self.save_history()
        self.console.print(
            f"[bold green]Refilled system prompt:[/bold green]\n[dim]{rendered}[/dim]"
        )
        return True

    def manage_system_prompt(self, arg=None):
        """Interactive and inline management of model system prompts."""
        # 1. Inline handling
        if arg:
            clean_arg = arg.strip()
            lower_arg = clean_arg.lower()

            if lower_arg in ("clear", "reset", "none"):
                self.system_prompt = None
                self.system_prompt_template = None
                self.system_prompt_values = {}
                self.save_history()
                self.console.print(
                    "[bold green]System prompt cleared. Model will use its default persona.[/bold green]"
                )
                return

            if lower_arg in ("vars", "variables"):
                self.show_template_variables()
                return

            if lower_arg == "refill":
                self.refill_template_variables()
                return

            if lower_arg.startswith("load "):
                # /system load coder [key=value ...]
                rest = clean_arg[5:].strip()
                preset_name = rest.split(None, 1)[0].lower() if rest else ""
                assignments = parse_variable_assignments(rest)
                if preset_name in self.presets:
                    if self.apply_system_template(
                        self.presets[preset_name], assignments
                    ):
                        self.console.print(
                            f"[bold green]Applied preset '{preset_name}':[/bold green]\n[dim]{self.system_prompt}[/dim]"
                        )
                else:
                    self.console.print(
                        f"[bold red]Preset '{preset_name}' not found. Available: {list(self.presets.keys())}[/bold red]"
                    )
                return

            if lower_arg.startswith("set "):
                template = clean_arg[4:].strip().strip("'\"")
                if self.apply_system_template(template):
                    self.console.print(
                        f"[bold green]Updated active system prompt:[/bold green]\n[dim]{self.system_prompt}[/dim]"
                    )
                return

            # Direct preset name lookup, with optional assignments
            # (e.g., /system coder role=auditor context=payments).
            # Only the preset name plus assignments triggers this; other
            # text starting with a preset word stays literal text.
            first_token = lower_arg.split(None, 1)[0] if lower_arg else ""
            preset_rest = clean_arg[len(first_token) :].strip()
            preset_rest_is_assignments = not _ASSIGNMENT_RE.sub("", preset_rest).strip()
            if first_token in self.presets and preset_rest_is_assignments:
                assignments = parse_variable_assignments(clean_arg)
                if self.apply_system_template(self.presets[first_token], assignments):
                    self.console.print(
                        f"[bold green]Applied preset '{first_token}':[/bold green]\n[dim]{self.system_prompt}[/dim]"
                    )
                return

            # Direct arbitrary text input (e.g., /system "You are a math genius").
            # Text containing {{variables}} is rendered the same way,
            # prompting for any value not already known.
            template = clean_arg.strip("'\"")
            if self.apply_system_template(template):
                self.console.print(
                    f"[bold green]Updated active system prompt:[/bold green]\n[dim]{self.system_prompt}[/dim]"
                )
            return

        # 2. Interactive Menu
        while True:
            self.console.print()
            active_display = (
                f"[bold green]{self.system_prompt}[/bold green]"
                if self.system_prompt
                else "[dim]None (Model Default)[/dim]"
            )
            theme_styles = getattr(self, "theme", THEMES["classic"])["styles"]
            self.console.print(
                Panel(
                    active_display,
                    title=f"[bold {theme_styles['primary']}]Active System Prompt[/bold {theme_styles['primary']}]",
                    expand=False,
                )
            )

            table = Table(
                title="System Prompt Menu",
                show_header=True,
                header_style="bold magenta",
                box=box.ROUNDED,
            )
            table.add_column("Option", style="cyan", width=8)
            table.add_column("Action", style="green")
            table.add_column("Description", style="dim")

            table.add_row(
                "1", "Select Preset", "Choose from pre-configured or saved personas"
            )
            table.add_row("2", "Custom Prompt", "Enter a custom system instruction")
            table.add_row(
                "3", "Save As Preset", "Save active system prompt to persistent library"
            )
            table.add_row(
                "4", "Clear Prompt", "Remove custom system prompt (reset to default)"
            )
            table.add_row("b", "Back", "Return to chat")
            self.console.print(table)

            choice = Prompt.ask(
                "Choose an option", choices=["1", "2", "3", "4", "b"], default="b"
            )

            if choice == "1":
                preset_table = Table(
                    title="Available System Prompt Presets",
                    show_header=True,
                    header_style="bold blue",
                    box=box.SIMPLE,
                )
                preset_table.add_column("Key", style="cyan", width=12)
                preset_table.add_column("Prompt Template", style="dim")
                for k, v in self.presets.items():
                    preview = (v[:75] + "...") if len(v) > 75 else v
                    preset_table.add_row(k, preview)
                self.console.print(preset_table)

                p_choice = (
                    Prompt.ask(
                        "Enter preset key to apply (or [b] to cancel)", default="b"
                    )
                    .strip()
                    .lower()
                )
                if p_choice in self.presets:
                    if self.apply_system_template(self.presets[p_choice]):
                        self.console.print(
                            f"[bold green]Applied preset '{p_choice}'.[/bold green]"
                        )
                elif p_choice != "b":
                    self.console.print("[bold red]Unknown preset key.[/bold red]")

            elif choice == "2":
                self.console.print(
                    "[dim]Enter custom system prompt (press Enter to apply):[/dim]"
                )
                new_prompt = self.pt_session.prompt("system > ").strip()
                if new_prompt:
                    if self.apply_system_template(new_prompt):
                        self.console.print(
                            "[bold green]Custom system prompt applied.[/bold green]"
                        )

            elif choice == "3":
                if not self.system_prompt:
                    self.console.print(
                        "[bold yellow]No active system prompt to save.[/bold yellow]"
                    )
                    continue
                name = (
                    Prompt.ask(
                        "Enter a short identifier key for this preset (e.g., 'security-auditor')"
                    )
                    .strip()
                    .lower()
                )
                if name:
                    # Save the template, not the rendered prompt, so a
                    # templated prompt stays reusable with new values.
                    self.presets[name] = (
                        getattr(self, "system_prompt_template", None)
                        or self.system_prompt
                    )
                    self.save_presets()
                    self.console.print(
                        f"[bold green]Saved preset '{name}' to library.[/bold green]"
                    )

            elif choice == "4":
                self.system_prompt = None
                self.system_prompt_template = None
                self.system_prompt_values = {}
                self.save_history()
                self.console.print(
                    "[bold green]System prompt reset to model default.[/bold green]"
                )

            elif choice == "b":
                break

    # ----------------- METRICS DISPLAY ----------------- #

    def render_metrics_panel(self, m: dict):
        if not m:
            return
        s = telemetry_summary(m)
        theme_styles = getattr(self, "theme", THEMES["classic"])["styles"]
        table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style=f"bold {theme_styles['primary']}",
            pad_edge=False,
        )
        table.add_column("Pipeline Stage", style="dim")
        table.add_column("Token Count", justify="right")
        table.add_column("Duration", justify="right")
        table.add_column("Processing Speed", justify="right", style="green")

        table.add_row("Model Load", "-", s["load_str"], "-")
        table.add_row(
            "Prompt Eval", f"{s['p_eval_cnt']} tok", s["p_dur_str"], s["p_rate_str"]
        )
        table.add_row(
            "Generation", f"{s['eval_cnt']} tok", s["eval_dur_str"], s["eval_rate_str"]
        )
        table.add_row(
            "Total Turn",
            f"{s['total_tokens']} tok",
            s["total_dur_str"],
            f"[magenta]{s['reason']}[/magenta]",
        )

        panel = Panel(
            table,
            title=f"[bold {theme_styles['warning']}]Ollama Inference Telemetry[/bold {theme_styles['warning']}]",
            subtitle=f"[dim]Context window: {self.params.get('num_ctx')} tokens | Model: {self.current_model}[/dim]",
            border_style="dim",
            expand=False,
        )
        self.console.print(panel)

    # ----------------- COMMAND HANDLERS ----------------- #

    def print_help(self):
        # Header style uses a concrete colour from the palette, not a
        # named theme style: Rich parses table header styles strictly,
        # and a named style would fail on a console without that theme.
        theme_styles = getattr(self, "theme", THEMES["classic"])["styles"]
        table = Table(
            title="Available Commands",
            show_header=True,
            header_style=f"bold {theme_styles['accent']}",
        )
        table.add_column("Command / Shortcut", style="cyan")
        table.add_column("Inline Example", style="yellow")
        table.add_column("Description", style="green")

        table.add_row("/help", "", "Show this commands reference")
        table.add_row(
            "/system",
            "/system coder role=auditor",
            "Manage or apply system prompt personas; presets and text "
            "may contain {{variable}} placeholders, filled at runtime",
        )
        table.add_row(
            "/system vars",
            "",
            "Show the active prompt template, its variables, and values",
        )
        table.add_row(
            "/system refill",
            "",
            "Re-ask every variable of the active prompt template",
        )
        table.add_row(
            "/models", "/models llama3", "List/select models or switch inline"
        )
        table.add_row(
            "/params",
            "/params num_ctx 8192",
            "Set hyperparams (num_ctx, num_predict, temp...)",
        )
        table.add_row(
            "/params think",
            "/params think off",
            "Thinking mode: on, off, or unset (model default); off sends "
            "Ollama think:false",
        )
        table.add_row(
            "/theme",
            "/theme cyberpunk",
            "Switch colour theme: classic or cyberpunk (neon pink, cyan, purple)",
        )
        table.add_row(
            "/verbose", "", "Toggle verbose token generation telemetry after turns"
        )
        table.add_row(
            "/file",
            "/file ./main.py [query]",
            "Inject file content directly into context",
        )
        table.add_row("/sessions", "", "List all saved conversation sessions")
        table.add_row(
            "/new", "/new code-review", "Create and switch to a fresh conversation"
        )
        table.add_row(
            "/newchat",
            "",
            "Start a fresh chat with the same model, in memory only: "
            "no session file is written until you /load or /new again",
        )
        table.add_row(
            "/load", "/load default", "Switch to an existing conversation session"
        )
        table.add_row(
            "/multiline", "", "Toggle multiline prompt mode (Esc+Enter to send)"
        )
        table.add_row("/tokens", "", "View current session input/output token usage")
        table.add_row(
            "/context",
            "",
            "Inspect current context estimate against num_ctx, without sending",
        )
        table.add_row(
            "/history", "", "Display turns or wipe current conversation memory"
        )
        table.add_row("/exit", "", "Gracefully exit the terminal")
        self.console.print(table)

    def manage_models(self, arg=None):
        available = self.get_model_names()
        if arg:
            target = arg.strip()
            matched = [m for m in available if target.lower() in m.lower()]
            if matched:
                self.current_model = matched[0]
                self.console.print(
                    f"[bold green]Switched active model to: {self.current_model}[/bold green]"
                )
                self.save_history()
            else:
                self.console.print(
                    f"[bold red]Model '{target}' not found locally. Use /models to inspect or pull.[/bold red]"
                )
            return

        try:
            models = self.client.list_models()
        except Exception as e:
            self.console.print(
                f"[bold red]Error connecting to Ollama API:[/bold red] {e}"
            )
            return

        table = Table(show_header=True, header_style="bold blue")
        table.add_column("Index", style="dim", width=6)
        table.add_column("Name", style="green")
        table.add_column("Size (GB)", style="magenta")
        table.add_column("Format", style="yellow")

        for idx, m in enumerate(models):
            gb_size = round(m.get("size", 0) / (1024**3), 2)
            fmt = m.get("details", {}).get("format", "N/A")
            table.add_row(str(idx + 1), m["name"], f"{gb_size} GB", fmt)

        self.console.print(table)
        self.console.print(
            f"\nOptions: [1-{len(models)}] Select | [p] Pull New | [d] Delete | [b] Back"
        )
        choice = Prompt.ask("Choose an action", default="b")

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                self.current_model = models[idx]["name"]
                self.console.print(
                    f"[bold green]Switched active model to: {self.current_model}[/bold green]"
                )
                self.save_history()
        elif choice.lower() == "p":
            repo_name = Prompt.ask("Enter model name to pull (e.g. llama3:8b)")
            if repo_name:
                self.pull_model(repo_name.strip())
        elif choice.lower() == "d":
            del_choice = Prompt.ask("Enter the index of the model to delete")
            if del_choice.isdigit():
                d_idx = int(del_choice) - 1
                if 0 <= d_idx < len(models):
                    m_name = models[d_idx]["name"]
                    if Confirm.ask(f"Are you sure you want to delete {m_name}?"):
                        try:
                            self.client.delete_model(m_name)
                            self.console.print(
                                f"[bold green]Deleted {m_name}[/bold green]"
                            )
                            if self.current_model == m_name:
                                self.current_model = None
                            self.save_history()
                        except Exception as e:
                            self.console.print(
                                f"[bold red]Failed to delete model:[/bold red] {e}"
                            )

    def pull_model(self, model_name):
        try:
            res = self.client.pull_stream(model_name)
            if res.status_code != 200:
                self.console.print(
                    f"[bold red]Error pulling model: Ollama returned {res.status_code}[/bold red]"
                )
                return
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console,
            ) as progress:
                task = progress.add_task(
                    description=f"Pulling {model_name}...", total=None
                )
                for line in res.iter_lines():
                    if line:
                        try:
                            status = json.loads(line).get("status", "")
                        except json.JSONDecodeError:
                            status = ""
                        progress.update(task, description=f"{model_name}: {status}")
            self.console.print(
                f"[bold green]Successfully pulled model {model_name}[/bold green]"
            )
        except Exception as e:
            self.console.print(f"[bold red]Error pulling model:[/bold red] {e}")

    def manage_params(self, arg=None):
        if arg:
            parts = arg.split(maxsplit=1)
            if len(parts) == 2:
                key, raw_val = parts[0].lower(), parts[1]
                if key == "think":
                    try:
                        self.think = parse_think_value(raw_val)
                    except ValueError as e:
                        self.console.print(f"[bold red]{e}[/bold red]")
                        return
                    self.console.print(
                        f"[bold green]Updated think to {think_label(self.think)}[/bold green]"
                    )
                    self.save_history()
                    return
                try:
                    self.params[key] = coerce_param(key, raw_val)
                except ValueError as e:
                    self.console.print(f"[bold red]{e}[/bold red]")
                    return
                self.console.print(
                    f"[bold green]Updated {key} to {self.params[key]}[/bold green]"
                )
                self.save_history()
                return
            self.console.print(
                f"[bold red]Usage: /params <key> <value>. Choose from: {list(self.params.keys()) + ['think']}[/bold red]"
            )
            return

        table = Table(
            title="Model Generation Hyperparameters",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Option", style="cyan", width=6)
        table.add_column("Parameter", style="cyan")
        table.add_column("Value", style="green")
        table.add_column("Description", style="dim")

        table.add_row(
            "1",
            "num_ctx",
            str(self.params["num_ctx"]),
            "Context window buffer size (tokens)",
        )
        table.add_row(
            "2",
            "num_predict",
            str(self.params["num_predict"]),
            "Max generation output tokens",
        )
        table.add_row(
            "3",
            "temperature",
            str(self.params["temperature"]),
            "Creativity/randomness (0.0 - 2.0)",
        )
        table.add_row(
            "4", "top_p", str(self.params["top_p"]), "Nucleus sampling probability"
        )
        table.add_row(
            "5", "top_k", str(self.params["top_k"]), "Top-k sampling threshold"
        )
        table.add_row(
            "6",
            "repeat_penalty",
            str(self.params["repeat_penalty"]),
            "Repetition penalty factor",
        )
        table.add_row(
            "7",
            "think",
            think_label(getattr(self, "think", None)),
            "Thinking mode for reasoning models (on, off, or unset)",
        )
        self.console.print(table)

        choice = Prompt.ask("Select option to modify or [b] back", default="b")
        key_map = {
            "1": "num_ctx",
            "2": "num_predict",
            "3": "temperature",
            "4": "top_p",
            "5": "top_k",
            "6": "repeat_penalty",
            "7": "think",
        }
        if choice == "b":
            return
        if choice not in key_map:
            self.console.print(
                f"[bold red]Unknown option '{choice}'. Nothing changed.[/bold red]"
            )
            return
        key = key_map[choice]
        if key == "think":
            current = getattr(self, "think", None)
            default = (
                "on" if current is True else "off" if current is False else "unset"
            )
            try:
                new_value = parse_think_value(
                    Prompt.ask("Enter think (on, off, or unset)", default=default)
                )
            except ValueError as e:
                self.console.print(f"[bold red]{e}. Nothing changed.[/bold red]")
                return
            if new_value == current:
                self.console.print("[dim]No change. Nothing saved.[/dim]")
                return
            self.think = new_value
            self.save_history()
            self.console.print("[bold green]Parameters updated and saved.[/bold green]")
            return
        prompt_cls = IntPrompt if key in PARAM_INT_KEYS else FloatPrompt
        raw = prompt_cls.ask(f"Enter {key}", default=self.params[key])
        try:
            new_value = coerce_param(key, raw)
        except ValueError as e:
            self.console.print(f"[bold red]{e}. Nothing changed.[/bold red]")
            return
        if new_value == self.params[key]:
            self.console.print("[dim]No change. Nothing saved.[/dim]")
            return
        self.params[key] = new_value
        self.save_history()
        self.console.print("[bold green]Parameters updated and saved.[/bold green]")

    def attach_file(self, arg=None):
        file_path = ""
        prompt_query = ""

        if arg:
            file_path, prompt_query = split_file_arg(arg)
        else:
            file_path = Prompt.ask("Enter local file path")

        clean_path = os.path.expanduser(file_path.strip().strip("'\""))
        if not os.path.isfile(clean_path):
            self.console.print(f"[bold red]File not found: {clean_path}[/bold red]")
            return

        try:
            size = os.path.getsize(clean_path)
            if size > MAX_FILE_BYTES:
                self.console.print(
                    f"[bold red]Refused: {os.path.basename(clean_path)} is {size} bytes, "
                    f"over the {MAX_FILE_BYTES} byte cap. Split it or paste a smaller part.[/bold red]"
                )
                return
            with open(clean_path, "rb") as f:
                raw = f.read()
            if b"\x00" in raw[:8192]:
                self.console.print(
                    f"[bold red]Refused: {os.path.basename(clean_path)} looks like a binary file.[/bold red]"
                )
                return
            content = raw.decode("utf-8", errors="replace")
            if looks_like_credential(content):
                self.console.print(
                    f"[bold yellow]Warning: {os.path.basename(clean_path)} looks like it may contain "
                    "credentials or a private key. Injected content is also saved in the session file.[/bold yellow]"
                )
                if not Confirm.ask("Inject this file anyway?"):
                    self.console.print("[dim]File not injected.[/dim]")
                    return

            context_msg = (
                f"File Context (`{os.path.basename(clean_path)}`):\n```\n{content}\n```"
            )
            if prompt_query:
                context_msg += f"\n\nUser Query: {prompt_query}"

            self.console.print(
                f"[bold green]Read {os.path.basename(clean_path)} ({len(content)} chars).[/bold green]"
            )
            self.handle_chat(context_msg)
        except Exception as e:
            self.console.print(f"[bold red]Failed to read file context:[/bold red] {e}")

    def list_sessions(self):
        sessions = self.get_saved_session_names()
        table = Table(
            title="Saved Conversation Sessions",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Active", justify="center", width=8)
        table.add_column("Session Name", style="green")
        table.add_column("Messages", justify="right")
        table.add_column("Last Updated", style="dim")

        for s in sessions:
            path = self._get_session_path(s)
            msg_count = "?"
            updated_at = "Unknown"
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    msg_count = str(len(data.get("messages", [])))
                    updated_at = data.get("updated_at", "Unknown")[:19].replace(
                        "T", " "
                    )
            except Exception:
                pass
            active_marker = (
                "[bold cyan]=>[/bold cyan]" if s == self.current_session else ""
            )
            table.add_row(active_marker, s, msg_count, updated_at)

        self.console.print(table)
        self.console.print(
            "[dim]Use '/load <name>' to switch or '/new <name>' to create a new session.[/dim]"
        )

    def view_tokens(self):
        table = Table(
            title="Session Token Performance Tracker",
            show_header=True,
            header_style="bold yellow",
        )
        table.add_column("Metric Type", style="cyan")
        table.add_column("Count / Value", style="green")
        table.add_row(
            "Context Window (num_ctx)", f"{self.params.get('num_ctx')} tokens"
        )
        table.add_row(
            "Active System Prompt",
            "Engaged" if self.system_prompt else "None (Default)",
        )
        table.add_row(
            "Session Mode",
            "Ephemeral (not saved)"
            if getattr(self, "ephemeral", False)
            else "Tracked (saved to session file)",
        )
        table.add_row(
            "Thinking Mode",
            think_label(getattr(self, "think", None)),
        )
        table.add_row(
            "Theme",
            getattr(self, "theme_name", "classic"),
        )
        table.add_row(
            "Last Turn Prompt Tokens (full context, not summed)",
            str(self.session_prompt_tokens),
        )
        table.add_row(
            "Session Completion Tokens (total generated)",
            str(self.session_completion_tokens),
        )
        if getattr(self, "last_context_report", {}):
            report = self.last_context_report
            table.add_row(
                "Last Turn Estimated Context Tokens",
                f"{report.get('estimated_tokens')} (estimate)",
            )
            table.add_row(
                "Last Turn Dropped Messages", str(report.get("dropped_count", 0))
            )
        self.console.print(table)

        if self.last_metrics:
            self.render_metrics_panel(self.last_metrics)

    def view_context(self):
        """v1.2: inspect the current context without sending it."""
        report = build_context(
            self.system_prompt, self.messages, self.params.get("num_ctx", 4096)
        )
        table = Table(
            title="Current Context Estimate",
            show_header=True,
            header_style="bold yellow",
        )
        table.add_column("Item", style="cyan")
        table.add_column("Value", style="green")
        table.add_row(
            "Order", "System prompt, then history in order, last message kept"
        )
        table.add_row("Estimated tokens", f"{report['estimated_tokens']} (estimate)")
        table.add_row("Context window (num_ctx)", str(report["num_ctx"]))
        table.add_row("Headroom", str(report["num_ctx"] - report["estimated_tokens"]))
        table.add_row("Would drop on send", str(report["dropped_count"]))
        table.add_row(
            "Over budget",
            "Yes, send would be refused" if report["over_budget"] else "No",
        )
        table.add_row("Method", report["method"])
        self.console.print(table)

    def manage_history(self):
        self.console.print(
            f"Total conversational turns in active cache: [bold cyan]{len(self.messages)}[/bold cyan]"
        )
        if self.messages:
            if Confirm.ask("Would you like to clear this active conversation buffer?"):
                self.messages = []
                self.session_prompt_tokens = 0
                self.session_completion_tokens = 0
                self.last_metrics = {}
                self.save_history()
                self.console.print(
                    "[bold green]Session memory buffers cleared. (System prompt preserved)[/bold green]"
                )

    # ----------------- CHAT & STREAMING ----------------- #

    def handle_chat(self, user_input: str):
        if not self.current_model:
            self.console.print(
                "[bold red]No model currently active. Set one with /models first.[/bold red]"
            )
            return

        self.messages.append({"role": "user", "content": user_input})

        # v1.2: build context through the builder, in fixed order, with a
        # num_ctx budget. Dropped messages are reported, not hidden.
        context_report = build_context(
            self.system_prompt, self.messages, self.params.get("num_ctx", 4096)
        )
        self.last_context_report = {
            k: v for k, v in context_report.items() if k != "payload_messages"
        }
        payload_messages = context_report["payload_messages"]
        if context_report["over_budget"]:
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()
            self.console.print(
                f"[bold red]Context over budget: estimated {context_report['estimated_tokens']} tokens "
                f"against num_ctx {context_report['num_ctx']}, even after dropping older messages. "
                "Turn refused. Start a new session or clear history.[/bold red]"
            )
            return
        if context_report["dropped_count"] > 0:
            self.console.print(
                f"[bold yellow]Context note: dropped {context_report['dropped_count']} older message(s) "
                f"to fit num_ctx {context_report['num_ctx']}. Estimated context: "
                f"{context_report['estimated_tokens']} tokens.[/bold yellow]"
            )

        # v1.1 failed-turn rule: if this turn produces no assistant reply,
        # the user message is removed again. A failed prompt must not sit in
        # history and be silently resent as context on the next turn.
        def discard_turn(reason):
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()
            self.console.print(f"[bold red]{reason}[/bold red]")

        full_response = ""
        turn_metrics = {}
        cancelled = False
        stream_error = None
        self.console.print(
            f"\n[bold magenta]{self.current_model}[/bold magenta] [dim]({self.current_session})[/dim]:"
        )

        try:
            res = self.client.chat_stream(
                self.current_model,
                payload_messages,
                self.params,
                think=getattr(self, "think", None),
            )
            if res.status_code != 200:
                discard_turn(
                    f"API Error {res.status_code}: turn discarded, history unchanged"
                )
                return

            with Live(
                Markdown(""), refresh_per_second=10, console=self.console
            ) as live:
                try:
                    for line in res.iter_lines():
                        if line:
                            try:
                                chunk = json.loads(line)
                            except json.JSONDecodeError:
                                stream_error = (
                                    "Malformed response from Ollama: turn discarded"
                                )
                                break
                            msg_chunk = chunk.get("message", {}).get("content", "")
                            full_response += msg_chunk
                            live.update(Markdown(full_response))

                            if chunk.get("done", False):
                                # v1.1: prompt count is the last turn's full
                                # context, not an amount to add to a total.
                                self.session_prompt_tokens = chunk.get(
                                    "prompt_eval_count", 0
                                )
                                self.session_completion_tokens += chunk.get(
                                    "eval_count", 0
                                )
                                turn_metrics = {
                                    "total_duration": chunk.get("total_duration", 0),
                                    "load_duration": chunk.get("load_duration", 0),
                                    "prompt_eval_count": chunk.get(
                                        "prompt_eval_count", 0
                                    ),
                                    "prompt_eval_duration": chunk.get(
                                        "prompt_eval_duration", 0
                                    ),
                                    "eval_count": chunk.get("eval_count", 0),
                                    "eval_duration": chunk.get("eval_duration", 0),
                                    "done_reason": chunk.get("done_reason", "stop"),
                                }
                except KeyboardInterrupt:
                    cancelled = True
                    self.console.print(
                        "\n[bold yellow]Stream stopped by user (Ctrl+C).[/bold yellow]"
                    )

            if stream_error:
                discard_turn(stream_error + ", history unchanged")
                return
            if cancelled:
                discard_turn(
                    "Turn cancelled: partial reply not saved, history unchanged"
                )
                self.last_metrics = {"done_reason": "cancelled"}
                if self.verbose_metrics:
                    self.render_metrics_panel(self.last_metrics)
                return
            if not full_response.strip():
                discard_turn("No response received: turn discarded, history unchanged")
                return

            self.messages.append({"role": "assistant", "content": full_response})
            self.save_history()
            print()

            if turn_metrics:
                self.last_metrics = turn_metrics
                if self.verbose_metrics:
                    self.render_metrics_panel(turn_metrics)

        except requests.exceptions.RequestException as e:
            discard_turn(
                f"Network/Ollama Error: {e}. Turn discarded, history unchanged"
            )

    # ----------------- MAIN RUN LOOP ----------------- #

    def run(self):
        banner_styles = getattr(self, "theme", THEMES["classic"])["styles"]
        banner = (
            f"[bold {banner_styles['success']}]Ollama Rich Terminal Framework[/bold {banner_styles['success']}]\n"
            f"• Type [bold {banner_styles['primary']}]/help[/bold {banner_styles['primary']}] for commands and shortcuts.\n"
            f"• Manage personas and instructions with [bold {banner_styles['primary']}]/system[/bold {banner_styles['primary']}].\n"
            f"• Dynamic context size: [bold {banner_styles['warning']}]num_ctx[/bold {banner_styles['warning']}] set to [bold {banner_styles['primary']}]"
            f"{self.params.get('num_ctx')}[/bold {banner_styles['primary']}] tokens.\n"
            f"• Toggle telemetry statistics with [bold {banner_styles['primary']}]/verbose[/bold {banner_styles['primary']}]."
        )
        if getattr(self, "theme_name", "classic") == "cyberpunk":
            banner += (
                f"\n• Theme: [bold {banner_styles['banner']}]CYBERPUNK[/bold {banner_styles['banner']}] "
                f"neon pink, cyan, and purple. Use [bold {banner_styles['primary']}]/theme classic[/bold {banner_styles['primary']}] "
                "to switch back."
            )
        self.console.print(Panel(banner))

        while True:
            try:
                model_lbl = self.current_model if self.current_model else "No Model"
                mode_lbl = (
                    " [bold yellow][ML][/bold yellow]" if self.multiline_mode else ""
                )
                prompt_colors = getattr(self, "theme", THEMES["classic"])["prompt"]
                sys_lbl = (
                    f" <{prompt_colors['sys']}>[Sys]</{prompt_colors['sys']}>"
                    if self.system_prompt
                    else ""
                )

                prompt_html = HTML(
                    f"<{prompt_colors['title']}><b>Ollama</b></{prompt_colors['title']}> "
                    f"<{prompt_colors['session']}>({self.current_session})</{prompt_colors['session']}> "
                    f"<{prompt_colors['model']}>[{model_lbl}]</{prompt_colors['model']}>{sys_lbl}{mode_lbl} <b>&gt;</b> "
                )

                user_input = self.pt_session.prompt(
                    prompt_html, multiline=self.multiline_mode
                ).strip()

                if not user_input:
                    continue

                # Multiline capture with triple quotes ("""...""")
                if user_input.startswith('"""') and not user_input.endswith('"""', 3):
                    buffer = [user_input[3:]]
                    self.console.print(
                        '[dim]Multiline block opened. End with closing triple quotes (""")[/dim]'
                    )
                    while True:
                        line = self.pt_session.prompt("... ")
                        if line.endswith('"""'):
                            buffer.append(line[:-3])
                            break
                        buffer.append(line)
                    user_input = "\n".join(buffer).strip()

                # Command Dispatcher
                if user_input.startswith("/"):
                    cmd_parts = user_input.split(maxsplit=1)
                    command = cmd_parts[0].lower()
                    argument = cmd_parts[1].strip() if len(cmd_parts) > 1 else None

                    if command in ("/exit", "/quit"):
                        self.console.print(
                            "[bold yellow]Exiting framework. Goodbye![/bold yellow]"
                        )
                        break
                    elif command == "/help":
                        self.print_help()
                    elif command == "/system":
                        self.manage_system_prompt(argument)
                    elif command == "/models":
                        self.manage_models(argument)
                    elif command == "/params":
                        self.manage_params(argument)
                    elif command == "/verbose":
                        self.verbose_metrics = not self.verbose_metrics
                        state = (
                            "[bold green]ENABLED[/bold green]"
                            if self.verbose_metrics
                            else "[bold yellow]DISABLED[/bold yellow]"
                        )
                        self.console.print(f"Verbose Ollama telemetry is now {state}.")
                    elif command == "/tokens":
                        self.view_tokens()
                    elif command == "/context":
                        self.view_context()
                    elif command == "/file":
                        self.attach_file(argument)
                    elif command == "/sessions":
                        self.list_sessions()
                    elif command == "/new":
                        s_name = argument or Prompt.ask(
                            "Enter new session name", default="default"
                        )
                        if self.create_new_session(s_name):
                            self.console.print(
                                f"[bold green]Created clean session: '{self.current_session}'[/bold green]"
                            )
                    elif command in ("/newchat", "/fresh"):
                        self.start_ephemeral_chat()
                        self.console.print(
                            "[bold green]Started an ephemeral chat with "
                            f"{self.current_model}: history is in memory only "
                            "and no session file will be written. Use /load "
                            "or /new to return to a tracked session; exiting "
                            "loses this chat.[/bold green]"
                        )
                    elif command == "/load":
                        s_name = argument or Prompt.ask(
                            "Enter session name to load", default="default"
                        )
                        existed = os.path.exists(self._get_session_path(s_name))
                        ok = self.load_session(s_name)
                        if existed and not ok:
                            self.console.print(
                                f"[bold yellow]Could not load '{s_name}': started empty instead.[/bold yellow]"
                            )
                        else:
                            self.console.print(
                                f"[bold green]Loaded session: '{self.current_session}' ({len(self.messages)} turns)[/bold green]"
                            )
                    elif command == "/multiline":
                        self.multiline_mode = not self.multiline_mode
                        state = (
                            "[bold green]ON[/bold green] (Press [bold cyan]Esc+Enter[/bold cyan] to send)"
                            if self.multiline_mode
                            else "[bold yellow]OFF[/bold yellow]"
                        )
                        self.console.print(f"Multiline input mode is now {state}.")
                    elif command == "/theme":
                        self.manage_theme(argument)
                    elif command == "/history":
                        self.manage_history()
                    else:
                        self.console.print(
                            "[bold red]Unknown command. Type /help to see all options.[/bold red]"
                        )
                else:
                    self.handle_chat(user_input)

            except KeyboardInterrupt:
                self.console.print("\n[dim]Press /exit or Ctrl+D to quit.[/dim]")
            except EOFError:
                self.console.print(
                    "\n[bold yellow]Session terminated. Goodbye![/bold yellow]"
                )
                break


def main(argv=None):
    """v1.2 packaging entry point. Also used by the ollama-cli script.

    v1.4: --ephemeral (alias --fresh) starts in ephemeral mode, the
    same state /newchat reaches from inside the REPL.
    v1.5: --no-think sets think to False for the run, which a tracked
    session then persists on its next save, like /params think off.
    v1.6: --theme sets the colour theme for the run and persists it
    as the global preference, like /theme.
    """
    parser = argparse.ArgumentParser(prog="ollama-cli")
    parser.add_argument(
        "--ephemeral",
        "--fresh",
        dest="ephemeral",
        action="store_true",
        help="start an ephemeral chat: same model, no session file written",
    )
    parser.add_argument(
        "--no-think",
        dest="no_think",
        action="store_true",
        help="disable thinking mode for this run (sends think:false)",
    )
    parser.add_argument(
        "--theme",
        dest="theme",
        choices=list(THEMES.keys()),
        default=None,
        help="colour theme: classic or cyberpunk",
    )
    args = parser.parse_args(argv)
    cli = OllamaRichCLI()
    if args.theme:
        cli.set_theme(args.theme)
    if args.no_think:
        cli.think = False
    if args.ephemeral:
        cli.start_ephemeral_chat()
    cli.run()


if __name__ == "__main__":
    main()
