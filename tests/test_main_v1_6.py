import importlib.util
import io
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN_PATH = os.path.join(HERE, "..", "main_v1.6.py")

spec = importlib.util.spec_from_file_location("main_v1_6", MAIN_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def make_cli(tmpdir):
    cli = object.__new__(mod.OllamaRichCLI)
    cli.console = mod.Console(
        file=io.StringIO(),
        width=80,
        theme=mod.Theme(mod.THEMES["classic"]["styles"]),
    )
    cli.api_url = "http://localhost:11434"
    cli.client = mod.OllamaClient(cli.api_url)
    cli.base_dir = tmpdir
    cli.sessions_dir = os.path.join(tmpdir, "sessions")
    os.makedirs(cli.sessions_dir, exist_ok=True)
    cli.store = mod.SessionStore(cli.sessions_dir)
    cli.prompts_file = os.path.join(tmpdir, "system_prompts.json")
    cli.theme_file = os.path.join(tmpdir, "theme.json")
    cli.theme_name = "classic"
    cli.theme = mod.THEMES["classic"]
    cli.current_session = "default"
    cli.current_model = "test-model"
    cli.messages = []
    cli.system_prompt = None
    cli.system_prompt_template = None
    cli.system_prompt_values = {}
    cli.ephemeral = False
    cli.think = None
    cli.multiline_mode = False
    cli.verbose_metrics = False
    cli.last_metrics = {}
    cli.last_context_report = {}
    cli.presets = dict(mod.DEFAULT_PRESETS)
    cli.params = dict(mod.PARAM_DEFAULTS)
    cli.session_prompt_tokens = 0
    cli.session_completion_tokens = 0
    return cli


class ThemeTests(unittest.TestCase):
    def test_themes_exist_and_differ(self):
        self.assertIn("classic", mod.THEMES)
        self.assertIn("cyberpunk", mod.THEMES)
        self.assertNotEqual(
            mod.THEMES["classic"]["styles"],
            mod.THEMES["cyberpunk"]["styles"],
        )
        self.assertNotEqual(
            mod.THEMES["classic"]["prompt"],
            mod.THEMES["cyberpunk"]["prompt"],
        )

    def test_cyberpunk_palette_is_neon(self):
        styles = mod.THEMES["cyberpunk"]["styles"]
        self.assertEqual(styles["banner"], "#ff2a6d")
        self.assertEqual(styles["primary"], "#05d9e8")
        self.assertEqual(styles["accent"], "#b967ff")
        self.assertEqual(styles["success"], "#00ff9f")
        self.assertEqual(styles["warning"], "#f9c80e")

    def test_classic_palette_reproduces_old_colours(self):
        styles = mod.THEMES["classic"]["styles"]
        self.assertEqual(styles["accent"], "magenta")
        self.assertEqual(styles["primary"], "cyan")
        self.assertEqual(styles["success"], "green")
        self.assertEqual(styles["warning"], "yellow")
        self.assertEqual(styles["error"], "red")


class SetThemeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cli = make_cli(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_theme_switches_and_persists(self):
        self.assertTrue(self.cli.set_theme("cyberpunk"))
        self.assertEqual(self.cli.theme_name, "cyberpunk")
        self.assertEqual(self.cli.theme, mod.THEMES["cyberpunk"])
        with open(os.path.join(self.tmp.name, "theme.json")) as f:
            self.assertEqual(json.load(f), {"theme": "cyberpunk"})
        self.assertEqual(mod.load_theme_name(self.cli.theme_file), "cyberpunk")

    def test_set_theme_case_insensitive(self):
        self.assertTrue(self.cli.set_theme("Cyberpunk"))
        self.assertEqual(self.cli.theme_name, "cyberpunk")

    def test_unknown_theme_changes_nothing(self):
        self.assertFalse(self.cli.set_theme("neon-noir"))
        self.assertEqual(self.cli.theme_name, "classic")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "theme.json")))

    def test_load_theme_name_falls_back_on_bad_file(self):
        bad = os.path.join(self.tmp.name, "bad.json")
        with open(bad, "w") as f:
            f.write('{"theme": "nope"}')
        self.assertEqual(mod.load_theme_name(bad), "classic")
        self.assertEqual(
            mod.load_theme_name(os.path.join(self.tmp.name, "missing.json")), "classic"
        )

    def test_manage_theme_no_arg_shows_current_and_available(self):
        self.cli.manage_theme()
        out = self.cli.console.file.getvalue()
        self.assertIn("classic", out)
        self.assertIn("cyberpunk", out)

    def test_manage_theme_with_arg_switches(self):
        self.cli.manage_theme("cyberpunk")
        self.assertEqual(self.cli.theme_name, "cyberpunk")

    def test_theme_survives_session_switch(self):
        self.cli.set_theme("cyberpunk")
        self.cli.save_history()
        self.cli.messages = [{"role": "user", "content": "old"}]
        self.cli.load_session("default")
        self.assertEqual(self.cli.theme_name, "cyberpunk")

    def test_tokens_view_shows_theme(self):
        self.cli.set_theme("cyberpunk")
        self.cli.view_tokens()
        out = self.cli.console.file.getvalue()
        self.assertIn("Theme", out)
        self.assertIn("cyberpunk", out)

    def test_help_lists_theme_command(self):
        self.cli.print_help()
        out = self.cli.console.file.getvalue()
        self.assertIn("/theme", out)
        self.assertIn("cyberpunk", out)


if __name__ == "__main__":
    unittest.main()
