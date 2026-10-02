"""Public source-link validation contract.

The implementation remains in ``link_validator`` so existing imports keep
working; this module exposes the explicit SourceLinkResolver name used by the
current architecture.
"""

from .link_validator import SourceLinkResolver, parse_quran_direct_reference

__all__ = ["SourceLinkResolver", "parse_quran_direct_reference"]
