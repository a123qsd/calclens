"""Slab Preflight: conservative, local CIF geometry screening."""

from .core import UnsupportedStructure, analyze_cif

__all__ = ["UnsupportedStructure", "analyze_cif"]
__version__ = "0.1.0"
