from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


CommandHandler = Callable[[str], None]


@dataclass
class ObjContext:
    """Контекст метаданих — що саме відображає форма."""
    obj_guid:  str = ""   # GUID в маніфесті
    obj_name:  str = ""   # технічне ім'я об'єкта
    obj_type:  str = ""   # catalog / document / ...
    obj_title: str = ""   # відображувана назва
    rec_guid:  str = ""   # GUID поточного запису (порожній = новий)
    form_kind: str = ""   # list_form / object_form


def _tp_table(obj_name: str, tp_name: str) -> str:
    return f"data_tp_{obj_name.strip().lower()}_{tp_name.strip().lower()}"
