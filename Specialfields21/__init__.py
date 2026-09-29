from aqt import mw

from . import dialog, importer
from .config import getUserOption

# #########################################################
#
# See this video for how to use this add-on: https://youtu.be/cg-tQ6Ut0IQ
#
# #########################################################


def current_settings() -> importer.Settings:
    return importer.Settings.from_config(getUserOption("configs")["current config"])


def collection_for(backend):
    col = mw.col
    if col is not None and col._backend is backend:
        return col
    return None


importer.install(collection_for, current_settings, dialog.consume_armed_package)
