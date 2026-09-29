from __future__ import annotations

import functools
import os
import tempfile
import zipfile

import pytest
from anki.collection import Collection, ImportAnkiPackageRequest, ImportLogWithChanges
from anki.errors import BackendError
from anki.import_export_pb2 import ImportAnkiPackageOptions

from Specialfields21 import importer
from Specialfields21.importer import ALWAYS, IF_NEWER, NEVER, DeckDescription, Settings

from conftest import add_basic_note, export_package


def settings(**overrides) -> Settings:
    base = dict(
        special_fields=frozenset(),
        all_fields_special=False,
        combine_tags=False,
        protected_tags=("%%keep%%",),
        update_deck_description=False,
        update_note_styling=None,
        update_only_if_newer=False,
    )
    base.update(overrides)
    return Settings(**base)


def test_settings_from_config_uses_addon_keys_and_defaults():
    s = Settings.from_config(
        {
            "All fields are special": True,
            "Combine tagging": True,
            "Protected tags": ["%%keep%%", "mine"],
            "Special field": ["Lecture Notes", "Personal Notes"],
            "update deck description": True,
            "update note styling": False,
            "update only if newer": False,
        }
    )
    assert s.special_fields == frozenset({"Lecture Notes", "Personal Notes"})
    assert s.all_fields_special and s.combine_tags and s.update_deck_description
    assert s.protected_tags == ("%%keep%%", "mine")
    assert s.update_note_styling is False
    assert s.update_only_if_newer is False
    defaults = Settings.from_config({})
    assert defaults.update_only_if_newer is True
    assert defaults.update_note_styling is None
    assert defaults.protected_tags == ()


def test_merge_tags_combine_keeps_every_local_tag_with_incoming_spelling():
    s = settings(combine_tags=True)
    assert importer.merge_tags(["Old", "shared"], ["SHARED", "new"], s) == ["SHARED", "new", "Old"]


def test_merge_tags_protected_mode_keeps_only_protected_marked_and_leech():
    s = settings(protected_tags=("%%keep%%", "AK"))
    local = ["drop", "%%keep%%me", "prefixAKsuffix", "marked", "unmarked", "leech", "Shared"]
    assert importer.merge_tags(local, ["shared", "new"], s) == [
        "shared",
        "new",
        "%%keep%%me",
        "prefixAKsuffix",
        "marked",
        "unmarked",
        "leech",
    ]


def test_merge_tags_protected_match_is_case_sensitive():
    s = settings(protected_tags=("keep",))
    assert importer.merge_tags(["KEEP-me"], [], s) == []
    assert importer.merge_tags(["keep-me"], [], s) == ["keep-me"]


def test_merge_fields_restores_only_existing_fields_and_reports_change(make_collection):
    col = make_collection()
    note = add_basic_note(col, "Deck", "F", "B", [])
    assert importer.merge_fields({"Back": "LOCAL", "Missing": "x"}, note) is True
    assert note["Back"] == "LOCAL" and note["Front"] == "F"
    assert importer.merge_fields({"Back": "LOCAL"}, note) is False
    assert importer.merge_fields({"Back": ""}, note) is True
    assert note["Back"] == ""


def test_apply_settings_to_options_maps_addon_settings_onto_import_options():
    opts = ImportAnkiPackageOptions(update_notes=IF_NEWER, update_notetypes=IF_NEWER)
    importer.apply_settings_to_options(opts, settings(update_only_if_newer=False))
    assert opts.update_notes == ALWAYS and opts.update_notetypes == IF_NEWER

    opts = ImportAnkiPackageOptions(update_notes=ALWAYS, update_notetypes=IF_NEWER)
    importer.apply_settings_to_options(opts, settings(update_only_if_newer=True, update_note_styling=True))
    assert opts.update_notes == IF_NEWER and opts.update_notetypes == ALWAYS

    opts = ImportAnkiPackageOptions(update_notes=NEVER, update_notetypes=IF_NEWER)
    importer.apply_settings_to_options(opts, settings(update_only_if_newer=False, update_note_styling=False))
    assert opts.update_notes == NEVER and opts.update_notetypes == NEVER


