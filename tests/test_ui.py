import json
import subprocess
import unittest
from pathlib import Path

from awg_cita.ui import INDEX_HTML

UI_JS = Path(__file__).parents[1] / "awg_cita" / "static" / "sector-console.js"


def render_history(records: list[dict[str, object]]) -> str:
    harness = r'''
const fs=require('fs');
const source=fs.readFileSync(process.argv[1],'utf8');
const history=JSON.parse(process.argv[2]);
const elements=new Map();
const make=()=>({textContent:'',innerHTML:'',value:'',dataset:{},hidden:true,setAttribute(){},classList:{add(){},remove(){}}});
global.document={documentElement:{lang:''},getElementById:id=>{if(!elements.has(id))elements.set(id,make());return elements.get(id)},querySelectorAll:()=>[]};
let call=0;
global.fetch=async()=>call++===0?{ok:true,json:async()=>({state:'OK',peers:[],summary:{online:0,stale:0,offline:0,never:0,rx_bytes:0,tx_bytes:0}})}:{ok:true,json:async()=>({history})};
global.setInterval=()=>0;
eval(source);
setTimeout(()=>console.log(JSON.stringify(elements.get('history').textContent)),0);
'''
    completed = subprocess.run(
        ["node", "-e", harness, str(UI_JS), json.dumps(records)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


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

    def test_history_renders_a_bounded_newest_first_transition_log(self):
        records = [
            {"checked_at": "one", "state": "OK", "peer_count": 1, "summary": {"online": 0, "stale": 0, "offline": 0, "never": 1, "unknown": 0}},
            {"checked_at": "two", "state": "OK", "peer_count": 1, "summary": {"online": 0, "stale": 0, "offline": 0, "never": 1, "unknown": 0}},
            {"checked_at": "three", "state": "ERROR", "error_code": "awg_command_failed"},
            {"checked_at": "four", "state": "ERROR", "error_code": "awg_command_failed"},
            {"checked_at": "five", "state": "OK", "peer_count": 1, "summary": {"online": 1, "stale": 0, "offline": 0, "never": 0, "unknown": 0}},
        ]
        self.assertEqual(render_history(records).splitlines(), [
            "five · OK · 1 клиентов · 1 онлайн · 0 устаревших",
            "three · ERROR · awg_command_failed",
            "one · OK · 1 клиентов · 0 онлайн · 0 устаревших",
        ])

    def test_history_caps_visible_transitions_at_six_rows(self):
        records = [
            {"checked_at": str(index), "state": "OK", "peer_count": index, "summary": {"online": index, "stale": 0, "offline": 0, "never": 0, "unknown": 0}}
            for index in range(8)
        ]
        visible = render_history(records).splitlines()
        self.assertEqual(len(visible), 6)
        self.assertTrue(visible[0].startswith("7 ·"))
        self.assertTrue(visible[-1].startswith("2 ·"))


if __name__ == "__main__":
    unittest.main()
