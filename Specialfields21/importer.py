"""Wrapper for the native importer. It copies the protected fields/tags before the import and pastes them back after."""

from __future__ import annotations

import functools
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from anki._backend import RustBackend
from anki.collection import (
    Collection,
    ImportAnkiPackageRequest,
    ImportLogWithChanges,
    OpChanges,
    StripHtmlMode,
)
from anki.decks import DeckDict
from anki.hooks import wrap
from anki.import_export_pb2 import ImportAnkiPackageOptions, PackageMetadata
from anki.import_export_pb2 import ImportAnkiPackageUpdateCondition as _Condition
from anki.notes import Note, NoteId

IF_NEWER = _Condition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_IF_NEWER
ALWAYS = _Condition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS
NEVER = _Condition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_NEVER

# the import stores its options as the next import screen's defaults under these keys
PRESET_KEYS = (("update_notes", "updateNotes"), ("update_notetypes", "updateNotetypes"))
PRESET_VALUES = {IF_NEWER: "IfNewer", ALWAYS: "Always", NEVER: "Never"}

COLLECTION_ENTRIES = ("meta", "collection.anki21b", "collection.anki21", "collection.anki2")
LEGACY_PACKAGE_VERSIONS = (PackageMetadata.VERSION_LEGACY_1, PackageMetadata.VERSION_LEGACY_2)
EMPTY_LEGACY_MEDIA_LIST = b"{}"
# zstd frame of an empty MediaEntries message, which is what a package with no media contains
EMPTY_MEDIA_LIST = b"\x28\xb5\x2f\xfd\x20\x00\x01\x00\x00"
ALWAYS_KEPT_TAG_MARKERS = ("marked", "leech")
DEFAULT_DECK_ID = 1
SQL_CHUNK = 500
UPDATE_CHUNK = 500
# import log field limit
LOG_FIELD_BYTES = 80


@dataclass(frozen=True)
class Settings:
    special_fields: frozenset[str]
    all_fields_special: bool
    combine_tags: bool
    protected_tags: tuple[str, ...]
    update_deck_description: bool
    update_note_styling: bool | None
    update_only_if_newer: bool

    @classmethod
    def from_config(cls, config: Mapping) -> Settings:
        return cls(
            special_fields=frozenset(config.get("Special field", [])),
            all_fields_special=bool(config.get("All fields are special", False)),
            combine_tags=bool(config.get("Combine tagging", False)),
            protected_tags=tuple(config.get("Protected tags", [])),
            update_deck_description=bool(config.get("update deck description", False)),
            update_note_styling=config.get("update note styling"),
            update_only_if_newer=bool(config.get("update only if newer", True)),
        )


# Package inspection
##########################################################################


@dataclass(frozen=True)
class DeckDescription:
    """Anki copies a non-empty description together with its markdown flag."""

    text: str
    markdown: bool

    @classmethod
    def of(cls, deck: DeckDict) -> DeckDescription:
        return cls(deck["desc"], bool(deck.get("md", False)))


@dataclass(frozen=True)
class PackageContents:
    guids: frozenset[str]
    deck_descriptions: dict[str, DeckDescription]


def copy_without_media(source: str, target: str) -> None:
    """Copy only the collection entries, with an empty media list.

    The list must be present, otherwise a missing one is read as a legacy JSON map, which current-format (2.1.50+) packages can't decode.
    """
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        names = set(src.namelist())
        for name in COLLECTION_ENTRIES:
            if name not in names:
                continue
            with src.open(name) as reader, dst.open(
                zipfile.ZipInfo(name), "w", force_zip64=True
            ) as writer:
                shutil.copyfileobj(reader, writer, 1 << 20)
        meta = src.read("meta") if "meta" in names else None
        dst.writestr("media", empty_media_list(meta))


def empty_media_list(meta: bytes | None) -> bytes:
    """Build an empty media list in the format the package's meta entry declares. No meta means legacy."""
    if meta is None or PackageMetadata.FromString(meta).version in LEGACY_PACKAGE_VERSIONS:
        return EMPTY_LEGACY_MEDIA_LIST
    return EMPTY_MEDIA_LIST


def inspect_package(path: str) -> PackageContents:
    with tempfile.TemporaryDirectory() as tmp:
        stripped = os.path.join(tmp, "package.apkg")
        copy_without_media(path, stripped)
        col = Collection(os.path.join(tmp, "inspect.anki2"))
        try:
            col.import_anki_package(
                ImportAnkiPackageRequest(
                    package_path=stripped,
                    options=ImportAnkiPackageOptions(
                        update_notes=NEVER, update_notetypes=NEVER
                    ),
                )
            )
            guids = frozenset(col.db.list("select guid from notes"))
            decks = {
                deck.name: DeckDescription.of(col.decks.get(deck.id))
                for deck in col.decks.all_names_and_ids()
                if deck.id != DEFAULT_DECK_ID
            }
        finally:
            col.close()
    return PackageContents(guids, decks)


