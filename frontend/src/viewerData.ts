import type { GeometryReport, Vec3 } from './types.ts';

export type ChargeKind = 'partial_charge' | 'formal_charge' | 'ionic_charge' | 'oxidation_state';
export interface ChargeDataset {
  kind: ChargeKind;
  method: string;
  source: string;
  filename: string;
  structureSha256: string;
  values: (number | null)[];
}
export interface VolumeDataset {
  kind: 'density' | 'orbital';
  source: string;
  filename: string;
  units: string;
  cubeText: string;
  min: number;
  max: number;
  suggestedIsovalue: number;
  pointCount: number;
}
export interface ViewerAuxiliaryData {
  charges: Partial<Record<ChargeKind, ChargeDataset>>;
  volume?: VolumeDataset;
}
export interface CubeOptions {
  kind: 'density' | 'orbital';
  source: string;
  units: string;
}

export const MAX_CHARGE_BYTES = 1024 * 1024;
export const MAX_CUBE_BYTES = 32 * 1024 * 1024;
export const MAX_VOLUME_POINTS = 1_000_000;
export const CUBE_POSITION_TOLERANCE_ANGSTROM = 0.01;
// CODATA 2018 Bohr radius; canonical Cube coordinates are passed to 3Dmol in Å.
const BOHR_ANGSTROM = 0.529177210903;
const CHARGE_KINDS: ChargeKind[] = ['partial_charge', 'formal_charge', 'ionic_charge', 'oxidation_state'];
export const DENSITY_UNITS = ['e/bohr^3', 'e/angstrom^3'] as const;
export const ORBITAL_UNITS = ['bohr^-3/2', 'angstrom^-3/2', 'arbitrary'] as const;

// Standard element symbols ordered by atomic number; no ionic charge is inferred.
const ELEMENTS = ('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn '
  + 'Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm '
  + 'Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa '
  + 'U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og').split(' ');
const ATOMIC_NUMBERS = new Map(ELEMENTS.map((symbol, index) => [symbol, index + 1]));

export function atomicNumber(element: string): number | undefined {
  return ATOMIC_NUMBERS.get(element);
}

/** A display category, not evidence that a compound has metallic electronic properties. */
export function isMetalElement(element: string): boolean {
  const z = atomicNumber(element);
  if (!z) return false;
  return [3, 4, 11, 12, 13, 31, 49, 50, 81, 82, 83].includes(z)
    || (z >= 19 && z <= 30) || (z >= 37 && z <= 48)
    || (z >= 55 && z <= 80) || (z >= 87 && z <= 112);
}

