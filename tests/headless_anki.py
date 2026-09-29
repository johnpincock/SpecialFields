"""Runs headless anki subprocess: python tests/headless_anki.py <base_dir> <addon_source_dir>"""

from __future__ import annotations

import faulthandler
import json
import os
import shutil
import sys
import traceback

faulthandler.dump_traceback_later(150, exit=True)

ADDON_ID = "1102281552"


def install_addon(base: str, source: str) -> None:
    target = os.path.join(base, "addons21", ADDON_ID)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        os.symlink(source, target)
    except OSError:
        shutil.copytree(source, target)


def silence_dialogs() -> None:
    import aqt.addons
    import aqt.profiles
    import aqt.utils
    from aqt.qt import QMessageBox

    for name in ("warning", "critical", "information", "question"):
        setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    aqt.profiles.ProfileManager.setDefaultLang = lambda self, *a, **k: self.setLang("en_US")
    for module in (aqt.utils, aqt.addons):
        for name in ("showWarning", "showInfo", "showCritical"):
            if hasattr(module, name):
                setattr(module, name, lambda *a, **k: None)


def exercise_import(mw, base: str) -> dict:
    from anki.collection import Collection
    from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest

    try:
        from anki.import_export_pb2 import ExportAnkiPackageOptions
    except ImportError:
        ExportAnkiPackageOptions = None

    from importlib import import_module

    dialog = import_module(f"{ADDON_ID}.dialog")
    importer = import_module(f"{ADDON_ID}.importer")

    src = Collection(os.path.join(base, "src.anki2"))
    note = src.new_note(src.models.by_name("Basic"))
    note["Front"], note["Back"], note.tags = "F1", "B1", ["t1"]
    src.add_note(note, src.decks.id("Deck"))
    # mtimes are whole seconds, so push the source note back to make the local edit newer without sleeping
    src.db.execute("update notes set mod = mod - 100 where id = ?", note.id)
    package = os.path.join(base, "deck.apkg")
    if ExportAnkiPackageOptions is None:
        src.export_anki_package(
            out_path=package, limit=None, with_scheduling=False, with_media=False, legacy_support=True
        )
    else:
        src.export_anki_package(
            out_path=package,
            options=ExportAnkiPackageOptions(legacy=True),
            limit=None,
        )
    src.close()

    mw.col = Collection(os.path.join(base, "dst.anki2"))
    request = ImportAnkiPackageRequest(
        package_path=package, options=ImportAnkiPackageOptions(update_notes=importer.ALWAYS)
    )
    mw.col.import_anki_package(request)
    local = mw.col.get_note(mw.col.find_notes("")[0])
    local["Back"] = "LOCAL"
    local.tags = ["mine"]
    mw.col.update_note(local)

    dialog.arm_package(package)
    mw.col.import_anki_package(request)
    armed = mw.col.get_note(local.id)
    result = {"armed_back": armed["Back"], "armed_tags": armed.tags}

    mw.col.import_anki_package(request)
    unarmed = mw.col.get_note(local.id)
    result.update({"unarmed_back": unarmed["Back"], "unarmed_tags": unarmed.tags})
    mw.col.close()
    return result


def exercise_gate(mw) -> dict:
    from importlib import import_module

    dialog = import_module(f"{ADDON_ID}.dialog")
    old_ask_user = dialog.askUser
    ask_calls = []
    result = {}

    def ask_true(*a, **k):
        ask_calls.append(True)
        return True

    def ask_false(*a, **k):
        return False

    def call(path):
        calls = []
        dialog.import_file_override(mw, path, lambda m, p: calls.append(p))
        return calls

    dialog.askUser = ask_true
    skip_ok = True
    for path in ("/x/collection.apkg", "/x/backup-1.apkg", "/x/col.colpkg"):
        calls = call(path)
        skip_ok = skip_ok and calls == [path] and dialog.consume_armed_package(path) is False
    result["gate_skips_colpkg"] = skip_ok and not ask_calls

    dialog.askUser = ask_true
    calls = call("/x/deck.apkg")
    result["gate_accept_arms"] = (
        calls == ["/x/deck.apkg"]
        and dialog.consume_armed_package("/x/deck.apkg") is True
        and dialog.consume_armed_package("/x/deck.apkg") is False
    )

    dialog.askUser = ask_false
    calls = call("/x/deck.apkg")
    result["gate_decline_clears"] = calls == ["/x/deck.apkg"] and dialog.consume_armed_package("/x/deck.apkg") is False

    dialog.askUser = ask_true
    call("/x/one.apkg")
    dialog.askUser = ask_false
    call("/x/two.apkg")
    result["gate_later_call_clears"] = dialog.consume_armed_package("/x/one.apkg") is False

    dialog.askUser = old_ask_user
    return result


def exercise_legacy_gate(mw) -> dict:
    """Anki 23.10 to 26.08 route imports to aqt.importing when legacy import/export is on."""
    from importlib import import_module

    dialog = import_module(f"{ADDON_ID}.dialog")
    if dialog.legacy_importing is None:
        return {"legacy_gate_available": False, "legacy_gate_accept": True, "legacy_gate_decline": True}

    old_ask_user, old_new_import_file = dialog.askUser, dialog.new_import_file
    new_calls, legacy_calls = [], []
    dialog.new_import_file = lambda m, p: new_calls.append(p)

    def run(answer):
        new_calls.clear()
        legacy_calls.clear()
        dialog.askUser = lambda *a, **k: answer
        dialog.legacy_import_file_override(mw, "/x/deck.apkg", lambda m, p: legacy_calls.append(p))
        return dialog.consume_armed_package("/x/deck.apkg")

    try:
        accept_armed = run(True)
        accept = accept_armed and new_calls == ["/x/deck.apkg"] and not legacy_calls
        decline_armed = run(False)
        decline = not decline_armed and legacy_calls == ["/x/deck.apkg"] and not new_calls
    finally:
        dialog.askUser, dialog.new_import_file = old_ask_user, old_new_import_file
    return {
        "legacy_gate_available": hasattr(dialog.legacy_importing.importFile, "__wrapped__"),
        "legacy_gate_accept": accept,
        "legacy_gate_decline": decline,
    }


def main(base: str, source: str) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["ANKI_NOHIGHDPI"] = "1"
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
    install_addon(base, source)
    import aqt

    silence_dialogs()
    aqt._run(["anki", "-b", base], exec=False)
    mw = aqt.mw
    report = {"loaded": ADDON_ID in sys.modules}
    if report["loaded"]:
        import aqt.import_export.importing as importing_ui
        import aqt.main
        from anki._backend import RustBackend

        report["import_file_wrapped"] = hasattr(importing_ui.import_file, "__wrapped__")
        report["backend_wrapped"] = hasattr(RustBackend.import_anki_package_raw, "__wrapped__")
        report["main_rebound"] = not hasattr(aqt.main, "import_file") or aqt.main.import_file is importing_ui.import_file
        report["menu"] = "Special Fields" in [a.text() for a in mw.form.menuTools.actions()]
        report["config_action"] = ADDON_ID in mw.addonManager._configButtonActions
        report.update(exercise_gate(mw))
        report.update(exercise_legacy_gate(mw))
        try:
            report.update(exercise_import(mw, base))
        except Exception:
            report["import_error"] = traceback.format_exc()
    print("REPORT " + json.dumps(report), flush=True)
    return 0 if report["loaded"] else 1


if __name__ == "__main__":
    code = main(sys.argv[1], sys.argv[2])
    sys.stdout.flush()
    os._exit(code)