# Snapshot of local data
##########################################################################


@dataclass(frozen=True)
class NoteState:
    fields: dict[str, str]
    tags: list[str]


@dataclass(frozen=True)
class Snapshot:
    notes: dict[int, NoteState]
    deck_descriptions: dict[str, DeckDescription]


def take_snapshot(col: Collection, package: PackageContents, settings: Settings) -> Snapshot:
    notes: dict[int, NoteState] = {}
    names_by_notetype: dict[int, list[str]] = {}
    guids = sorted(package.guids)
    for start in range(0, len(guids), SQL_CHUNK):
        chunk = guids[start : start + SQL_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        rows = col.db.all(
            f"select id, mid, flds, tags from notes where guid in ({placeholders})", *chunk
        )
        for nid, mid, flds, tags in rows:
            names = names_by_notetype.get(mid)
            if names is None:
                names = [f["name"] for f in col.models.get(mid)["flds"]]
                names_by_notetype[mid] = names
            values = dict(zip(names, flds.split("\x1f")))
            if not settings.all_fields_special:
                values = {n: v for n, v in values.items() if n in settings.special_fields}
            notes[nid] = NoteState(values, col.tags.split(tags))
    decks = {}
    for name in package.deck_descriptions:
        deck = col.decks.by_name(name)
        if deck:
            decks[name] = DeckDescription.of(deck)
    return Snapshot(notes, decks)


# Merge rules
##########################################################################


def merge_fields(local: Mapping[str, str], note: Note) -> bool:
    # NOTE: local values win for protected fields that still exist on the note.
    names = set(note.keys())
    changed = False
    for name, value in local.items():
        if name in names and note[name] != value:
            note[name] = value
            changed = True
    return changed


def merge_tags(local: Sequence[str], incoming: Sequence[str], settings: Settings) -> list[str]:
    """Merge tags by incoming first; local tags survive when combining, protected, marked or leech."""
    result = list(incoming)
    seen = {tag.lower() for tag in incoming}
    for tag in local:
        if tag.lower() in seen:
            continue
        keep = (
            settings.combine_tags
            or any(phrase in tag for phrase in settings.protected_tags)
            or any(marker in tag for marker in ALWAYS_KEPT_TAG_MARKERS)
        )
        if keep:
            result.append(tag)
            seen.add(tag.lower())
    return result


def apply_settings_to_options(options: ImportAnkiPackageOptions, settings: Settings) -> None:
    if settings.update_note_styling is not None:
        options.update_notetypes = ALWAYS if settings.update_note_styling else NEVER
    if options.update_notes != NEVER:
        options.update_notes = IF_NEWER if settings.update_only_if_newer else ALWAYS


def presets_to_restore(
    chosen: ImportAnkiPackageOptions, applied: ImportAnkiPackageOptions
) -> dict[str, str]:
    """Get the import screen's original choices pre-override as config values for restore."""
    return {
        key: PRESET_VALUES[getattr(chosen, field)]
        for field, key in PRESET_KEYS
        if getattr(chosen, field) != getattr(applied, field)
    }


# Restore
##########################################################################


def notes_to_restore(
    col: Collection, snapshot: Snapshot, log: ImportLogWithChanges.Log, settings: Settings
) -> list[Note]:
    changed: list[Note] = []
    for entry in log.updated:
        state = snapshot.notes.get(entry.id.nid)
        if state is None:
            continue
        note = col.get_note(NoteId(entry.id.nid))
        touched = merge_fields(state.fields, note)
        tags = merge_tags(state.tags, note.tags, settings)
        if tags != note.tags:
            note.tags = tags
            touched = True
        if touched:
            changed.append(note)
    return changed


def decks_to_restore(
    col: Collection, snapshot: Snapshot, package: PackageContents, settings: Settings
) -> list[DeckDict]:
    changed: list[DeckDict] = []
    for name, incoming in package.deck_descriptions.items():
        deck = col.decks.by_name(name)
        if not deck or deck["dyn"]:
            continue
        if settings.update_deck_description:
            # text only, since anki already copied the flag for a non-empty description (23.10 always reads it as off)
            wanted = DeckDescription(incoming.text, DeckDescription.of(deck).markdown)
        else:
            wanted = snapshot.deck_descriptions.get(name)
        if wanted is None or DeckDescription.of(deck) == wanted:
            continue
        deck["desc"], deck["md"] = wanted.text, wanted.markdown
        changed.append(deck)
    return changed


def save_in_import_step(
    col: Collection,
    step: int,
    notes: list[Note],
    decks: list[DeckDict],
    presets: dict[str, str],
) -> OpChanges:
    """Write everything into the import's undo step.

    This will merge after each write (note that anki keeps 30 undo steps)
    """
    writes: list[Callable[[], object]] = [
        functools.partial(col.update_notes, notes[start : start + UPDATE_CHUNK])
        for start in range(0, len(notes), UPDATE_CHUNK)
    ]
    writes += [functools.partial(col.decks.update_dict, deck) for deck in decks]
    writes += [
        functools.partial(col.set_config, key, value, undoable=True)
        for key, value in presets.items()
    ]
    changes = OpChanges()
    for write in writes:
        write()
        changes = col.merge_undo_entries(step)
    return changes


def merge_failed_restore(col: Collection, step: int | None) -> str:
    """After a failed restore, merge what was already written and say whether undo still works."""
    message = (
        "The import completed, but Special Fields could not restore your protected fields and tags"
    )
    if step is None:
        return message + ". The import changed nothing, so there is nothing to undo."
    merge_error = None
    try:
        if col.undo_status().undo:
            col.merge_undo_entries(step)
            return message + ". Use Edit > Undo Import to revert the import."
    except Exception as exc:
        merge_error = exc
    message += (
        ", and the import can no longer be undone. If you need the previous state, restore "
        "one of Anki's automatic backups (File > Switch Profile > Open Backup)."
    )
    if merge_error is not None:
        message += f" Merging the undo step failed: {merge_error}"
    return message


def show_restored_fields(col: Collection, log: ImportLogWithChanges.Log, notes: list[Note]) -> None:
    """Make the import screen show what is now in the collection, reduced the way anki does it."""
    restored = {note.id: note for note in notes}
    for entry in log.updated:
        note = restored.get(entry.id.nid)
        if note is not None:
            entry.fields[:] = [log_field(col, value) for value in note.fields]


def log_field(col: Collection, value: str) -> str:
    text = col._backend.strip_html(text=value, mode=StripHtmlMode.PRESERVE_MEDIA_FILENAMES)
    return text.replace("\n", " ").encode("utf-8")[:LOG_FIELD_BYTES].decode("utf-8", "ignore")


def run_import(
    col: Collection,
    request: ImportAnkiPackageRequest,
    settings: Settings,
    do_import: Callable[[bytes], bytes],
) -> ImportLogWithChanges:
    package = inspect_package(request.package_path)
    snapshot = take_snapshot(col, package, settings)
    chosen = ImportAnkiPackageOptions()
    chosen.CopyFrom(request.options)
    apply_settings_to_options(request.options, settings)
    presets = presets_to_restore(chosen, request.options)
    response = ImportLogWithChanges.FromString(do_import(request.SerializeToString()))
    # nothing changed so there is no undo step to merge into
    import_step = col.undo_status().last_step if response.changes.mtime else None
    try:
        if response.changes.notetype:
            # notetypes changed on the Rust side so pylib's cache is stale
            col.models._clear_cache()
        notes = notes_to_restore(col, snapshot, response.log, settings)
        decks = decks_to_restore(col, snapshot, package, settings)
        if notes or decks or presets:
            if import_step is None:
                import_step = col.add_custom_undo_entry(col.tr.actions_import())
            response.changes.CopyFrom(
                save_in_import_step(col, import_step, notes, decks, presets)
            )
    except Exception as exc:
        raise RuntimeError(merge_failed_restore(col, import_step)) from exc
    show_restored_fields(col, response.log, notes)
    return response


# Installation
##########################################################################

_original_import_anki_package_raw = RustBackend.import_anki_package_raw


def install(
    resolve_collection: Callable[[RustBackend], Collection | None],
    settings: Callable[[], Settings],
    should_apply: Callable[[str], bool],
) -> None:
    """Wrap the backend import call the import screen and the API both use."""

    def import_anki_package_raw(backend: RustBackend, message: bytes, _old) -> bytes:
        request = ImportAnkiPackageRequest.FromString(message)
        col = resolve_collection(backend)
        if col is None or not should_apply(request.package_path):
            return _old(backend, message)

        def do_import(data: bytes) -> bytes:
            return _old(backend, data)

        return run_import(col, request, settings(), do_import).SerializeToString()

    RustBackend.import_anki_package_raw = wrap(
        _original_import_anki_package_raw, import_anki_package_raw, "around"
    )
