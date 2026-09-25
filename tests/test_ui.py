import subprocess
import unittest
from pathlib import Path

from awg_cita.ui import INDEX_HTML


PROJECT_ROOT = Path(__file__).parents[1]
UI_JS = PROJECT_ROOT / "awg_cita" / "static" / "sector-console.js"
UI_CSS = PROJECT_ROOT / "awg_cita" / "static" / "sector-console.css"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"


class UiTests(unittest.TestCase):
    def test_sector_console_shell_exposes_sprint_one_controls(self):
        for marker in (
            'data-runtime="mock_lifecycle"',
            'data-view="overview"',
            'data-view="clients"',
            'data-view="journal"',
            'id="refresh-button"',
            'id="client-search"',
            'data-status-filter="ONLINE"',
            'data-status-filter="DISABLED"',
            'data-sort-key="name"',
            'data-sort-key="status"',
            'id="client-rows"',
            'id="client-dossier"',
            'id="journal-view"',
            'id="journal-alerts"',
            'id="journal-history"',
            'id="journal-events"',
            'id="export-json"',
            'id="export-csv"',
            'id="create-preview-modal"',
            'id="preview-name"',
            'id="preview-tags"',
            'id="preview-submit"',
            'id="preview-result-boundary"',
            'id="mutation-boundary"',
            'id="client-actions-menu"',
            'id="edit-client-modal"',
            'id="delete-client-modal"',
            'id="config-preview-modal"',
            'id="config-preview-tab-qr"',
            'id="config-preview-tab-config"',
            'id="config-preview-copy"',
            'id="config-preview-download"',
            '<link rel="stylesheet" href="/static/sector-console.css">',
            '<script defer src="/static/sector-console.js"></script>',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, INDEX_HTML)
        for marker in ('id="preview-ack"', 'id="preview-step-confirm"', 'id="status-client-modal"'):
            with self.subTest(absent=marker):
                self.assertNotIn(marker, INDEX_HTML)

        self.assertIn('data-lang="ru"', INDEX_HTML)
        self.assertIn('data-lang="en"', INDEX_HTML)
        self.assertNotIn("method: 'POST'", INDEX_HTML)
        self.assertNotIn('<style>', INDEX_HTML)
        self.assertNotIn('<script>', INDEX_HTML)

    def test_sector_console_script_has_mock_adapter_and_status_fixture_coverage(self):
        script = UI_JS.read_text(encoding="utf-8")
        for marker in (
            'class MockLifecycleAdapter',
            'class MockObservabilityAdapter',
            'async previewCreateClient(input)',
            'async updateClient(id, input)',
            'async enableClient(id)',
            'async disableClient(id)',
            'async deleteClient(id)',
            'async generateConfigurationPreview(id)',
            'async listClients()',
            'async getClient(id)',
            'async refreshStatus()',
            'async listObservability()',
            'function normalizeObservability(',
            'function normalizePreviewResult(',
            'unsupported_observability_schema',
            'observabilitySchemaVersion',
            "status: 'ONLINE'",
            "status: 'IDLE'",
            "status: 'STALE'",
            "status: 'NEVER'",
            "status: 'DISABLED'",
            'peer-atlas',
            'peer-juniper',
            'function getVisibleClients()',
            'function toggleStatusFilter(status)',
            'function toggleSort(key)',
            'async function refreshStatus()',
            'function renderJournal(',
            'function safeEvidencePayload()',
            'function downloadEvidence(',
            'function openCreatePreview()',
            'function openEditClient(id)',
            'function openDeleteClient(id)',
            'function openConfigurationPreview(id)',
            'function renderActionMenu()',
            'CLIENT_UPDATED',
            'CLIENT_DISABLED',
            'CLIENT_ENABLED',
            'CLIENT_DELETED',
            'CONFIG_PREVIEWED',
            'LOCALE_CHANGED',
            'CLIENT_PREVIEWED',
            'NO PEER CREATED',
            'DRY_RUN',
            'window.history.pushState',
            'UI READY / BACKEND STUB',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

        self.assertTrue(script.startswith("(() => {"))
        self.assertTrue(script.rstrip().endswith("})();"))
        self.assertNotIn("method: 'POST'", script)
        self.assertNotIn("method: 'DELETE'", script)

    def test_sector_console_script_is_valid_javascript(self):
        completed = subprocess.run(
            ["node", "--check", str(UI_JS)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_sector_console_styles_keep_operator_console_responsive_baseline(self):
        styles = UI_CSS.read_text(encoding="utf-8")
        for marker in (
            '--bg:',
            '--red:',
            '.rail',
            '.client-row.is-selected',
            '.status-chip.is-active',
            '.dossier.is-open',
            '.table-scroll',
            '.row-actions-menu',
            '.mock-qr',
            '.modal-dialog-danger',
            '@media (max-width: 780px)',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, styles)

    def test_package_data_includes_static_svg_assets(self):
        package_data = PYPROJECT.read_text(encoding="utf-8")
        self.assertIn('"static/*.svg"', package_data)


if __name__ == "__main__":
    unittest.main()