function requireValue(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function boundedText(text: string, maximum: number, label: string): void {
  requireValue(typeof text === 'string' && text.length <= maximum
    && new TextEncoder().encode(text).byteLength <= maximum,
  `${label}: file exceeds the ${maximum / 1024 / 1024} MiB limit.`);
}

function metadata(value: unknown, label: string): string {
  requireValue(typeof value === 'string' && value.trim().length > 0 && value.length <= 500,
    `${label} is required and must be at most 500 characters.`);
  return value.trim();
}

function object(value: unknown, label: string): Record<string, unknown> {
  requireValue(value !== null && typeof value === 'object' && !Array.isArray(value),
    `${label} must be an object.`);
  return value as Record<string, unknown>;
}

function validReport(report: GeometryReport): void {
  requireValue(Number.isInteger(report.atom_count) && report.atom_count >= 1 && report.atom_count <= 400
    && report.elements.length === report.atom_count && report.positions.length === report.atom_count,
  'The structure report has an invalid atom count.');
  requireValue(report.positions.every((position) => position.length === 3
    && position.every(Number.isFinite)) && report.elements.every((element) => atomicNumber(element)),
  'The structure report has invalid coordinates or elements.');
}

function validSha256(value: unknown): value is string {
  return typeof value === 'string' && /^[0-9a-f]{64}$/i.test(value);
}

export function parseChargeData(
  text: string, report: GeometryReport, structureSha256: string, filename: string,
): ChargeDataset {
  boundedText(text, MAX_CHARGE_BYTES, 'Charge data');
  validReport(report);
  let parsed: unknown;
  try { parsed = JSON.parse(text); }
  catch { throw new Error('Charge data must be valid JSON with finite numeric values or null.'); }
  // JSON.parse silently rounds tiny nonzero literals to zero. Scan validated
  // JSON tokens while consuming complete strings, including escaped quotes.
  for (const match of text.matchAll(/"(?:\\.|[^"\\])*"|(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/g)) {
    if (match[1] !== undefined) numberToken(match[1], 'Charge data');
  }
  const input = object(parsed, 'Charge data');
  requireValue(input.schema_version === 1, 'Unsupported charge-data schema_version; expected 1.');
  requireValue(validSha256(structureSha256) && validSha256(input.structure_sha256)
    && input.structure_sha256.toLowerCase() === structureSha256.toLowerCase(),
  'Charge data does not match the original CIF SHA-256. Download a template for this structure.');
  requireValue(CHARGE_KINDS.includes(input.kind as ChargeKind),
    'Charge kind must be partial_charge, formal_charge, ionic_charge or oxidation_state.');
  const kind = input.kind as ChargeKind;
  const method = metadata(input.method, 'Calculation or assignment method');
  const source = metadata(input.source, 'Data source');
  requireValue(Array.isArray(input.atoms) && input.atoms.length === report.atom_count,
    `Charge data must include all ${report.atom_count} original atom indices; use null for unknown values.`);
  const values: (number | null)[] = Array(report.atom_count).fill(null);
  const seen = new Set<number>();
  for (const raw of input.atoms) {
    const atom = object(raw, 'Charge atom');
    const index = atom.index;
    requireValue(typeof index === 'number' && Number.isInteger(index)
      && index >= 1 && index <= report.atom_count && !seen.has(index),
    'Charge atom indices must include each 1-based original index exactly once.');
    requireValue(atom.element === report.elements[index - 1],
      `Charge atom ${index} has a different element from the CIF.`);
    const value = atom.value;
    requireValue(value === null || (typeof value === 'number'
      && Number.isFinite(value) && Number.isFinite(Math.fround(value))),
    `Charge atom ${index} needs a finite number or null, not a string or missing value.`);
    requireValue(!['formal_charge', 'ionic_charge'].includes(kind) || value === null || Number.isInteger(value),
      'Formal charges and ionic net charges must be integers; use partial_charge for fractional atomic charges.');
    seen.add(index);
    values[index - 1] = value as number | null;
  }
  return { kind, method, source, filename: metadata(filename, 'Filename'),
    structureSha256: structureSha256.toLowerCase(), values };
}

export function makeChargeTemplate(
  report: GeometryReport, structureSha256: string, kind: ChargeKind = 'partial_charge',
): string {
  validReport(report);
  requireValue(validSha256(structureSha256), 'A valid original CIF SHA-256 is required.');
  requireValue(CHARGE_KINDS.includes(kind), 'Unsupported charge kind.');
  return JSON.stringify({
    schema_version: 1, structure_sha256: structureSha256.toLowerCase(), kind,
    method: '', source: '',
    atoms: report.elements.map((element, index) => ({ index: index + 1, element, value: null })),
  }, null, 2);
}

const NUMBER_TOKEN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?$/;
function numberToken(token: string | undefined, label: string): number {
  requireValue(token !== undefined && NUMBER_TOKEN.test(token), `${label}: invalid numeric value.`);
  const value = Number(token.replace(/[dD]/, 'e'));
  requireValue(Number.isFinite(value), `${label}: numeric values must be finite.`);
  requireValue(value !== 0 || !/[1-9]/.test(token.split(/[eEdD]/, 1)[0]),
    `${label}: a nonzero numeric value is too small to represent.`);
  return value;
}

