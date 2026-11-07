"""CalcLens geometry engine: conservative, local CIF geometry screening."""

__all__ = ["UnsupportedStructure", "analyze_cif"]
__version__ = "0.9.0"


def __getattr__(name):
    # Opening the desktop diagnostics must not import ASE/NumPy or Qt first.
    # Keep the existing public scientific API, loading it only when requested.
    if name in __all__:
        from . import core

        value = getattr(core, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
