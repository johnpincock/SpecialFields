from __future__ import annotations

import os
import sys
import types

import pytest
from anki.collection import Collection

try:
    from anki.import_export_pb2 import ExportAnkiPackageOptions
except ImportError:  # Anki 23.10 takes the export options as keyword arguments
    ExportAnkiPackageOptions = None

# __init__.py and config.py need a live aqt.mw, so load the GUI-free modules through a bare package instead
_addon_package = types.ModuleType("Specialfields21")
_addon_package.__path__ = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Specialfields21")
]
sys.modules.setdefault("Specialfields21", _addon_package)


@pytest.fixture
def make_collection(tmp_path):
    opened: list[Collection] = []

    def _make(name: str = "col") -> Collection:
        col = Collection(str(tmp_path / f"{name}.anki2"))
        opened.append(col)
        return col

    yield _make
    for col in opened:
        col.close()


def export_package(col: Collection, path: str, legacy: bool) -> str:
    if ExportAnkiPackageOptions is None:
        col.export_anki_package(
            out_path=path, limit=None, with_scheduling=False, with_media=False, legacy_support=legacy
        )
        return path
    col.export_anki_package(
        out_path=path,
        options=ExportAnkiPackageOptions(
            with_scheduling=False,
            with_deck_configs=False,
            with_media=False,
            legacy=legacy,
        ),
        limit=None,
    )
    return path


def add_basic_note(col: Collection, deck: str, front: str, back: str, tags: list[str]):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = front
    note["Back"] = back
    note.tags = list(tags)
    col.add_note(note, col.decks.id(deck))
    return note
