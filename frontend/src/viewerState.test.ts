import assert from 'node:assert/strict';
import test from 'node:test';
import type { ChargeDataset, ViewerAuxiliaryData, VolumeDataset } from './viewerData.ts';
import { defaultViewerState, reconcileViewerDatasets, restoreViewerState, sameCamera, selectedCharge, selectedVolume, validCamera } from './viewerState.ts';

const data: ViewerAuxiliaryData = {
  charges: [
    { id: 'q-a', kind: 'partial_charge', values: [null, 0] },
    { id: 'q-b', kind: 'partial_charge', values: [-1, 1] },
    { id: 'ox-a', kind: 'oxidation_state', values: [2, -2] },
  ] as ChargeDataset[],
  volumes: [{ id: 'v-a', suggestedIsovalue: 0.1 }, { id: 'v-b', suggestedIsovalue: 0.2 }] as VolumeDataset[],
};

test('viewer state round trips camera, display settings and independent dataset IDs', () => {
  const state = { ...defaultViewerState(true), repeat: 2 as const, representation: 'spacefill' as const,
    projection: 'orthographic' as const, showCell: true, showLabels: true,
    colorMode: 'partial_charge' as const, chargeDatasetIds: { partial_charge: 'q-b', oxidation_state: 'ox-a' },
    volumeDatasetId: 'v-b', surface: { enabled: true, level: 0.2, opacity: 0.6 },
    camera: [1, 2, 3, -90, 0, 0, Math.SQRT1_2, Math.SQRT1_2] };
  const restored = restoreViewerState(JSON.parse(JSON.stringify(state)));
  assert.deepEqual(restored, state);
  restored.camera![0] = 99; restored.chargeDatasetIds.partial_charge = 'q-a';
  assert.equal(state.camera[0], 1); assert.equal(state.chargeDatasetIds.partial_charge, 'q-b');
  assert.equal(defaultViewerState().repeat, 3); assert.equal(defaultViewerState(true).repeat, 1);
});

test('viewer selections remain independent even when both slots display one CIF', () => {
  const left = { ...defaultViewerState(true), colorMode: 'partial_charge' as const,
    chargeDatasetIds: { partial_charge: 'q-a' }, volumeDatasetId: 'v-a' };
  const right = { ...defaultViewerState(true), colorMode: 'partial_charge' as const,
    chargeDatasetIds: { partial_charge: 'q-b' }, volumeDatasetId: 'v-b' };
  assert.equal(selectedCharge(data, left)?.id, 'q-a'); assert.equal(selectedCharge(data, right)?.id, 'q-b');
  assert.equal(selectedCharge(data, left, 'oxidation_state')?.id, 'ox-a');
  assert.equal(selectedVolume(data, left)?.id, 'v-a'); assert.equal(selectedVolume(data, right)?.id, 'v-b');
  assert.equal(selectedCharge(data, defaultViewerState()), undefined);
});

test('dataset removal selects an existing replacement and disables a stale surface', () => {
  const state = { ...defaultViewerState(), colorMode: 'partial_charge' as const,
    chargeDatasetIds: { partial_charge: 'removed', oxidation_state: 'ox-a' },
    volumeDatasetId: 'removed', surface: { enabled: true, level: 0.4, opacity: 0.6 } };
  const next = reconcileViewerDatasets(state, data);
  assert.equal(next.chargeDatasetIds.partial_charge, 'q-a');
  assert.equal(next.chargeDatasetIds.oxidation_state, 'ox-a');
  assert.equal(next.volumeDatasetId, 'v-a');
  assert.deepEqual(next.surface, { enabled: false, level: 0.1, opacity: 0.6 });
  assert.equal(reconcileViewerDatasets(next, data), next);
  const empty = defaultViewerState();
  assert.equal(reconcileViewerDatasets(empty, { charges: [], volumes: [] }), empty);
});

test('archived viewer state rejects invalid camera, options, selections and surface values', () => {
  const state = defaultViewerState();
  for (const patch of [
    { schemaVersion: 2 }, { repeat: 100 }, { projection: 'fish-eye' }, { colorMode: 'nuclear_charge' },
    { camera: [0, 0, 0, 0, 0, 0, 0, 0] }, { camera: [0, 0, 0, Infinity, 0, 0, 0, 1] },
    { camera: [0, 0, 0, 0, 0, 0, 1] }, { showBonds: 'false' },
    { chargeDatasetIds: { partial_charge: '../unsafe' } }, { chargeDatasetIds: { charge: 'q-a' } },
    { surface: { enabled: true, level: -1, opacity: 0.35 } },
    { surface: { enabled: true, level: 1, opacity: 2 } },
  ]) assert.throws(() => restoreViewerState({ ...state, ...patch }));
});

test('camera comparison ignores rendering echoes while retaining rotation and zoom changes', () => {
  const camera = [0, 0, 0, -50, 0, 0, 0, 1];
  assert.equal(validCamera(camera), true);
  assert.equal(sameCamera(camera, [...camera]), true);
  assert.equal(sameCamera(camera, [0, 0, 0, -60, 0, 0, 0, 1]), false);
  assert.equal(sameCamera(camera, [0, 0, 0, -50, 0, Math.SQRT1_2, 0, Math.SQRT1_2]), false);
});
