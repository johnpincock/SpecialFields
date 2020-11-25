from typing import Optional, Dict
from abc import ABC

from anki.models import NoteType
from aqt.utils import showText
from aqt import mw


class NoteTypeMapping(ABC):
    def map_card_type(tmpl_id: int) -> Optional[int]:
        pass

    def map_field(fld_id: int) -> Optional[int]:
        pass


class FieldMapping(NoteTypeMapping):
    def __init__(
        self,
        tmpl_amount: int,
        fld_mappings: Dict[int, Optional[int]],
    ):
        self.tmpl_amount = tmpl_amount
        self.fld_mappings = fld_mappings

    def map_card_type(self, tmpl_id: int) -> Optional[int]:
        return tmpl_id if tmpl_id < self.tmpl_amount else None

    def map_field(self, fld_id: int) -> Optional[int]:
        return self.fld_mappings[fld_id] if fld_id in self.fld_mappings else fld_id


def get_template_name(tmpl: Dict[str, any]) -> str:
    return tmpl["name"]


def get_field_name(fld: Dict[str, any]) -> str:
    return fld["name"]


def templates_match(model: NoteType, other_model: NoteType) -> bool:
    if len(model["tmpls"]) != len(other_model["tmpls"]):
        return False

    template_names = map(get_template_name, model["tmpls"])

    for idx, name in enumerate(template_names):
        if name != get_template_name(other_model["tmpls"][idx]):
            return False

    return True


def create_mapping_on_field_name_equality(src_model: NoteType, dst_model: NoteType) -> Optional[NoteTypeMapping]:
    if not templates_match(src_model, dst_model):
        return None

    src_fields = list(map(get_field_name, src_model["flds"]))
    dst_fields = list(map(get_field_name, dst_model["flds"]))

    field_mappings = {}

    for index, field_name in enumerate(src_fields):
        try:
            index_in_dst = dst_fields.index(field_name)
            field_mappings[index] = index_in_dst
        except ValueError:
            field_mappings[index] = None

    return FieldMapping(len(src_model["tmpls"]), field_mappings)
