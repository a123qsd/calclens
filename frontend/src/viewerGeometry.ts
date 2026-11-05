import type { Contact, GeometryReport, Vec3 } from './types';

export interface DisplayAtom {
  displayIndex: number;
  index: number;
  element: string;
  shift: Vec3;
  position: Vec3;
  highlight: boolean;
}

export interface DisplayBond { a: number; b: number }
export interface LineSegment { start: Vec3; end: Vec3 }

// Covalent radii in Å: Cordero et al. (2008), DOI:10.1039/B801115J,
// as tabulated in ASE's ase.data.covalent_radii. Used only for display sticks.
const COVALENT_RADII: Record<string, number> = {
  H: 0.31, He: 0.28, Li: 1.28, Be: 0.96, B: 0.84, C: 0.76, N: 0.71,
  O: 0.66, F: 0.57, Ne: 0.58, Na: 1.66, Mg: 1.41, Al: 1.21, Si: 1.11,
  P: 1.07, S: 1.05, Cl: 1.02, Ar: 1.06, K: 2.03, Ca: 1.76, Sc: 1.70,
  Ti: 1.60, V: 1.53, Cr: 1.39, Mn: 1.39, Fe: 1.32, Co: 1.26, Ni: 1.24,
  Cu: 1.32, Zn: 1.22, Ga: 1.22, Ge: 1.20, As: 1.19, Se: 1.20, Br: 1.20,
  Kr: 1.16, Rb: 2.20, Sr: 1.95, Y: 1.90, Zr: 1.75, Nb: 1.64, Mo: 1.54,
  Ru: 1.46, Rh: 1.42, Pd: 1.39, Ag: 1.45, Cd: 1.44, In: 1.42, Sn: 1.39,
  Sb: 1.39, Te: 1.38, I: 1.39, Xe: 1.40, Cs: 2.44, Ba: 2.15, W: 1.62, Pt: 1.36,
  Au: 1.36, Hg: 1.32, Pb: 1.46,
};

const CELL_SIZE = 2.8;

function plus(a: Vec3, b: Vec3): Vec3 {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

export function latticeTranslation(cell: Vec3[], shift: Vec3): Vec3 {
  return [0, 1, 2].map((component) => (
    shift[0] * cell[0][component]
    + shift[1] * cell[1][component]
    + shift[2] * cell[2][component]
  )) as Vec3;
}

export function shiftedPosition(position: Vec3, cell: Vec3[], shift: Vec3): Vec3 {
  return plus(position, latticeTranslation(cell, shift));
}

export function repeatShifts(normalAxisIndex: number, repeat: 1 | 2 | 3): Vec3[] {
  const values = repeat === 1 ? [0] : repeat === 2 ? [0, 1] : [-1, 0, 1];
  const inPlane = [0, 1, 2].filter((axis) => axis !== normalAxisIndex);
  const shifts: Vec3[] = [];
  for (const first of values) {
    for (const second of values) {
      const shift: Vec3 = [0, 0, 0];
      shift[inPlane[0]] = first;
      shift[inPlane[1]] = second;
      shifts.push(shift);
    }
  }
  return shifts;
}

export function buildDisplayAtoms(report: GeometryReport, repeat: 1 | 2 | 3): DisplayAtom[] {
  const atoms: DisplayAtom[] = [];
  for (const shift of repeatShifts(report.normal_axis_index, repeat)) {
    report.positions.forEach((position, index) => atoms.push({
      displayIndex: atoms.length,
      index,
      element: report.elements[index],
      shift,
      position: shiftedPosition(position, report.cell, shift),
      highlight: false,
    }));
  }
  return atoms;
}

export function contactEndpoints(report: GeometryReport, contact: Contact): LineSegment {
  const startShift = contact.start_shift ?? [0, 0, 0];
  const endShift = contact.end_shift ?? contact.shift;
  return {
    start: shiftedPosition(report.positions[contact.i], report.cell, startShift),
    end: shiftedPosition(report.positions[contact.j], report.cell, endShift),
  };
}

function samePoint(a: Vec3, b: Vec3): boolean {
  const dx = a[0] - b[0];
  const dy = a[1] - b[1];
  const dz = a[2] - b[2];
  return dx * dx + dy * dy + dz * dz < 1e-10;
}

export function withContactEndpoints(
  atoms: DisplayAtom[], report: GeometryReport, contact?: Contact | null,
): DisplayAtom[] {
  if (!contact) return atoms;
  const output = atoms.map((atom) => ({ ...atom }));
  const shifts: [number, Vec3][] = [
    [contact.i, contact.start_shift ?? [0, 0, 0]],
    [contact.j, contact.end_shift ?? contact.shift],
  ];
  for (const [index, shift] of shifts) {
    const position = shiftedPosition(report.positions[index], report.cell, shift);
    const existing = output.find((atom) => atom.index === index && samePoint(atom.position, position));
    if (existing) {
      existing.highlight = true;
    } else {
      output.push({
        displayIndex: output.length,
        index,
        element: report.elements[index],
        shift,
        position,
        highlight: true,
      });
    }
  }
  output.forEach((atom, index) => { atom.displayIndex = index; });
  return output;
}

export function markAtomIndices(atoms: DisplayAtom[], indices?: number[]): DisplayAtom[] {
  if (!indices?.length) return atoms;
  const selected = new Set(indices);
  return atoms.map((atom) => selected.has(atom.index) ? { ...atom, highlight: true } : atom);
}

export function gapBoundary(report: GeometryReport, fraction: number): Vec3[] {
  const normal = report.cell[report.normal_axis_index];
  const inPlane = [0, 1, 2].filter((axis) => axis !== report.normal_axis_index);
  const origin: Vec3 = [normal[0] * fraction, normal[1] * fraction, normal[2] * fraction];
  const first = report.cell[inPlane[0]];
  const second = report.cell[inPlane[1]];
  return [origin, plus(origin, first), plus(plus(origin, first), second), plus(origin, second)];
}

export function gapFractions(report: GeometryReport): [number, number] {
  const start = report.metrics.gap_start_fraction;
  return [start, start + report.metrics.gap_fraction];
}

/** Rotate the in-plane normal onto the camera axis, including a/b-normal CIFs. */
export function normalViewQuaternion(report: GeometryReport): [number, number, number, number] {
  const plane = report.cell.filter((_, axis) => axis !== report.normal_axis_index);
  const [a, b] = plane;
  const normal = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0]];
  const length = Math.hypot(...normal);
  const [x, y, z] = normal.map((value) => value / length);
  if (z < -0.999999) return [1, 0, 0, 0];
  const norm = Math.hypot(y, -x, 1 + z);
  return [y / norm, -x / norm, 0, (1 + z) / norm];
}

