import assert from 'node:assert/strict';
import test from 'node:test';
import { assertSurfaceBudget, chargeColor, exportDimensions, labelAtoms, repeatDimensions } from './viewerPresentation.ts';
import type { DisplayAtom } from './viewerGeometry.ts';

test('missing charge has a different color from neutral and signed values', () => {
  assert.notEqual(chargeColor(null, 1), chargeColor(0, 1));
  assert.notEqual(chargeColor(-1, 1), chargeColor(1, 1));
  assert.equal(chargeColor(-10, 1), chargeColor(-1, 1));
});

test('repeat dimensions follow the chosen normal axis', () => {
  assert.deepEqual(repeatDimensions(0, 3), [1, 3, 3]);
  assert.deepEqual(repeatDimensions(1, 2), [2, 1, 2]);
  assert.deepEqual(repeatDimensions(2, 1), [1, 1, 1]);
});

test('bounded labels prioritize picked and highlighted atoms without duplicating them', () => {
  const atoms = Array.from({ length: 200 }, (_, index): DisplayAtom => ({
    displayIndex: index, index, element: 'C', shift: [0, 0, 0],
    position: [index, 0, 0], highlight: index === 199,
  }));
  const chosen = labelAtoms(atoms, 198, 180);
  assert.equal(chosen.length, 180);
  assert.equal(new Set(chosen.map((atom) => atom.displayIndex)).size, 180);
  assert.ok(chosen.some((atom) => atom.index === 198));
  assert.ok(chosen.some((atom) => atom.index === 199));
  const allHighlighted = atoms.map((atom) => ({ ...atom, highlight: true }));
  assert.equal(labelAtoms(allHighlighted, 198, 1)[0].index, 198);
});

test('export dimensions preserve aspect and cap physical pixels', () => {
  assert.deepEqual(exportDimensions(800, 400, 3200), { width: 3200, height: 1600 });
  assert.deepEqual(exportDimensions(400, 800, 3200), { width: 1600, height: 3200 });
  assert.throws(() => exportDimensions(0, 100, 1600));
});

test('noisy volumes are rejected before unbounded surface allocation', () => {
  const values = Float32Array.from({ length: 64 }, (_, i) => i % 2 ? 1 : -1);
  assert.throws(() => assertSurfaceBudget(values, { x: 4, y: 4, z: 4 }, [0.5, -0.5], 10), /complexity limit/);
  assert.doesNotThrow(() => assertSurfaceBudget(new Float32Array(64), { x: 4, y: 4, z: 4 }, [0.5], 1));
});
