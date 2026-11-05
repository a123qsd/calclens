import assert from 'node:assert/strict';
import test from 'node:test';
import type { GeometryReport, Vec3 } from './types.ts';
import {
  atomicNumber, isMetalElement, makeChargeTemplate, parseChargeData, parseCubeData,
  appendAuxiliaryDataset, assertAuxiliaryLimits, auxiliaryByteSize, serializeAuxiliaryData, restoreAuxiliaryData,
  MAX_CHARGE_BYTES, MAX_CUBE_BYTES, MAX_VOLUME_POINTS, MAX_AUXILIARY_DATASETS,
} from './viewerData.ts';

const sha = 'a'.repeat(64);
function report(positions: Vec3[] = [[0, 0, 0], [1, 0, 0]]): GeometryReport {
  return { atom_count: 2, elements: ['C', 'H'], positions } as GeometryReport;
}
function charges() {
  return { schema_version: 1, structure_sha256: sha, kind: 'partial_charge',
    method: 'Hirshfeld', source: 'example calculation',
    atoms: [{ index: 1, element: 'C', value: null }, { index: 2, element: 'H', value: 0 }] };
}
function parseCharge(value: unknown) {
  return parseChargeData(JSON.stringify(value), report(), sha, 'charge.json');
}
function cube(options: { bohr?: boolean; orbital?: boolean; values?: string; skew?: boolean } = {}) {
  const c = options.bohr ? 1 / 0.529177210903 : 1;
  const n = options.bohr ? 2 : -2;
  return ['Test cube', 'Synthetic parser fixture, not a calculated electronic structure',
    `${options.orbital ? -2 : 2} ${-c} 0 0`, `${n} ${c} 0 0`,
    `${n} ${options.skew ? c / 2 : 0} ${c} 0`, `${n} 0 0 ${c}`,
    '6 6.0 0 0 0', `1 1.0 ${c} 0 0`, ...(options.orbital ? ['1 7'] : []),
    options.values ?? '0.0 0.1 0.2 0.3 0.4 0.5 0.6 0.7'].join('\n');
}
const density = { kind: 'density' as const, source: 'Synthetic test fixture', units: 'e/bohr^3' };
const orbital = { kind: 'orbital' as const, source: 'Synthetic test fixture', units: 'bohr^-3/2' };

test('charge template leaves all values unknown and binds the exact source bytes', () => {
  const template = JSON.parse(makeChargeTemplate(report(), sha));
  assert.equal(template.structure_sha256, sha);
  assert.deepEqual(template.atoms, [
    { index: 1, element: 'C', value: null }, { index: 2, element: 'H', value: null },
  ]);
});

test('imported unknown charge and an actual zero remain distinct', () => {
  assert.deepEqual(parseCharge(charges()).values, [null, 0]);
  const data = charges(); data.atoms.reverse();
  assert.deepEqual(parseCharge(data).values, [null, 0]);
});

test('tiny nonzero charge tokens cannot silently become zero', () => {
  const json = JSON.stringify(charges());
  for (const token of ['1e-1000', '-1e-1000']) {
    assert.throws(() => parseChargeData(json.replace('"value":0', `"value":${token}`), report(), sha, 'tiny.json'));
  }
  const valid = json.replace('"value":0', '"value":0e-1000')
    .replace('example calculation', 'Example \\"1e-1000\\" text');
  assert.equal(parseChargeData(valid, report(), sha, 'zero.json').values[1], 0);
});

test('tiny nonzero Cube tokens cannot silently become zero or evade density sign checks', () => {
  for (const token of ['1e-1000', '-1D-1000']) {
    assert.throws(() => parseCubeData(cube({ values: `0 0 0 0 0 0 0 ${token}` }), report(), density, 'tiny.cube'));
  }
  assert.equal(parseCubeData(cube({ values: '0 0 0 0 0 0 0 0D-1000' }), report(), density, 'zero.cube').max, 0);
});

test('charge imports preserve scientific kind, method and source', () => {
  for (const kind of ['partial_charge', 'formal_charge', 'ionic_charge', 'oxidation_state']) {
    const data = parseCharge({ ...charges(), kind });
    assert.equal(data.kind, kind);
    assert.equal(data.method, 'Hirshfeld');
    assert.equal(data.source, 'example calculation');
    assert.equal(data.filename, 'charge.json');
  }
});

