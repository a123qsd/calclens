import assert from 'node:assert/strict';
import test from 'node:test';
import type { Contact, GeometryReport, Vec3 } from './types.ts';
import {
  buildDisplayAtoms, cellCorners, contactEndpoints, inferDisplayBonds,
  gapBoundary, gapFractions, latticeTranslation, markAtomIndices, normalViewQuaternion,
  repeatShifts, withContactEndpoints,
} from './viewerGeometry.ts';

function report(cell: Vec3[] = [[2, 0, 0], [0.5, 3, 0], [0, 0, 10]]): GeometryReport {
  const contact: Contact = { i: 0, j: 1, element_i: 'C', element_j: 'C', shift: [0, 0, 0], distance_angstrom: 1.4, is_self_image: false };
  return {
    schema_version: '1.1', formula: 'C2', atom_count: 2, elements: ['C', 'C'],
    cell, positions: [[0, 0, 0], [1.4, 0, 0]], scaled_positions: [[0, 0, 0], [0.7, 0, 0]],
    periodic_axes: [true, true, true], normal_axis: 'c', normal_axis_index: 2,
    in_plane_axes: ['a', 'b'], review_required: false, gap_review_required: false,
    metrics: { minimum_distance_angstrom: 1.4, minimum_pair: contact, c_height_angstrom: 10,
      normal_height_angstrom: 10, nuclei_thickness_angstrom: 0, nuclei_gap_angstrom: 10,
      gap_fraction: 1, gap_start_fraction: 0, gap_end_fraction: 1, second_largest_gap_angstrom: 0 },
    short_distance_threshold_angstrom: 1, short_contacts: [], short_contact_count: 0,
    short_contacts_truncated: false, issues: [], assumptions: [], limitations: [],
  };
}

test('repeat shifts preserve original indices and integer image shifts', () => {
  assert.deepEqual(repeatShifts(2, 1), [[0, 0, 0]]);
  assert.equal(repeatShifts(2, 2).length, 4);
  assert.equal(repeatShifts(2, 3).length, 9);
  const atoms = buildDisplayAtoms(report(), 3);
  assert.equal(atoms.length, 18);
  assert.deepEqual(atoms[0].shift, [-1, -1, 0]);
  assert.equal(atoms[0].index, 0);
  assert.equal(atoms[17].index, 1);
});

test('triclinic lattice shifts use cell row vectors', () => {
  assert.deepEqual(latticeTranslation(report().cell, [2, -1, 1]), [3.5, -3, 10]);
});

test('contact endpoints honor explicit start and end images', () => {
  const data = report();
  const contact: Contact = { i: 0, j: 0, element_i: 'C', element_j: 'C', shift: [1, -1, 0],
    start_shift: [-1, 0, 0], end_shift: [1, -1, 0], distance_angstrom: 1, is_self_image: true };
  assert.deepEqual(contactEndpoints(data, contact), { start: [-2, 0, 0], end: [1.5, -3, 0] });
  const atoms = withContactEndpoints(buildDisplayAtoms(data, 1), data, contact);
  assert.equal(atoms.filter((atom) => atom.highlight).length, 2);
  assert.equal(atoms.length, 4);
});

test('display bonds follow covalent distances and respect the hard cap', () => {
  const data = report();
  const atoms = buildDisplayAtoms(data, 1);
  assert.deepEqual(inferDisplayBonds(atoms), [{ a: 0, b: 1 }]);
  const many = Array.from({ length: 50 }, (_, index) => ({
    displayIndex: index, index, element: 'C', shift: [0, 0, 0] as Vec3,
    position: [index * 0.8, 0, 0] as Vec3, highlight: false,
  }));
  assert.equal(inferDisplayBonds(many, 7).length, 7);
});

test('cell corners contain the eight triclinic vertices', () => {
  assert.equal(cellCorners(report().cell).length, 8);
  assert.deepEqual(cellCorners(report().cell).at(-1), [2.5, 3, 10]);
});

test('gap boundary follows the selected normal axis in fractional coordinates', () => {
  const data = report();
  assert.deepEqual(gapBoundary(data, 0.25), [[0, 0, 2.5], [2, 0, 2.5], [2.5, 3, 2.5], [0.5, 3, 2.5]]);
  const marked = markAtomIndices(buildDisplayAtoms(data, 2), [1]);
  assert.equal(marked.filter((atom) => atom.highlight).length, 4);
});

test('cyclic gap endpoints unwrap across the cell boundary', () => {
  const data = report();
  data.metrics.gap_start_fraction = 0.5;
  data.metrics.gap_end_fraction = 0.5;
  assert.deepEqual(gapFractions(data), [0.5, 1.5]);
  data.metrics.gap_fraction = 0.8;
  assert.deepEqual(gapFractions(data), [0.5, 1.3]);
});

test('normal camera rotation maps each lattice-plane normal onto z', () => {
  for (const axis of [0, 1, 2]) {
    const data = report([[2, 0, 0], [0, 3, 0], [0, 0, 10]]);
    data.normal_axis_index = axis;
    const [x, y, z, w] = normalViewQuaternion(data);
    const n = [0, 0, 0]; n[axis] = axis === 1 ? -1 : 1;
    const resultZ = 2 * (x * z - y * w) * n[0]
      + 2 * (y * z + x * w) * n[1] + (1 - 2 * (x * x + y * y)) * n[2];
    assert.ok(Math.abs(resultZ - 1) < 1e-12);
  }
});

test('unknown element radii do not invent display bonds', () => {
  const data = report(); data.elements = ['Xx', 'C'];
  assert.deepEqual(inferDisplayBonds(buildDisplayAtoms(data, 1)), []);
});

test('400-site 3x3 display remains bounded by the stick cap', () => {
  const data = report([[32, 0, 0], [0, 32, 0], [0, 0, 12]]);
  data.positions = Array.from({ length: 400 }, (_, index) => [
    (index % 20) * 1.55, Math.floor(index / 20) * 1.55, 0,
  ] as Vec3);
  data.elements = Array.from({ length: 400 }, () => 'C');
  data.atom_count = 400;
  const atoms = buildDisplayAtoms(data, 3);
  assert.equal(atoms.length, 3_600);
  assert.ok(inferDisplayBonds(atoms).length <= 8_000);
});
