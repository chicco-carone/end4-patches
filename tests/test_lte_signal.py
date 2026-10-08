"""Exercise the patched QML service with real Quickshell and a fake mmcli."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


def cellular_source():
    patch = (REPO / "lte-signal.patch").read_text()
    section = patch.split("+++ b/services/Cellular.qml\n", 1)[1]
    return "\n".join(line[1:] for line in section.splitlines() if line.startswith("+")) + "\n"


def modem(state="connected", strength="22", technology="lte"):
    return {"modem": {
        "generic": {"state": state, "signal-quality": {"value": strength},
                    "access-technologies": [technology], "model": "Test modem"},
        "3gpp": {"operator-name": "Test carrier"},
    }}


@unittest.skipUnless(shutil.which("quickshell"), "Quickshell is required for QML integration tests")
class CellularTests(unittest.TestCase):
    def run_service(self, modems, raw_list=None, exit_code=0, extra_qml="", remove_on_refresh=False):
        with tempfile.TemporaryDirectory(prefix="end4-lte-test-") as directory:
            root = Path(directory)
            (root / "services").mkdir()
            (root / "bin").mkdir()
            (root / "services/Cellular.qml").write_text(cellular_source())
            (root / "services/qmldir").write_text("singleton Cellular 1.0 Cellular.qml\n")
            paths = [f"/org/freedesktop/ModemManager1/Modem/{i}" for i in range(len(modems))]
            (root / "fixture.json").write_text(json.dumps({
                "paths": paths, "modems": dict(zip(paths, modems)),
                "raw_list": raw_list, "exit_code": exit_code,
                "remove_on_refresh": remove_on_refresh,
            }))
            fake = root / "bin/mmcli"
            fake.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
fixture = json.loads(Path(os.environ['LTE_TEST_FIXTURE']).read_text())
if '--list-modems' in sys.argv:
    if fixture['remove_on_refresh']:
        fixture['remove_on_refresh'] = False
        updated = dict(fixture, paths=[])
        Path(os.environ['LTE_TEST_FIXTURE']).write_text(json.dumps(updated))
    print(fixture['raw_list'] if fixture['raw_list'] is not None else json.dumps({'modem-list': fixture['paths']}))
    sys.exit(fixture['exit_code'])
path = sys.argv[sys.argv.index('--modem') + 1]
value = fixture['modems'][path]
if value is None:
    sys.exit(1)  # Removed between listing and reading.
print(json.dumps(value))
""")
            fake.chmod(0o755)
            (root / "shell.qml").write_text("""
import QtQuick
import Quickshell
import "services" as Services
ShellRoot {
    property bool present: Services.Cellular.present
    Timer {
        running: true
        interval: 1000
        onTriggered: {
            EXTRA_QML
            console.log("LTE_TEST_RESULT", JSON.stringify({
                present: Services.Cellular.present,
                strength: Services.Cellular.strength,
                state: Services.Cellular.state,
                icon: Services.Cellular.materialSymbol,
                description: Services.Cellular.description
            }));
            Qt.quit();
        }
    }
}
""".replace("EXTRA_QML", extra_qml).replace("interval: 1000", "interval: 11500" if remove_on_refresh else "interval: 1000"))
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                               PATH=str(root / "bin") + os.pathsep + os.environ["PATH"],
                               LTE_TEST_FIXTURE=str(root / "fixture.json"))
            result = subprocess.run(["quickshell", "-p", str(root), "--no-color"],
                                    env=environment, text=True, capture_output=True, timeout=20)
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertNotIn("ERROR", output)
            for line in output.splitlines():
                if "LTE_TEST_RESULT " in line:
                    return json.loads(line.split("LTE_TEST_RESULT ", 1)[1])
            self.fail(output)

    def test_connected_lte(self):
        result = self.run_service([modem()])
        self.assertTrue(result["present"])
        self.assertEqual(result["icon"], "signal_cellular_1_bar")
        self.assertEqual(result["description"], "Test carrier · LTE · connected · 22%")

    def test_no_modem_or_unavailable_manager(self):
        for raw, code in [(None, 0), ("bad json", 0), ("{}", 1), ('{"modem-list":null}', 0)]:
            with self.subTest(raw=raw, code=code):
                self.assertFalse(self.run_service([], raw_list=raw, exit_code=code)["present"])

    def test_connected_modem_has_priority_and_removal_is_tolerated(self):
        result = self.run_service([modem("registered", "90"), None, modem("connected", "55")])
        self.assertEqual(result["state"], "connected")
        self.assertEqual(result["strength"], 55)
        self.assertEqual(result["icon"], "signal_cellular_3_bar")

    def test_refresh_hides_a_removed_modem(self):
        self.assertFalse(self.run_service([modem()], remove_on_refresh=True)["present"])

    def test_signal_thresholds_and_states(self):
        # Validate every threshold and ensure unknown values do not look like good signal.
        cases = [("connected", value, f"signal_cellular_{bars}_bar")
                 for value, bars in [(0, 0), (1, 1), (25, 1), (26, 2), (50, 2),
                                     (51, 3), (75, 3), (76, 4), (100, 4), (200, 4), (-2, 0)]]
        cases += [("connected", "--", "signal_cellular_nodata"),
                  ("searching", 80, "signal_cellular_nodata"),
                  ("locked", 80, "signal_cellular_off"),
                  ("disabled", 80, "signal_cellular_off")]
        code = "const cases = " + json.dumps(cases) + ";\n"
        code += """
            for (const [state, strength, expected] of cases) {
                Services.Cellular.modem = {generic: {state: state, 'signal-quality': {value: strength}}};
                if (Services.Cellular.materialSymbol !== expected)
                    throw new Error(JSON.stringify([state, strength, expected, Services.Cellular.materialSymbol]));
            }
        """
        self.run_service([], extra_qml=code)


if __name__ == "__main__":
    unittest.main()