test('charge import rejects wrong or missing identity and unsupported schema', () => {
  for (const patch of [
    { structure_sha256: 'b'.repeat(64) }, { structure_sha256: null },
    { schema_version: 2 }, { kind: 'nuclear_charge' }, { method: '' }, { source: '' },
  ]) assert.throws(() => parseCharge({ ...charges(), ...patch }));
});

test('charge atoms require complete unique indices and matching elements', () => {
  const data = charges();
  for (const atoms of [
    data.atoms.slice(0, 1), [...data.atoms, data.atoms[0]],
    [data.atoms[0], data.atoms[0]],
    [data.atoms[0], { ...data.atoms[1], index: 3 }],
    [{ ...data.atoms[0], element: 'H' }, data.atoms[1]],
  ]) assert.throws(() => parseCharge({ ...data, atoms }));
});

test('charge parser rejects nonnumbers rather than coercing missing data', () => {
  for (const value of ['', '0', true, {}, [], 1e100]) {
    const data = charges();
    assert.throws(() => parseCharge({ ...data, atoms: [{ ...data.atoms[0], value }, data.atoms[1]] }));
  }
  assert.throws(() => parseChargeData('{"value":NaN}', report(), sha, 'bad.json'));
  assert.throws(() => parseChargeData(' '.repeat(MAX_CHARGE_BYTES + 1), report(), sha, 'large.json'));
});

test('formal charge is integer-valued but fractional oxidation states are preserved', () => {
  const data = charges();
  const atoms = [{ ...data.atoms[0], value: 0.5 }, data.atoms[1]];
  assert.throws(() => parseCharge({ ...data, kind: 'formal_charge', atoms }));
  assert.equal(parseCharge({ ...data, kind: 'oxidation_state', atoms }).values[0], 0.5);
});

test('ionic net charge is an independent integer-valued dataset', () => {
  const data = charges();
  assert.equal(parseCharge({ ...data, kind: 'ionic_charge' }).kind, 'ionic_charge');
  assert.throws(() => parseCharge({ ...data, kind: 'ionic_charge',
    atoms: [{ ...data.atoms[0], value: 0.5 }, data.atoms[1]] }));
  assert.deepEqual(parseCharge({ ...data, kind: 'ionic_charge',
    atoms: [{ ...data.atoms[0], value: -1 }, { ...data.atoms[1], value: 1 }] }).values, [-1, 1]);
});

test('Cube in Bohr converts coordinates only and preserves scalar units and values', () => {
  const data = parseCubeData(cube({ bohr: true }), report(), density, 'density.cube');
  assert.equal(data.pointCount, 8);
  assert.equal(data.units, 'e/bohr^3');
  assert.equal(data.min, 0); assert.equal(data.max, 0.7);
  const lines = data.cubeText.split('\n');
  assert.deepEqual(lines[2].split(/\s+/).map(Number), [2, -1, 0, 0]);
  assert.deepEqual(lines[3].split(/\s+/).map(Number), [-2, 1, 0, 0]);
  assert.deepEqual(lines[7].split(/\s+/).map(Number), [1, 1, 1, 0, 0]);
  assert.ok(data.suggestedIsovalue > 0 && data.suggestedIsovalue < data.max);
  assert.ok(!data.cubeText.endsWith('\n'), '3Dmol must not parse an empty trailing scalar');
});

test('Cube negative counts use the explicitly supported Å convention, including skew grids', () => {
  const data = parseCubeData(cube({ skew: true }), report(), density, 'skew.cube');
  assert.deepEqual(data.cubeText.split('\n')[4].split(/\s+/).map(Number), [-2, 0.5, 1, 0]);
});

test('a grid that collapses in the renderer float32 transform is rejected', () => {
  const nearlyParallel = cube().replace('-2 1 0 0', '-2 1 1 0')
    .replace('-2 0 1 0', '-2 1 1.00000003 0');
  assert.throws(() => parseCubeData(nearlyParallel, report(), density, 'collapsed.cube'));
  // A resolvable skew basis still works; this is not a blanket skew-grid ban.
  assert.equal(parseCubeData(nearlyParallel.replace('1.00000003', '1.000001'),
    report(), density, 'resolved.cube').pointCount, 8);
});

