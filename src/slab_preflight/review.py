"""Session-scoped identities and bounded reuse for interactive CIF review."""
from __future__ import annotations

from dataclasses import replace
import hashlib
from uuid import uuid4

import ase

from . import __version__
from .batch import MAX_BATCH_FILES, BatchInput, analyze_batch
from .project import ProjectEntry
from .provenance import with_provenance

MAX_CACHED_RESULTS = 40


def reconcile_uploads(uploads, previous: list[tuple[object, ProjectEntry]]):
    """Match upload records, never their position, filename or content hash.

    Streamlit recreates UploadedFile wrappers but preserves file_id. Objects
    without an uploader ID are matched by object identity (e.g. local adapters).
    Keeping the previous object reference also prevents Python ID reuse.
    """
    remaining = list(previous)
    records = []
    for upload in uploads:
        file_id = getattr(upload, "file_id", None)
        match = next((i for i, (old, _) in enumerate(remaining)
                      if (file_id is not None and file_id == getattr(old, "file_id", None))
                      or (file_id is None and old is upload)), None)
        entry = (remaining.pop(match)[1] if match is not None
                 else ProjectEntry(uuid4().hex, upload.name, upload.getvalue()))
        raw = upload.getvalue()
        changed = raw != entry.data
        records.append((upload, replace(entry, filename=upload.name, data=raw,
                                        reviewed=False if changed else entry.reviewed)))
    return records


def cached_batch(inputs: list[BatchInput], cache: dict) -> list[dict]:
    """Reuse only geometry/error results; attach each current filename afresh.

    The caller owns a per-session cache. It contains at most 40 results, including
    failed inputs, and no persisted executable serialization or shared user data.
    """
    if not 1 <= len(inputs) <= MAX_BATCH_FILES:
        raise ValueError(f"Choose between 1 and {MAX_BATCH_FILES} CIF files.")
    results = []
    for item in inputs:
        key = (hashlib.sha256(item.data).hexdigest(), item.normal_axis,
               item.short_distance, __version__, ase.__version__)
        if key not in cache:
            cache[key] = analyze_batch([
                BatchInput("", item.data, item.normal_axis, item.short_distance)
            ])[0]
        cached = cache.pop(key)
        cache[key] = cached
        while len(cache) > MAX_CACHED_RESULTS:
            del cache[next(iter(cache))]
        entry = dict(cached, filename=item.filename)
        if cached["report"] is not None:
            entry["report"] = with_provenance(cached["report"], item.data, item.filename)
        results.append(entry)
    return results
