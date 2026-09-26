"""DSL package for MetaPlatform.

The DSL supports Ukrainian (uk) and English (en) keywords while producing a
single language-neutral AST.
"""

from .api import parse_dsl

__all__ = ["parse_dsl"]