test('single-orbital Cube supports Fortran exponents and a wrapped dataset identifier', () => {
  const text = cube({ orbital: true, values: '-1D-1 -5D-2 0 0 0 0 5D-2 1D-1' })
    .replace('1 7\n', '1\n7\n');
  const data = parseCubeData(text, report(), orbital, 'orbital.cube');
  assert.equal(data.kind, 'orbital');
  assert.equal(data.min, -0.1); assert.equal(data.max, 0.1);
  assert.equal(Number(data.cubeText.split('\n')[2].split(' ')[0]), 2);
  assert.equal(data.cubeText.split('\n').slice(8).join(' ').trim().split(/\s+/).length, 8);
});

test('Cube rejects mismatched atom count, order, elements, positions and coordinates', () => {
  for (const text of [
    cube().replace('2 -1 0 0\n', '1 -1 0 0\n'),
    cube().replace('6 6.0 0 0 0', '8 8.0 0 0 0'),
    cube().replace('1 1.0 1 0 0', '1 1.0 1.1 0 0'),
    cube().replace('6 6.0 0 0 0', '6 6.0 NaN 0 0'),
  ]) assert.throws(() => parseCubeData(text, report(), density, 'bad.cube'));
  assert.throws(() => parseCubeData(cube(), { ...report(), elements: ['H', 'C'] }, density, 'wrong-order.cube'));
});

test('Cube rejects mixed coordinate-unit signs and invalid or singular grids', () => {
  for (const text of [
    cube().replace('-2 1 0 0', '2 1 0 0'),
    cube().replace('-2 1 0 0', '-2 0 0 0'),
    cube().replace('-2 0 1 0', '-2 1 0 0'),
    cube().replace('-2 1 0 0', '-1 1 0 0'),
    cube().replace('-2 1 0 0', '-2.5 1 0 0'),
    cube().replace('-2 1 0 0', `-${MAX_VOLUME_POINTS} 1 0 0`),
    cube().replace('-2 1 0 0', '-2 400000 0 0')
      .replace('-2 0 1 0', '-2 400000 400000 0').replace('-2 0 0 1', '-2 400000 0 400000'),
  ]) assert.throws(() => parseCubeData(text, report(), density, 'bad-grid.cube'));
});

test('Cube rejects multidataset and truncated or extra scalar data', () => {
  for (const text of [
    cube().replace('2 -1 0 0\n', '2 -1 0 0 2\n'),
    cube({ orbital: true }).replace('1 7\n', '2 7 8\n'),
    cube({ values: '0 0 0' }), cube({ values: '0 0 0 0 0 0 0 0 0' }),
    cube({ values: '0 0 0 0 0 0 0 1junk' }),
    cube({ values: '0 0 0 0 0 0 0 1e100' }),
    cube({ values: '0 0 0 0 0 0 0 1e-100' }),
  ]) assert.throws(() => parseCubeData(text, report(), density, 'bad-values.cube'));
});

test('density cannot contain negative values and units must match declared field kind', () => {
  assert.throws(() => parseCubeData(cube({ values: '-0.1 0 0 0 0 0 0 1' }), report(), density, 'signed.cube'));
  assert.throws(() => parseCubeData(cube(), report(), { ...density, units: 'unknown' }, 'bad.cube'));
  assert.throws(() => parseCubeData(cube(), report(), { ...density, units: 'bohr^-3/2' }, 'bad.cube'));
  assert.throws(() => parseCubeData(cube(), report(), { ...density, source: '' }, 'bad.cube'));
  assert.throws(() => parseCubeData(' '.repeat(MAX_CUBE_BYTES + 1), report(), density, 'large.cube'));
});

test('atomic helpers distinguish nuclear identity and metal elements', () => {
  assert.equal(atomicNumber('C'), 6); assert.equal(atomicNumber('W'), 74);
  assert.equal(atomicNumber('Og'), 118); assert.equal(atomicNumber('Xx'), undefined);
  for (const element of ['Fe', 'Cu', 'Na', 'W', 'U']) assert.equal(isMetalElement(element), true);
  for (const element of ['C', 'Si', 'Cl', 'He', 'Xx']) assert.equal(isMetalElement(element), false);
});

