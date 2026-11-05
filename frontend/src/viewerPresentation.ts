import type { DisplayAtom } from './viewerGeometry.ts';

export type Representation = 'ball-stick' | 'stick' | 'spacefill';
export type Quality = 'light' | 'balanced' | 'high';
export type ColorMode = 'element' | 'metal' | 'ionic_charge' | 'formal_charge' | 'partial_charge' | 'oxidation_state';
export const LABEL_LIMIT = 180;
export const BOND_LIMIT = 8_000;
export const UNKNOWN_COLOR = '#969CA5';

const ELEMENT_COLORS: Record<string, string> = {
  H: '#DCE2E8', He: '#A1DAD8', Li: '#B898CD', Be: '#92B970', B: '#C89178',
  C: '#607183', N: '#4675C8', O: '#D85858', F: '#69B59A', Ne: '#91CFD0',
  Na: '#A381C6', Mg: '#80B56F', Al: '#A8B3C0', Si: '#BD976F', P: '#E69A45',
  S: '#D8B84B', Cl: '#69A96F', Ar: '#84BEC8', K: '#9675BD', Ca: '#87A969',
  Ti: '#8F9FAC', V: '#899C9D', Cr: '#7C9DA9', Mn: '#AA87AC', Fe: '#AC8066',
  Co: '#8B81B7', Ni: '#6BA38F', Cu: '#BF8157', Zn: '#8E9FAA', Ga: '#C18D96',
  Ge: '#8E9CAA', As: '#A082B1', Se: '#B89049', Br: '#A75C58', Kr: '#79ABB8',
  Mo: '#5C9C9E', W: '#487F91', Ag: '#A3AFB8', Cd: '#B9A87B', Sn: '#899CAB',
  I: '#8666AC', Pt: '#A4A7A0', Au: '#C4A14D', Hg: '#95A1AE', Pb: '#718499',
};

export function elementColor(element: string): string {
  if (ELEMENT_COLORS[element]) return ELEMENT_COLORS[element];
  // A deterministic fallback keeps less common elements consistent with their legend.
  const palette = ['#8E9CB9', '#AA8799', '#78A8A0', '#B5A278', '#8D9F76', '#A18BBD'];
  return palette[[...element].reduce((sum, char) => sum + char.charCodeAt(0), 0) % palette.length];
}

export function chargeColor(value: number | null | undefined, extent: number): string {
  if (value == null || !Number.isFinite(value)) return UNKNOWN_COLOR;
  const amount = Math.min(1, Math.abs(value) / (extent > 0 ? extent : 1));
  const endpoint = value < 0 ? [198, 67, 79] : [51, 104, 192];
  const neutral = [232, 235, 240];
  return `#${neutral.map((component, index) => Math.round(
    component + amount * (endpoint[index] - component),
  ).toString(16).padStart(2, '0')).join('')}`;
}

export function repeatDimensions(normalAxis: number, repeat: number): number[] {
  return [0, 1, 2].map((axis) => axis === normalAxis ? 1 : repeat);
}

export function labelAtoms(atoms: DisplayAtom[], pickedIndex?: number, limit = LABEL_LIMIT): DisplayAtom[] {
  const prioritized = [
    ...atoms.filter((atom) => atom.index === pickedIndex),
    ...atoms.filter((atom) => atom.index !== pickedIndex && atom.highlight),
  ];
  const selected = new Set(prioritized.map((atom) => atom.displayIndex));
  return [...prioritized, ...atoms.filter((atom) => !selected.has(atom.displayIndex))].slice(0, limit);
}

export function exportDimensions(width: number, height: number, longestEdge: number) {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error('The viewer needs a visible area before exporting.');
  }
  const scale = Math.min(3200, Math.max(800, longestEdge)) / Math.max(width, height);
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

/** Bound marching-cubes work before allocating meshes; do not downsample scientific data. */
export function assertSurfaceBudget(
  values: Float32Array, size: { x: number; y: number; z: number }, levels: number[], limit = 25_000,
): void {
  const { x: nx, y: ny, z: nz } = size;
  const offsets = [0, 1, nz, nz + 1, ny * nz, ny * nz + 1, (ny + 1) * nz, (ny + 1) * nz + 1];
  let intersected = 0;
  for (let x = 0; x < nx - 1; x += 1) for (let y = 0; y < ny - 1; y += 1) for (let z = 0; z < nz - 1; z += 1) {
    const base = (x * ny + y) * nz + z;
    let low = Infinity; let high = -Infinity;
    for (const offset of offsets) { low = Math.min(low, values[base + offset]); high = Math.max(high, values[base + offset]); }
    if (low === high) continue;
    for (const level of levels) {
      if (low <= level && high >= level) intersected += 1;
      if (intersected > limit) throw new Error(`Surface exceeds the ${limit.toLocaleString('en-US')}-cell complexity limit. Choose another isovalue or prepare a smaller grid; no data was omitted.`);
    }
  }
}
