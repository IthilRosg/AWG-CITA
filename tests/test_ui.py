import unittest

from awg_cita.ui import INDEX_HTML


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
            'data-i18n="totalTraffic"',
            "fetch('/api/status'",
            'data-runtime="read_only"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, INDEX_HTML)
        self.assertNotIn("method: 'POST'", INDEX_HTML)
        self.assertNotIn("SE" + "-1", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
