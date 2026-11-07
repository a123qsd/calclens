"""Bounded tile rasterizer for the native scientific viewport.

All geometry shares one orthographic depth convention (larger z is nearer).
Opaque fragments write depth; translucent fragments are sorted *per pixel* and
composited in front of that depth. No triangle-centroid painter ordering is used.
The module changes display samples only, never a scientific mesh or scalar grid.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import math

import numpy as np


@dataclass
class Primitive:
    kind: str
    points: np.ndarray
    color: tuple
    radius: float = 0.0
    atom: int = -1
    shaded: bool = False
    texture: np.ndarray | None = None
    dashed: bool = False

    @cached_property
    def bounds(self):
        points = np.asarray(self.points)
        xy = points[:, :2]
        padding = self.radius + 1 if self.kind in ("sphere", "line") else 0
        if self.kind == "sprite":
            return (xy[0, 0], xy[0, 1], xy[0, 0] + self.texture.shape[1],
                    xy[0, 1] + self.texture.shape[0])
        return (*tuple(xy.min(axis=0) - padding), *tuple(xy.max(axis=0) + padding))


def _triangle_samples(items, tile):
    """Vectorize mesh triangles within a tile instead of a Python loop per face."""
    if not items:
        return None
    tx, ty, width, height = tile
    points = np.array([item.points for item in items], dtype=np.float64)
    a, b, c = points[:, 0], points[:, 1], points[:, 2]
    area = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    negative = area < 0
    old_b = b[negative].copy()
    b[negative], c[negative] = c[negative], old_b
    area = np.abs(area)
    lo = np.maximum(np.floor(points[:, :, :2].min(axis=1)).astype(int), [tx, ty])
    hi = np.minimum(np.ceil(points[:, :, :2].max(axis=1)).astype(int) + 1, [tx + width, ty + height])
    sizes = np.maximum(0, hi - lo)
    counts = sizes[:, 0] * sizes[:, 1]
    counts[area < 1e-12] = 0
    if not counts.sum():
        return None
    which = np.repeat(np.arange(len(items)), counts)
    starts = np.cumsum(counts) - counts
    offsets = np.arange(len(which)) - np.repeat(starts, counts)
    xx = lo[which, 0] + offsets % sizes[which, 0]
    yy = lo[which, 1] + offsets // sizes[which, 0]
    x, y = xx + 0.5, yy + 0.5
    a, b, c, area = a[which], b[which], c[which], area[which]

    def edge(first, second):
        return (second[:, 0] - first[:, 0]) * (y - first[:, 1]) - (second[:, 1] - first[:, 1]) * (x - first[:, 0])

    def included(value, first, second):
        delta = second[:, :2] - first[:, :2]
        top_left = (delta[:, 1] > 0) | ((delta[:, 1] == 0) & (delta[:, 0] < 0))
        return (value > 1e-9) | ((np.abs(value) <= 1e-9) & top_left)

    e0, e1, e2 = edge(b, c), edge(c, a), edge(a, b)
    mask = included(e0, b, c) & included(e1, c, a) & included(e2, a, b)
    if not mask.any():
        return None
    z = (e0[mask] * a[mask, 2] + e1[mask] * b[mask, 2] + e2[mask] * c[mask, 2]) / area[mask]
    colors = np.array([item.color for item in items], np.float32)
    return ((yy[mask] - ty) * width + xx[mask] - tx).astype(np.int32), z.astype(np.float32), colors[which[mask]]


def _samples(primitive, tile, world_per_pixel):
    """Return sparse local pixel IDs, depth and straight RGBA fragments."""
    tx, ty, width, height = tile
    lo_x, lo_y, hi_x, hi_y = primitive.bounds
    x0, y0 = max(tx, int(math.floor(lo_x))), max(ty, int(math.floor(lo_y)))
    x1, y1 = min(tx + width, int(math.ceil(hi_x)) + 1), min(ty + height, int(math.ceil(hi_y)) + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    x, y = xx + 0.5, yy + 0.5
    points = primitive.points
    if primitive.kind == "triangle":
        a, b, c = points

        def edge(first, second):
            return (second[0] - first[0]) * (y - first[1]) - (second[1] - first[1]) * (x - first[0])

        area = ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
        if abs(area) < 1e-12:
            return None
        if area < 0:
            b, c, area = c, b, -area
        e0, e1, e2 = edge(b, c), edge(c, a), edge(a, b)

        def included(value, first, second):
            # A shared edge belongs to exactly one triangle, so translucent
            # quadrilaterals do not acquire an artificial dark diagonal seam.
            delta = second[:2] - first[:2]
            top_left = delta[1] > 0 or (delta[1] == 0 and delta[0] < 0)
            return (value > 1e-9) | ((np.abs(value) <= 1e-9) & top_left)

        mask = included(e0, b, c) & included(e1, c, a) & included(e2, a, b)
        depth = (e0 * a[2] + e1 * b[2] + e2 * c[2]) / area
    elif primitive.kind == "sphere":
        center = points[0]
        nx, ny = (x - center[0]) / primitive.radius, (y - center[1]) / primitive.radius
        square = nx * nx + ny * ny
        mask = square <= 1
        dome = np.sqrt(np.maximum(0, 1 - square))
        depth = center[2] + dome * primitive.radius * world_per_pixel
    elif primitive.kind == "line":
        a, b = points
        delta = b[:2] - a[:2]
        length_sq = float(delta @ delta)
        fraction = np.clip(((x - a[0]) * delta[0] + (y - a[1]) * delta[1]) / max(length_sq, 1e-12), 0, 1)
        square = (x - a[0] - fraction * delta[0]) ** 2 + (y - a[1] - fraction * delta[1]) ** 2
        mask = square <= primitive.radius ** 2
        if primitive.dashed:
            mask &= np.mod(fraction * math.sqrt(length_sq), max(4, primitive.radius * 6)) < max(2, primitive.radius * 3.6)
        depth = a[2] + fraction * (b[2] - a[2]) + np.sqrt(np.maximum(0, primitive.radius ** 2 - square)) * world_per_pixel
    elif primitive.kind == "sprite":
        sx = np.clip((xx - points[0, 0]).astype(int), 0, primitive.texture.shape[1] - 1)
        sy = np.clip((yy - points[0, 1]).astype(int), 0, primitive.texture.shape[0] - 1)
        texture = primitive.texture[sy, sx].astype(np.float32) / 255
        mask = texture[:, :, 3] > 0
        depth = np.full(x.shape, points[0, 2])
    else:
        raise ValueError(f"Unknown native scene primitive: {primitive.kind}")
    if not mask.any():
        return None
    ids = ((yy[mask] - ty) * width + xx[mask] - tx).astype(np.int32)
    rgba = np.broadcast_to(np.asarray(primitive.color, np.float32), (len(ids), 4)).copy()
    if primitive.kind == "sphere" and primitive.shaded:
        lighting = np.clip(0.62 + dome[mask] * 0.37 - nx[mask] * 0.15 - ny[mask] * 0.18, 0.4, 1.25)
        rgba[:, :3] = np.clip(rgba[:, :3] * lighting[:, None], 0, 1)
    if primitive.kind == "sphere" and primitive.texture is not None:
        side = primitive.texture.shape[0]
        sx = np.clip(((nx[mask] + 1) * side / 2).astype(int), 0, side - 1)
        sy = np.clip(((ny[mask] + 1) * side / 2).astype(int), 0, side - 1)
        glyph = primitive.texture[sy, sx].astype(np.float32) / 255
        rgba[:, :3] = glyph[:, :3] * glyph[:, 3:4] + rgba[:, :3] * (1 - glyph[:, 3:4])
    if primitive.kind == "sprite":
        rgba = texture[mask]
    return ids, depth[mask].astype(np.float32), rgba


def rasterize(width, height, primitives, *, world_per_pixel=1.0, tile_size=96):
    """Render exact depth intersections, with memory bounded by a scene tile.

    Returns straight RGBA uint8 pixels and visible opaque atom IDs. A partially
    transparent surface does not block picking an otherwise visible atom;
    an opaque surface does. Tiles avoid retaining a full-frame fragment stack.
    """
    width, height = max(1, int(width)), max(1, int(height))
    rgba_image = np.zeros((height, width, 4), np.uint8)
    atom_ids = np.full((height, width), -1, np.int32)
    columns, rows = math.ceil(width / tile_size), math.ceil(height / tile_size)
    bins = [[] for _ in range(columns * rows)]
    for primitive in primitives:
        if primitive.color[3] <= 0:
            continue
        x0, y0, x1, y1 = primitive.bounds
        if x1 < 0 or y1 < 0 or x0 >= width or y0 >= height:
            continue
        for row in range(max(0, int(y0) // tile_size), min(rows - 1, max(0, int(y1)) // tile_size) + 1):
            for column in range(max(0, int(x0) // tile_size), min(columns - 1, max(0, int(x1)) // tile_size) + 1):
                bins[row * columns + column].append(primitive)
    pending = [((column * tile_size, row * tile_size, min(tile_size, width - column * tile_size),
                 min(tile_size, height - row * tile_size)), bins[row * columns + column])
               for row in range(rows) for column in range(columns)]
    while pending:
        tile, items = pending.pop()
        if not items:
            continue
        tx, ty, tw, th = tile
        bounds = np.array([item.bounds for item in items])
        lo = np.maximum(np.floor(bounds[:, :2]), [tx, ty])
        hi = np.minimum(np.ceil(bounds[:, 2:]) + 1, [tx + tw, ty + th])
        candidates = np.prod(np.maximum(0, hi - lo), axis=1).sum()
        # Highly overlapping meshes subdivide further. This keeps fragment
        # allocation bounded without dropping any translucent depth layers.
        if candidates > 200_000 and max(tw, th) > 1:
            xs = [tx, tx + tw // 2, tx + tw] if tw > 1 else [tx, tx + tw]
            ys = [ty, ty + th // 2, ty + th] if th > 1 else [ty, ty + th]
            for y0, y1 in zip(ys[:-1], ys[1:]):
                for x0, x1 in zip(xs[:-1], xs[1:]):
                    relevant = (bounds[:, 0] <= x1) & (bounds[:, 1] <= y1) & (bounds[:, 2] >= x0) & (bounds[:, 3] >= y0)
                    pending.append(((x0, y0, x1 - x0, y1 - y0), [item for item, keep in zip(items, relevant) if keep]))
            continue
        depth = np.full(tw * th, -np.inf, np.float32)
        colors = np.zeros((tw * th, 4), np.float32)
        picks = np.full(tw * th, -1, np.int32)
        for item in items:
            if item.color[3] < 1 or item.kind in ("sprite", "triangle"):
                continue
            fragments = _samples(item, tile, world_per_pixel)
            if fragments is None:
                continue
            ids, z, rgba = fragments
            visible = z > depth[ids]
            ids = ids[visible]
            depth[ids], colors[ids], picks[ids] = z[visible], rgba[visible], item.atom
        opaque_mesh = _triangle_samples([item for item in items if item.kind == "triangle" and item.color[3] >= 1], tile)
        if opaque_mesh is not None:
            ids, z, rgba = opaque_mesh
            visible = z > depth[ids]
            ids, z, rgba = ids[visible], z[visible], rgba[visible]
            np.maximum.at(depth, ids, z)
            nearest = z == depth[ids]
            colors[ids[nearest]], picks[ids[nearest]] = rgba[nearest], -1
        fragments = []
        transparent_mesh = _triangle_samples([item for item in items if item.kind == "triangle" and item.color[3] < 1], tile)
        if transparent_mesh is not None:
            ids, z, rgba = transparent_mesh
            visible = z > depth[ids]
            if visible.any():
                fragments.append((ids[visible], z[visible], rgba[visible]))
        for item in items:
            if item.kind == "triangle" or (item.color[3] >= 1 and item.kind != "sprite"):
                continue
            sampled = _samples(item, tile, world_per_pixel)
            if sampled is not None:
                ids, z, rgba = sampled
                visible = z > depth[ids]
                if visible.any():
                    fragments.append((ids[visible], z[visible], rgba[visible]))
        if fragments:
            ids, z, rgba = (np.concatenate([part[index] for part in fragments]) for index in range(3))
            order = np.lexsort((-z, ids))
            ids, rgba = ids[order], rgba[order]
            starts = np.r_[0, np.flatnonzero(np.diff(ids)) + 1]
            lengths = np.diff(np.r_[starts, len(ids)])
            # Front-to-back alpha weights, reset for each pixel. Log space
            # avoids a Python fragment loop and supports crossing surfaces.
            log_transmission = np.log1p(-np.minimum(rgba[:, 3], 1 - 1e-7)).astype(np.float64)
            prefix = np.cumsum(log_transmission) - log_transmission
            transmission = np.exp(prefix - np.repeat(prefix[starts], lengths))
            weights = rgba[:, 3] * transmission
            rgb = np.add.reduceat(rgba[:, :3] * weights[:, None], starts, axis=0)
            alpha = -np.expm1(np.add.reduceat(log_transmission, starts))
            pixels = ids[starts]
            base = colors[pixels]
            colors[pixels, :3] = rgb + base[:, :3] * (1 - alpha[:, None])
            colors[pixels, 3] = alpha + base[:, 3] * (1 - alpha)
        colors[:, :3] /= np.maximum(colors[:, 3:4], 1e-12)
        rgba_image[ty:ty + th, tx:tx + tw] = np.clip(np.rint(colors.reshape(th, tw, 4) * 255), 0, 255).astype(np.uint8)
        atom_ids[ty:ty + th, tx:tx + tw] = picks.reshape(th, tw)
    return rgba_image, atom_ids
