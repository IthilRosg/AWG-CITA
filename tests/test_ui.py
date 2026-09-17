import unittest
from pathlib import Path

from awg_cita.ui import INDEX_HTML

UI_JS = Path(__file__).parents[1] / "awg_cita" / "static" / "sector-console.js"


class UiTests(unittest.TestCase):
    def test_sector_console_is_localized_and_read_only(self):
        for marker in (
            'class="shell"',
            'class="language-menu"',
            'data-lang="ru"',
            'data-lang="en"',
            'data-lang="es"',
            'data-lang="zh"',
            'data-lang="de"',
            'data-lang="fr"',
            'id="peers"',
            'id="inspect-total"',
            'id="history"',
            'data-i18n="history"',
            'data-i18n="totalTraffic"',
            'data-runtime="read_only"',
            '<link rel="stylesheet" href="/static/sector-console.css">',
            '<script defer src="/static/sector-console.js"></script>',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, INDEX_HTML)
        self.assertNotIn("method: 'POST'", INDEX_HTML)
        self.assertNotIn("<style>", INDEX_HTML)
        self.assertNotIn("<script>", INDEX_HTML)
        self.assertNotIn("SE" + "-1", INDEX_HTML)
        script = UI_JS.read_text(encoding="utf-8")
        self.assertIn("fetch('/api/status'", script)
        self.assertIn("fetch('/api/history'", script)
        self.assertIn("el('history').textContent", script)
        self.assertIn("state:'ERROR'", script)
        self.assertNotIn("method: 'POST'", script)

    def test_sector_console_script_is_scoped_from_extension_globals(self):
        script = UI_JS.read_text(encoding="utf-8").strip()
        self.assertTrue(script.startswith("(()=>{"))
        self.assertTrue(script.endswith("})();"))


if __name__ == "__main__":
    unittest.main()
