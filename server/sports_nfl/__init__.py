"""NFL data foundations.

This namespace is deliberately data-only.  In particular, importing it does
not import any estimator, training, Silver, Gold, or registry module.
"""

from .source_contracts import NFLVERSE_SOURCE_FAMILIES, SourceFamilyContract

__all__ = ["NFLVERSE_SOURCE_FAMILIES", "SourceFamilyContract"]