test('named datasets of the same kind append independently and preserve exact original text', () => {
  const raw = '\uFEFF' + JSON.stringify(charges(), null, 2).replace(/\n/g, '\r\n') + '\r\n';
  const first = parseChargeData(raw, report(), sha, 'calc-a.json', { name: 'Calculation A' });
  const second = parseChargeData(raw, report(), sha, 'calc-b.json', { name: 'Calculation B' });
  let data = appendAuxiliaryDataset({ charges: [], volumes: [] }, first);
  data = appendAuxiliaryDataset(data, second);
  assert.equal(data.charges.length, 2);
  assert.notEqual(data.charges[0].id, data.charges[1].id);
  assert.deepEqual(data.charges.map((item) => item.name), ['Calculation A', 'Calculation B']);
  assert.equal(first.rawText, raw);
  assert.equal(parseChargeData(raw, report(), sha, 'calc-a.json').id, first.id);
  assert.equal(auxiliaryByteSize(data), new TextEncoder().encode(raw).byteLength * 2);
});

test('saved electronic data restores originals and recomputes all derived values', () => {
  const rawCube = '\uFEFF' + cube({ bohr: true }).replace(/\n/g, '\r\n') + '\r\n';
  const charge = parseChargeData(JSON.stringify(charges()), report(), sha, 'q.json', { id: 'charge-a', name: 'Hirshfeld A' });
  const volume = parseCubeData(rawCube, report(), density, 'density.cube', { id: 'density-a', name: 'Density A' });
  const archived = serializeAuxiliaryData({ charges: [charge], volumes: [volume] });
  assert.deepEqual(Object.keys(archived.charges[0]).sort(), ['filename', 'id', 'name', 'rawText']);
  assert.ok(!('cubeText' in archived.volumes[0]));
  const restored = restoreAuxiliaryData(JSON.parse(JSON.stringify(archived)), report(), sha);
  assert.deepEqual(restored, { charges: [charge], volumes: [volume] });
  assert.equal(restored.volumes[0].rawText, rawCube);
  const injected = { ...archived, charges: [{ ...archived.charges[0], values: [100, 100] }],
    volumes: [{ ...archived.volumes[0], min: -999, cubeText: 'untrusted cache' }] };
  assert.deepEqual(restoreAuxiliaryData(injected, report(), sha), restored);
});

test('restoring electronic data rejects foreign CIF identity and corrupted raw files atomically', () => {
  const charge = parseCharge(JSON.parse(JSON.stringify(charges())));
  const volume = parseCubeData(cube(), report(), density, 'density.cube');
  const archived = serializeAuxiliaryData({ charges: [charge], volumes: [volume] });
  assert.throws(() => restoreAuxiliaryData(archived, report(), 'b'.repeat(64)), /SHA-256/);
  assert.throws(() => restoreAuxiliaryData({ ...archived, volumes: [{ ...archived.volumes[0],
    rawText: cube().replace('1 1.0 1 0 0', '1 1.0 5 0 0') }] }, report(), sha), /not aligned/);
  assert.throws(() => restoreAuxiliaryData({ ...archived, charges: [archived.charges[0], archived.charges[0]] }, report(), sha), /unique/);
  assert.throws(() => restoreAuxiliaryData({ ...archived, volumes: [{ ...archived.volumes[0], units: 'arbitrary' }] }, report(), sha), /units/);
});

test('dataset collection limits bound counts, individual bytes and aggregate original bytes', () => {
  const charge = parseCharge(charges());
  const volume = parseCubeData(cube(), report(), density, 'density.cube');
  const many = Array.from({ length: MAX_AUXILIARY_DATASETS + 1 }, (_, index) => ({ ...charge, id: `q-${index}` }));
  assert.throws(() => serializeAuxiliaryData({ charges: many, volumes: [] }), /At most/);
  assert.throws(() => restoreAuxiliaryData({ schemaVersion: 1, charges: many, volumes: [] }, report(), sha), /At most/);
  assert.throws(() => assertAuxiliaryLimits({ charges: [{ ...charge, rawText: 'é'.repeat(MAX_CHARGE_BYTES) }], volumes: [] }), /exceeds/);
  const largeRaw = ' '.repeat(MAX_CUBE_BYTES);
  assert.throws(() => assertAuxiliaryLimits({ charges: [{ ...charge, rawText: 'x' }], volumes: [
    { ...volume, id: 'v-1', rawText: largeRaw }, { ...volume, id: 'v-2', rawText: largeRaw },
  ] }), /total limit/);
});
