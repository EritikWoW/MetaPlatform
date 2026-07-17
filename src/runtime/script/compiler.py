"""Runtime compatibility shim for the shared MetaScript compiler.

The canonical compiler implementation lives in ``src.dsl.compiler``.
Runtime imports are preserved here to avoid breaking historical paths.
"""

from src.dsl.compiler import *  # noqa: F401,F403
