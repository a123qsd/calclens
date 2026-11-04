"""Attach reproducible source and runtime identity at a file-delivery boundary."""

from copy import deepcopy
import hashlib

import ase

from . import __version__


def with_provenance(report: dict, data: bytes, filename: str) -> dict:
    """Copy a report and identify the original file bytes without normalizing them.

    File readers must pass their original bytes, before decoding, newline conversion,
    or CIF parsing. The supplied filename is retained verbatim; local callers should
    pass a filename rather than an absolute path.
    """
    if not isinstance(data, bytes):
        raise TypeError("Provenance requires the original input bytes.")
    if not isinstance(filename, str):
        raise TypeError("The original filename must be a string.")
    result = deepcopy(report)
    result["provenance"] = {
        "original_filename": filename,
        "sha256": hashlib.sha256(data).hexdigest(),
        "calclens_version": __version__,
        "ase_version": ase.__version__,
    }
    return result
