"""mpdb package.

The project keeps the storage engine under src/mpdb. Expose the main public
entrypoints here so other layers can `import mpdb` cleanly.
"""

from .mpdb import Mpdb, MpdbError
from .doctor import check as doctor_check

__all__ = ["Mpdb", "MpdbError", "doctor_check"]
