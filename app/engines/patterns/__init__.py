"""Musterstrategien fuer Palettierung und Vakuumplatte.

Der Import von strategies fuellt die Registry in base. Ohne ihn waere sie leer,
und get_strategy() faende nichts - deshalb steht er hier und nicht bei den
Aufrufern.
"""

from __future__ import annotations

from app.engines.patterns import strategies as _strategies  # noqa: F401
from app.engines.patterns.base import (
    LayerPattern,
    PatternLayout,
    PatternRequest,
    available_strategies,
    generate,
    get_strategy,
    register,
)

__all__ = [
    "LayerPattern",
    "PatternLayout",
    "PatternRequest",
    "available_strategies",
    "generate",
    "get_strategy",
    "register",
]
