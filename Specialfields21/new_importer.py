from aqt.import_export.importing import ApkgImporter
from aqt.importing import importFile
from aqt.main import AnkiQt

# NOTE: This just disables the new APKG importer to keep the add-on working when the new import/export handling is enabled

def do_import(mw: AnkiQt, path: str) -> None:
    importFile(mw, path)


def patch_new_importer() -> None:
    ApkgImporter.do_import = do_import
