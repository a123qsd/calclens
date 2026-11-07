"""Conservative display migration; original v0.8 workspace data stays intact."""
from __future__ import annotations

import math


def legacy_camera_state(value):
    """Keep orientation and display switches while refitting a native orthographic scene.

    3Dmol's zoom and pixel framing are renderer-specific. The original eight
    values remain in the archived `viewers` field; they are never overwritten.
    """
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        return {}
    state = {}
    for old, new in (("showCell", "cell"), ("showBonds", "bonds"), ("showLabels", "labels")):
        if type(value.get(old)) is bool:
            state[new] = value[old]
    camera = value.get("camera")
    if (not isinstance(camera, list) or len(camera) != 8
            or not all(type(item) in (int, float) and math.isfinite(item) for item in camera)):
        return state
    x, y, z, w = camera[4:]
    if abs(math.sqrt(x*x + y*y + z*z + w*w) - 1) > 0.001:
        return state
    # Euler form Rx(pitch) @ Ry(roll) @ Rz(yaw), matching StructureView.
    r00, r01, r02 = 1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)
    r12, r22 = 2*(y*z-x*w), 1-2*(x*x+y*y)
    state.update(yaw=math.atan2(-r01, r00), pitch=math.atan2(-r12, r22),
                 roll=math.asin(max(-1, min(1, r02))), zoom=1.0, pan=[0.0, 0.0])
    return state


def legacy_draft(value, entry):
    if not isinstance(value, dict) or value.get("sha256") != entry["sha256"]:
        return None
    axis, note = value.get("axis"), value.get("note")
    try:
        cutoff = float(value.get("cutoff"))
    except (TypeError, ValueError, OverflowError):
        return None
    if (not isinstance(axis, str) or axis not in ("a", "b", "c")
            or not isinstance(note, str) or len(note) > 10000
            or not math.isfinite(cutoff) or not 0.1 <= cutoff <= 3):
        return None
    return {"sha256": entry["sha256"], "normal_axis": axis, "short_distance": cutoff, "note": note}