function integerToken(token: string | undefined, label: string): number {
  requireValue(token !== undefined && /^[+-]?\d+$/.test(token), `${label} must be an integer.`);
  const value = Number(token);
  requireValue(Number.isSafeInteger(value), `${label} exceeds the supported integer range.`);
  return value;
}

function row(lines: string[], index: number, lengths: number[], label: string): string[] {
  const tokens = lines[index]?.trim().split(/\s+/) ?? [];
  requireValue(lengths.includes(tokens.length), `${label}: unexpected or missing fields.`);
  return tokens;
}

function vector(tokens: string[], factor: number, label: string): Vec3 {
  return tokens.map((token) => {
    const value = numberToken(token, label) * factor;
    requireValue(Math.abs(value) <= 1_000_000, `${label}: coordinates must be within ±1,000,000 Å.`);
    return value;
  }) as Vec3;
}

function nondegenerateGrid(vectors: Vec3[]): boolean {
  const [a, b, c] = vectors;
  const determinant = a[0] * (b[1] * c[2] - b[2] * c[1])
    - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0]);
  const lengths = vectors.map((v) => Math.hypot(...v));
  return lengths.every((length) => length >= 1e-8)
    && Math.abs(determinant) / lengths.reduce((product, length) => product * length, 1) > 1e-8;
}