@pytest.mark.parametrize(
    "meta, collection, empty_media_list",
    [
        # zstd frame of an empty MediaEntries message, which is what a package with no media contains
        (b"\x08\x03", "collection.anki21b", b"\x28\xb5\x2f\xfd\x20\x00\x01\x00\x00"),
        (b"\x08\x02", "collection.anki21", b"{}"),
        (None, "collection.anki2", b"{}"),
    ],
    ids=["current-package", "legacy-package", "package-without-meta"],
)
def test_copy_without_media_keeps_collection_entries_and_an_empty_media_list(
    tmp_path, meta, collection, empty_media_list
):
    source = str(tmp_path / "in.apkg")
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as z:
        if meta is not None:
            z.writestr("meta", meta)
        z.writestr(collection, b"db-bytes")
        z.writestr("media", b'{"0": "a.jpg"}')
        z.writestr("0", b"jpeg")
    target = str(tmp_path / "out.apkg")
    importer.copy_without_media(source, target)
    with zipfile.ZipFile(target) as z:
        assert z.namelist() == [n for n in ("meta", collection, "media") if n != "meta" or meta]
        assert z.read(collection) == b"db-bytes"
        assert z.read("media") == empty_media_list
        assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())


def shift_mtime(col: Collection, note_id: int, seconds: int) -> None:
    """Bump the note's mtime instead of sleeping, since anki only compares whole seconds."""
    col.db.execute("update notes set mod = mod + ? where id = ?", seconds, note_id)


