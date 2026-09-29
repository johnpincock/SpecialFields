from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("aqt")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_addon_loads_and_protects_fields_in_a_real_anki(tmp_path):
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tests", "headless_anki.py"), str(tmp_path), os.path.join(ROOT, "Specialfields21")],
        capture_output=True,
        text=True,
        timeout=240,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    line = next((l for l in proc.stdout.splitlines() if l.startswith("REPORT ")), None)
    assert line, proc.stdout + proc.stderr
    report = json.loads(line[len("REPORT "):])
    assert report["loaded"], proc.stdout + proc.stderr
    assert report["import_file_wrapped"] and report["backend_wrapped"] and report["main_rebound"]
    assert report["menu"] and report["config_action"]
    assert "import_error" not in report, report["import_error"]
    assert report["armed_back"] == "LOCAL" and report["armed_tags"] == ["mine", "t1"]
    assert report["unarmed_back"] == "B1" and report["unarmed_tags"] == ["t1"]
    assert report["gate_skips_colpkg"]
    assert report["gate_accept_arms"]
    assert report["gate_decline_clears"]
    assert report["gate_later_call_clears"]
    assert report["legacy_gate_available"] == (importlib.util.find_spec("aqt.importing") is not None)
    assert report["legacy_gate_accept"]
    assert report["legacy_gate_decline"]