/** Validate a bounded scalar Cube, then normalize only its spatial coordinates to Å. */
export function parseCubeData(
  text: string, report: GeometryReport, options: CubeOptions, filename: string,
): VolumeDataset {
  boundedText(text, MAX_CUBE_BYTES, 'Cube data');
  validReport(report);
  requireValue(options.kind === 'density' || options.kind === 'orbital',
    'Select whether the Cube contains electron density or one orbital.');
  const units = options.units;
  const allowedUnits: readonly string[] = options.kind === 'density' ? DENSITY_UNITS : ORBITAL_UNITS;
  requireValue(allowedUnits.includes(units),
    `Select explicit ${options.kind} scalar units: ${allowedUnits.join(', ')}.`);
  const source = metadata(options.source, 'Volume data source');
  const lines = text.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n').split('\n');
  requireValue(lines.length >= 7, 'Cube data needs two comment lines, a grid and atom records.');
  const header = row(lines, 2, [4, 5], 'Cube origin header');
  const signedAtomCount = integerToken(header[0], 'Cube atom count');
  const atomCount = Math.abs(signedAtomCount);
  requireValue(atomCount === report.atom_count, 'Cube atom count does not match the original CIF.');
  if (header.length === 5) requireValue(integerToken(header[4], 'Cube values per voxel') === 1,
    'Only one scalar dataset per Cube is supported; export one density or orbital.');
  const axes = [3, 4, 5].map((index) => row(lines, index, [4], 'Cube grid axis'));
  const signedCounts = axes.map((axis) => integerToken(axis[0], 'Cube grid count'));
  requireValue(signedCounts.every((count) => count > 0) || signedCounts.every((count) => count < 0),
    'Cube grid counts must have one consistent sign: positive for Bohr or negative for Å.');
  const counts = signedCounts.map(Math.abs);
  const pointCount = counts.reduce((product, count) => product * count, 1);
  requireValue(counts.every((count) => count >= 2)
    && Number.isSafeInteger(pointCount) && pointCount <= MAX_VOLUME_POINTS,
  `Cube grids need at least two points per axis and at most ${MAX_VOLUME_POINTS.toLocaleString('en-US')} total points.`);
  const factor = signedCounts[0] > 0 ? BOHR_ANGSTROM : 1;
  const origin = vector(header.slice(1, 4), factor, 'Cube origin');
  const vectors = axes.map((axis) => vector(axis.slice(1), factor, 'Cube grid vector'));
  requireValue(nondegenerateGrid(vectors),
    'Cube grid vectors must define a nondegenerate three-dimensional grid.');
  // 3Dmol stores the skew-grid transform in a Float32Array. A valid double-
  // precision basis can collapse when rounded to that rendering precision.
  requireValue(nondegenerateGrid(vectors.map((v) => v.map(Math.fround) as Vec3)),
    'Cube grid becomes degenerate at the viewer\'s float32 precision.');
  requireValue([0, 1, 2].every((component) => {
    const extents = vectors.map((v, axis) => v[component] * (counts[axis] - 1));
    const minimum = origin[component] + extents.reduce((sum, value) => sum + Math.min(0, value), 0);
    const maximum = origin[component] + extents.reduce((sum, value) => sum + Math.max(0, value), 0);
    return minimum >= -1_000_000 && maximum <= 1_000_000;
  }),
  'Cube grid extent exceeds the supported coordinate range.');

  const atomRows: string[] = [];
  for (let index = 0; index < atomCount; index += 1) {
    const atom = row(lines, 6 + index, [5], `Cube atom ${index + 1}`);
    const z = integerToken(atom[0], 'Cube atomic number');
    requireValue(z === atomicNumber(report.elements[index]),
      `Cube atom ${index + 1} has a different element or atom order from the CIF.`);
    const nuclearCharge = numberToken(atom[1], 'Cube nuclear charge');
    const position = vector(atom.slice(2), factor, 'Cube atom position');
    const difference = position.map((value, axis) => value - report.positions[index][axis]);
    requireValue(Math.hypot(...difference) <= CUBE_POSITION_TOLERANCE_ANGSTROM,
      `Cube atom ${index + 1} is not aligned with the CIF (tolerance ${CUBE_POSITION_TOLERANCE_ANGSTROM} Å). No rotation or wrapping is inferred.`);
    atomRows.push([z, nuclearCharge, ...position].join(' '));
  }
  const rawValues = lines.slice(6 + atomCount).join(' ').trim();
  const tokens = rawValues ? rawValues.split(/\s+/) : [];
  let offset = 0;
  if (signedAtomCount < 0) {
    requireValue(integerToken(tokens[0], 'Cube dataset count') === 1,
      'Multi-orbital Cube files are not supported; export a single orbital.');
    requireValue(integerToken(tokens[1], 'Cube dataset identifier') >= 0,
      'Cube dataset identifier must be nonnegative.');
    offset = 2;
  }
  requireValue(tokens.length - offset === pointCount,
    `Cube needs exactly ${pointCount} scalar values; found ${tokens.length - offset}.`);
  let min = Infinity;
  let max = -Infinity;
  const values: string[] = [];
  for (let index = offset; index < tokens.length; index += 1) {
    const value = numberToken(tokens[index], `Cube scalar ${index - offset + 1}`);
    requireValue(Number.isFinite(Math.fround(value)) && (value === 0 || Math.fround(value) !== 0),
      'Cube scalar is outside the supported float32 display range.');
    requireValue(options.kind !== 'density' || value >= 0,
      'Electron density must be nonnegative. Signed orbital, spin-density or difference-density data is not total electron density.');
    min = Math.min(min, value); max = Math.max(max, value);
    values.push(String(value));
  }
  const extent = Math.max(Math.abs(min), Math.abs(max));
  // This is a starting display threshold, not a recommended physical cutoff.
  const suggestedIsovalue = extent > 0 ? extent * 0.15 : 0.01;
  const scalarLines: string[] = [];
  for (let index = 0; index < values.length; index += 6) scalarLines.push(values.slice(index, index + 6).join(' '));
  // 3Dmol 2.5.5 interprets negative voxel counts as Å. Positive NATOMS removes
  // the optional orbital-ID header; scalar order and values are unchanged.
  const cubeText = [
    'CalcLens validated display volume', `${options.kind}; scalar units ${units}; coordinates angstrom`,
    [atomCount, ...origin].join(' '),
    ...vectors.map((v, axis) => [-counts[axis], ...v].join(' ')),
    ...atomRows, ...scalarLines,
  ].join('\n');
  return { kind: options.kind, source, filename: metadata(filename, 'Filename'), units,
    cubeText, min, max, suggestedIsovalue, pointCount };
}