@functools.cache
def anki_imports_markdown_flag() -> bool:
    """Anki 23.10 drops a deck's markdown flag on import. Later versions keep it."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Collection(os.path.join(tmp, "src.anki2"))
        dst = Collection(os.path.join(tmp, "dst.anki2"))
        try:
            add_basic_note(src, "Probe", "F", "B", [])
            deck = src.decks.by_name("Probe")
            deck["desc"], deck["md"] = "d", True
            src.decks.update_dict(deck)
            package = export_package(src, os.path.join(tmp, "probe.apkg"), legacy=True)
            dst.import_anki_package(
                ImportAnkiPackageRequest(package_path=package, options=ImportAnkiPackageOptions())
            )
            return bool(dst.decks.by_name("Probe").get("md", False))
        finally:
            src.close()
            dst.close()


def assert_imported_description(actual: DeckDescription, expected: DeckDescription) -> None:
    """Check a description that went through an import. The flag is only checked on versions that keep it."""
    if anki_imports_markdown_flag():
        assert actual == expected
    else:
        assert actual.text == expected.text


def description(col: Collection, deck_name: str) -> DeckDescription:
    deck = col.decks.by_name(deck_name)
    return DeckDescription(deck["desc"], deck.get("md", False))


class Harness:
    """Installs the wrapper for one test collection and runs imports through it."""

    def __init__(self, col: Collection, active: Settings):
        self.col = col
        self.active = active
        self.apply = True
        importer.install(
            resolve_collection=lambda backend: col if col._backend is backend else None,
            settings=lambda: self.active,
            should_apply=lambda path: self.apply,
        )

    def import_package(self, path: str, **options) -> ImportLogWithChanges:
        request = ImportAnkiPackageRequest(
            package_path=path, options=ImportAnkiPackageOptions(**options)
        )
        return self.col.import_anki_package(request)

    def only_note(self):
        nids = self.col.find_notes("")
        assert len(nids) == 1, nids
        return self.col.get_note(nids[0])


@pytest.fixture(params=[True, False], ids=["legacy-package", "current-package"])
def legacy(request):
    return request.param


def test_inspect_package_lists_guids_and_deck_descriptions(make_collection, tmp_path, legacy):
    src = make_collection("src")
    note = add_basic_note(src, "Deck::Sub", "F", "B", ["t"])
    deck = src.decks.by_name("Deck::Sub")
    deck["desc"], deck["md"] = "D1", True
    src.decks.update_dict(deck)
    contents = importer.inspect_package(export_package(src, str(tmp_path / "p.apkg"), legacy))
    assert contents.guids == frozenset({note.guid})
    assert sorted(contents.deck_descriptions) == ["Deck", "Deck::Sub"]
    assert_imported_description(contents.deck_descriptions["Deck"], DeckDescription("", False))
    assert_imported_description(contents.deck_descriptions["Deck::Sub"], DeckDescription("D1", True))


def test_take_snapshot_keeps_protected_fields_tags_and_existing_deck_descriptions(make_collection):
    col = make_collection()
    note = add_basic_note(col, "Deck", "F", "B", ["a", "b"])
    deck = col.decks.by_name("Deck")
    deck["desc"], deck["md"] = "local", True
    col.decks.update_dict(deck)
    package = importer.PackageContents(
        frozenset({note.guid, "unknown-guid"}),
        {"Deck": DeckDescription("pkg", False), "New": DeckDescription("n", False)},
    )
    snap = importer.take_snapshot(col, package, settings(special_fields=frozenset({"Back"})))
    assert snap.notes == {note.id: importer.NoteState({"Back": "B"}, ["a", "b"])}
    assert snap.deck_descriptions == {"Deck": DeckDescription("local", True)}
    snap = importer.take_snapshot(col, package, settings(all_fields_special=True))
    assert snap.notes[note.id].fields == {"Front": "F", "Back": "B"}


def test_first_import_adds_new_notes_unchanged(make_collection, tmp_path, legacy):
    src, dst = make_collection("src"), make_collection("dst")
    add_basic_note(src, "Deck", "F1", "B1", ["t1"])
    h = Harness(dst, settings(all_fields_special=True, combine_tags=True))
    log = h.import_package(export_package(src, str(tmp_path / "a1.apkg"), legacy), update_notes=ALWAYS).log
    assert len(log.new) == 1 and not log.updated
    note = h.only_note()
    assert (note["Front"], note["Back"], note.tags) == ("F1", "B1", ["t1"])


def test_all_fields_special_keeps_local_fields_and_combines_tags(make_collection, tmp_path, legacy):
    src, dst = make_collection("src"), make_collection("dst")
    n = add_basic_note(src, "Deck", "F1", "B1", ["t1"])
    h = Harness(dst, settings(all_fields_special=True, combine_tags=True))
    h.import_package(export_package(src, str(tmp_path / "a1.apkg"), legacy), update_notes=ALWAYS)
    local = h.only_note()
    local["Back"] = "LOCAL"
    dst.update_note(local)
    n["Front"], n["Back"], n.tags = "F2", "B2", ["t2"]
    src.update_note(n)
    shift_mtime(src, n.id, 10)
    log = h.import_package(export_package(src, str(tmp_path / "a2.apkg"), legacy), update_notes=ALWAYS).log
    assert len(log.updated) == 1
    assert list(log.updated[0].fields) == ["F1", "LOCAL"]
    local = h.only_note()
    assert (local["Front"], local["Back"]) == ("F1", "LOCAL")
    assert local.tags == ["t1", "t2"]


def test_import_log_shows_restored_fields_reduced_as_anki_reduces_them(make_collection, tmp_path):
    rich = '<div>kept</div>\n<img src="pic.jpg"> ' + "é" * 50
    src, dst = make_collection("src"), make_collection("dst")
    n = add_basic_note(src, "Deck", "F1", rich, [])
    h = Harness(dst, settings(special_fields=frozenset({"Back"})))
    first = h.import_package(export_package(src, str(tmp_path / "a1.apkg"), legacy=True), update_notes=ALWAYS).log
    anki_reduced = list(first.new[0].fields)
    assert anki_reduced[1] != rich
    n["Back"] = "B2"
    src.update_note(n)
    shift_mtime(src, n.id, 10)
    log = h.import_package(export_package(src, str(tmp_path / "a2.apkg"), legacy=True), update_notes=ALWAYS).log
    assert list(log.updated[0].fields) == anki_reduced
    assert h.only_note()["Back"] == rich


def test_special_field_and_protected_tags_and_deck_description(make_collection, tmp_path, legacy):
    src, dst = make_collection("src"), make_collection("dst")
    n = add_basic_note(src, "Deck", "F1", "B1", ["t1"])
    deck = src.decks.by_name("Deck")
    deck["desc"] = "D1"
    src.decks.update_dict(deck)
    h = Harness(dst, settings(special_fields=frozenset({"Back"}), protected_tags=("%%keep%%",)))
    h.import_package(export_package(src, str(tmp_path / "a1.apkg"), legacy), update_notes=ALWAYS)
    assert dst.decks.by_name("Deck")["desc"] == "D1"
    local_flag, package_flag = True, False
    local_deck = dst.decks.by_name("Deck")
    local_deck["md"] = local_flag
    dst.decks.update_dict(local_deck)
    local = h.only_note()
    local["Back"] = "LOCAL"
    local.tags = ["t1", "%%keep%%local", "marked"]
    dst.update_note(local)
    n["Front"], n["Back"], n.tags = "F3", "B3", ["t3", "%%keep%%x"]
    src.update_note(n)
    shift_mtime(src, n.id, 10)
    deck["desc"], deck["md"] = "D2", package_flag
    src.decks.update_dict(deck)
    package = export_package(src, str(tmp_path / "a3.apkg"), legacy)

    h.active = settings(special_fields=frozenset({"Back"}), protected_tags=("%%keep%%",), update_deck_description=False)
    h.import_package(package, update_notes=ALWAYS)
    local = h.only_note()
    assert (local["Front"], local["Back"]) == ("F3", "LOCAL")
    assert local.tags == ["%%keep%%local", "%%keep%%x", "marked", "t3"]
    assert description(dst, "Deck") == DeckDescription("D1", local_flag)

    # for a non-empty description anki copies both the text and the flag from the package (23.10 always reads the flag as off)
    h.active = settings(special_fields=frozenset({"Back"}), protected_tags=("%%keep%%",), update_deck_description=True)
    h.import_package(package, update_notes=ALWAYS)
    assert description(dst, "Deck") == DeckDescription("D2", package_flag)


def test_update_only_if_newer_and_never_are_honoured(make_collection, tmp_path):
    src, dst = make_collection("src"), make_collection("dst")
    n = add_basic_note(src, "Deck", "F1", "B1", [])
    shift_mtime(src, n.id, -10)
    package = export_package(src, str(tmp_path / "a1.apkg"), legacy=True)
    h = Harness(dst, settings())
    h.import_package(package, update_notes=ALWAYS)
    local = h.only_note()
    local["Back"] = "LOCAL"
    dst.update_note(local)

    h.active = settings(update_only_if_newer=True)
    assert not h.import_package(package, update_notes=ALWAYS).log.updated
    assert h.only_note()["Back"] == "LOCAL"

    h.active = settings(update_only_if_newer=False)
    assert not h.import_package(package, update_notes=NEVER).log.updated
    assert h.only_note()["Back"] == "LOCAL"

    assert len(h.import_package(package, update_notes=IF_NEWER).log.updated) == 1
    assert h.only_note()["Back"] == "B1"


def test_unarmed_import_passes_through_untouched(make_collection, tmp_path):
    src, dst = make_collection("src"), make_collection("dst")
    n = add_basic_note(src, "Deck", "F1", "B1", ["t1"])
    shift_mtime(src, n.id, -10)
    package = export_package(src, str(tmp_path / "a1.apkg"), legacy=True)
    h = Harness(dst, settings(all_fields_special=True, combine_tags=True))
    h.import_package(package, update_notes=ALWAYS)
    local = h.only_note()
    local["Back"] = "LOCAL"
    local.tags = ["mine"]
    dst.update_note(local)
    h.apply = False
    assert len(h.import_package(package, update_notes=ALWAYS).log.updated) == 1
    local = h.only_note()
    assert local["Back"] == "B1" and local.tags == ["t1"]


def test_restore_is_part_of_the_import_undo_step(make_collection, tmp_path):
    src, dst = make_collection("src"), make_collection("dst")
    n = add_basic_note(src, "Deck", "F1", "B1", ["t1"])
    h = Harness(dst, settings(all_fields_special=True, combine_tags=True))
    h.import_package(export_package(src, str(tmp_path / "a1.apkg"), legacy=True), update_notes=ALWAYS)
    local = h.only_note()
    local["Back"] = "LOCAL"
    dst.update_note(local)
    n["Back"], n.tags = "B2", ["t2"]
    src.update_note(n)
    shift_mtime(src, n.id, 10)
    before = dst.undo_status().last_step
    h.import_package(export_package(src, str(tmp_path / "a2.apkg"), legacy=True), update_notes=ALWAYS)
    assert dst.undo_status().last_step == before + 1
    assert h.only_note().tags == ["t1", "t2"]
    dst.undo()
    local = h.only_note()
    assert local["Back"] == "LOCAL" and local.tags == ["t1"]


def test_restore_after_an_import_that_changed_nothing_is_one_import_undo_step(make_collection, tmp_path):
    src, dst = make_collection("src"), make_collection("dst")
    add_basic_note(src, "Deck::Sub", "F1", "B1", [])
    names = ("Deck", "Deck::Sub")
    package = export_package(src, str(tmp_path / "a1.apkg"), legacy=True)
    h = Harness(dst, settings(update_deck_description=True))
    h.import_package(package, update_notes=ALWAYS)
    for name in names:
        deck = dst.decks.by_name(name)
        deck["desc"], deck["md"] = "local", True
        dst.decks.update_dict(deck)
    assert h.import_package(package, update_notes=ALWAYS).log.duplicate
    # for an empty description anki leaves the deck alone and we only set the text
    assert [description(dst, n) for n in names] == [DeckDescription("", True)] * 2
    assert dst.undo_status().undo == dst.tr.actions_import()
    dst.undo()
    assert [description(dst, n) for n in names] == [DeckDescription("local", True)] * 2


def test_import_screen_presets_keep_the_users_choice(make_collection, tmp_path):
    src, dst = make_collection("src"), make_collection("dst")
    add_basic_note(src, "Deck", "F1", "B1", [])
    dst.set_config("updateNotes", "Never")
    dst.set_config("updateNotetypes", "Always")
    h = Harness(dst, settings(update_only_if_newer=False, update_note_styling=True))
    h.import_package(
        export_package(src, str(tmp_path / "a1.apkg"), legacy=True),
        update_notes=IF_NEWER,
        update_notetypes=NEVER,
    )
    presets = dst._backend.get_import_anki_package_presets()
    assert (presets.update_notes, presets.update_notetypes) == (IF_NEWER, NEVER)
    assert dst.undo_status().undo == dst.tr.actions_import()
    dst.undo()
    presets = dst._backend.get_import_anki_package_presets()
    assert (presets.update_notes, presets.update_notetypes) == (NEVER, ALWAYS)


def notes_state(col: Collection) -> dict:
    return {nid: (col.get_note(nid).fields, col.get_note(nid).tags) for nid in col.find_notes("")}


def import_that_restores_two_notes_one_chunk_at_a_time(make_collection, tmp_path, monkeypatch):
    """Set up two notes and an import that restores one note per chunk. Returns (dst, run_import, pre-import state)."""
    src, dst = make_collection("src"), make_collection("dst")
    originals = [add_basic_note(src, "Deck", f"F{i}", f"B{i}", ["t1"]) for i in (1, 2)]
    h = Harness(dst, settings(special_fields=frozenset({"Back"})))
    h.import_package(export_package(src, str(tmp_path / "a1.apkg"), legacy=True), update_notes=ALWAYS)
    for nid in dst.find_notes(""):
        local = dst.get_note(nid)
        local["Back"] = "LOCAL"
        dst.update_note(local)
    before = notes_state(dst)
    for n in originals:
        n["Back"], n.tags = "B-new", ["t2"]
        src.update_note(n)
        shift_mtime(src, n.id, 10)
    package = export_package(src, str(tmp_path / "a2.apkg"), legacy=True)
    monkeypatch.setattr(importer, "UPDATE_CHUNK", 1)
    return dst, lambda: h.import_package(package, update_notes=ALWAYS), before


def test_restore_failure_is_reported_and_undone_with_the_import(make_collection, tmp_path, monkeypatch):
    dst, run, before = import_that_restores_two_notes_one_chunk_at_a_time(make_collection, tmp_path, monkeypatch)
    update_notes = dst.update_notes
    calls = []

    def fail_on_second_chunk(notes):
        calls.append(notes)
        if len(calls) == 2:
            raise OSError("disk full")
        return update_notes(notes)

    monkeypatch.setattr(dst, "update_notes", fail_on_second_chunk)
    with pytest.raises(RuntimeError, match="Undo Import") as raised:
        run()
    assert isinstance(raised.value.__cause__, OSError)
    assert len(calls) == 2
    assert dst.undo_status().undo == dst.tr.actions_import()
    dst.undo()
    assert notes_state(dst) == before


def test_backend_failure_during_restore_points_to_a_backup(make_collection, tmp_path, monkeypatch):
    dst, run, _ = import_that_restores_two_notes_one_chunk_at_a_time(make_collection, tmp_path, monkeypatch)
    update_notes = dst.update_notes
    calls = []

    def break_second_chunk(notes):
        calls.append(notes)
        if len(calls) == 2:
            notes[0].mid = 1  # no such note type: the backend rejects it and discards undo history
        return update_notes(notes)

    monkeypatch.setattr(dst, "update_notes", break_second_chunk)
    with pytest.raises(RuntimeError) as raised:
        run()
    message = str(raised.value)
    assert isinstance(raised.value.__cause__, BackendError)
    assert "target undo op not found" not in str(raised.value.__cause__)
    assert "backup" in message and "Undo Import" not in message
    assert len(calls) == 2
    assert dst.undo_status().undo == ""


def test_inspection_failure_leaves_the_collection_untouched(make_collection, tmp_path):
    src, dst = make_collection("src"), make_collection("dst")
    add_basic_note(src, "Deck", "F1", "B1", ["t1"])
    h = Harness(dst, settings(all_fields_special=True))
    h.import_package(export_package(src, str(tmp_path / "a1.apkg"), legacy=True), update_notes=ALWAYS)
    local = h.only_note()
    local["Back"] = "LOCAL"
    dst.update_note(local)
    before = (local.fields, local.tags, dst.undo_status().undo, dst.undo_status().last_step)
    corrupt = tmp_path / "corrupt.apkg"
    corrupt.write_bytes(b"not a zip archive")
    with pytest.raises(zipfile.BadZipFile):
        h.import_package(str(corrupt), update_notes=ALWAYS)
    after = h.only_note()
    assert (after.fields, after.tags, dst.undo_status().undo, dst.undo_status().last_step) == before


def test_restore_beyond_ankis_undo_limit_stays_one_import_step(make_collection, tmp_path):
    src, dst = make_collection("src"), make_collection("dst")
    names = [f"Deck{i:02}" for i in range(40)]
    for name in names:
        add_basic_note(src, name, name, "B", [])
        deck = src.decks.by_name(name)
        deck["desc"] = f"package {name}"
        src.decks.update_dict(deck)
    package = export_package(src, str(tmp_path / "a1.apkg"), legacy=True)
    h = Harness(dst, settings(update_deck_description=False))
    h.import_package(package, update_notes=ALWAYS)
    for name in names:
        deck = dst.decks.by_name(name)
        deck["desc"] = f"local {name}"
        dst.decks.update_dict(deck)
    before = dst.undo_status().last_step
    h.import_package(package, update_notes=ALWAYS)
    assert [dst.decks.by_name(n)["desc"] for n in names] == [f"local {n}" for n in names]
    assert dst.undo_status().undo == dst.tr.actions_import()
    assert dst.undo_status().last_step == before + 1
    dst.undo()
    assert [dst.decks.by_name(n)["desc"] for n in names] == [f"local {n}" for n in names]
    assert dst.undo_status().undo != dst.tr.actions_import()


def test_failure_after_an_import_that_changed_nothing_says_there_is_nothing_to_undo(
    make_collection, tmp_path, monkeypatch
):
    src, dst = make_collection("src"), make_collection("dst")
    add_basic_note(src, "Deck", "F1", "B1", [])
    package = export_package(src, str(tmp_path / "a1.apkg"), legacy=True)
    h = Harness(dst, settings())
    h.import_package(package, update_notes=ALWAYS)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(importer, "notes_to_restore", fail)
    with pytest.raises(RuntimeError, match="nothing to undo") as raised:
        h.import_package(package, update_notes=ALWAYS)
    assert isinstance(raised.value.__cause__, OSError)


def test_merged_notetype_restores_fields_by_name(make_collection, tmp_path):
    src, dst = make_collection("src"), make_collection("dst")
    n = add_basic_note(src, "Deck", "F1", "B1", [])
    h = Harness(dst, settings(special_fields=frozenset({"Back"})))
    h.import_package(export_package(src, str(tmp_path / "a1.apkg"), legacy=True), update_notes=ALWAYS)
    local = h.only_note()
    local["Back"] = "LOCAL"
    dst.update_note(local)
    basic = src.models.by_name("Basic")
    src.models.add_field(basic, src.models.new_field("Extra"))
    src.models.update_dict(basic)
    n = src.get_note(n.id)
    n["Extra"], n["Back"] = "E", "B2"
    src.update_note(n)
    shift_mtime(src, n.id, 10)
    log = h.import_package(
        export_package(src, str(tmp_path / "a2.apkg"), legacy=True),
        update_notes=ALWAYS,
        merge_notetypes=True,
    ).log
    assert len(log.updated) == 1
    local = h.only_note()
    assert local["Back"] == "LOCAL" and local["Extra"] == "E"