function binKey(position: Vec3): string {
  return position.map((value) => Math.floor(value / CELL_SIZE)).join(',');
}

function radius(element: string): number {
  return COVALENT_RADII[element] ?? 0;
}

/** Infer strictly display-only sticks, with a hard cap for pathological cells. */
export function inferDisplayBonds(atoms: DisplayAtom[], maxBonds = 8_000): DisplayBond[] {
  if (maxBonds <= 0) return [];
  const bins = new Map<string, number[]>();
  const bonds: DisplayBond[] = [];
  const offsets = [-1, 0, 1];
  for (let index = 0; index < atoms.length; index += 1) {
    const atom = atoms[index];
    if (!radius(atom.element)) continue;
    const cell = atom.position.map((value) => Math.floor(value / CELL_SIZE));
    for (const dx of offsets) for (const dy of offsets) for (const dz of offsets) {
      const neighbours = bins.get(`${cell[0] + dx},${cell[1] + dy},${cell[2] + dz}`) ?? [];
      for (const otherIndex of neighbours) {
        const other = atoms[otherIndex];
        const x = atom.position[0] - other.position[0];
        const y = atom.position[1] - other.position[1];
        const z = atom.position[2] - other.position[2];
        const distanceSquared = x * x + y * y + z * z;
        // Long metallic/ionic separations should not become molecule-like sticks.
        const limit = Math.min(2.6, 1.18 * (radius(atom.element) + radius(other.element)));
        if (distanceSquared > 0.16 && distanceSquared <= limit * limit) {
          bonds.push({ a: otherIndex, b: index });
          if (bonds.length >= maxBonds) return bonds;
        }
      }
    }
    const key = binKey(atom.position);
    const entries = bins.get(key);
    if (entries) entries.push(index); else bins.set(key, [index]);
  }
  return bonds;
}

export function cellEdges(cell: Vec3[]): LineSegment[] {
  const origin: Vec3 = [0, 0, 0];
  const a = cell[0]; const b = cell[1]; const c = cell[2];
  const ab = plus(a, b); const ac = plus(a, c); const bc = plus(b, c);
  const abc = plus(ab, c);
  return [
    [origin, a], [origin, b], [origin, c], [a, ab], [a, ac], [b, ab],
    [b, bc], [c, ac], [c, bc], [ab, abc], [ac, abc], [bc, abc],
  ].map(([start, end]) => ({ start, end }));
}

export function cellCorners(cell: Vec3[]): Vec3[] {
  const edges = cellEdges(cell);
  const unique: Vec3[] = [];
  for (const edge of edges) for (const point of [edge.start, edge.end]) {
    if (!unique.some((candidate) => samePoint(candidate, point))) unique.push(point);
  }
  return unique;
}
