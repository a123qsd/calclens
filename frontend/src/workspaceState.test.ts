import assert from 'node:assert/strict';
import test from 'node:test';
import { comparisonRange, defaultComparison, entryDraft, hasDraftChanges, reconcileDraft, restoreClientWorkspace, serializeClientWorkspace, viewerKey } from './workspaceState.ts';
import { defaultViewerState } from './viewerState.ts';
import type { ChargeDataset } from './viewerData.ts';
import type { Entry, Workspace } from './types.ts';

const entry = { id: 'one', sha256: 'a'.repeat(64), normal_axis: 'c', short_distance: 1,
  note: 'saved', analysis: { report: null, error: null } } as Entry;

test('draft text and incomplete cutoff survive unrelated server updates', () => {
  const draft = { ...entryDraft(entry), note: 'unsaved work', cutoff: '' };
  const next = reconcileDraft(draft, { ...entry, normal_axis: 'a', note: 'other tab' });
  assert.equal(next.note, 'unsaved work'); assert.equal(next.cutoff, '');
  assert.equal(next.axis, 'a'); assert.equal(next.baseline.note, 'other tab');
  assert.equal(hasDraftChanges(next, entry), true);
});

test('draft ownership separates duplicate filenames and preserves notes on source replacement', () => {
  const a = { ...entryDraft(entry), note: 'file one' };
  const other = { ...entry, id: 'two' };
  assert.equal(entryDraft(other).note, 'saved');
  assert.notEqual(viewerKey(entry), viewerKey(other));
  const replaced = reconcileDraft(a, { ...entry, sha256: 'b'.repeat(64) });
  assert.equal(replaced.note, 'file one'); assert.equal(replaced.sha256, 'b'.repeat(64));
});

test('shared range distinguishes tenfold charge magnitudes and excludes unlike quantities', () => {
  const a = { kind: 'partial_charge', values: [-0.1, 0, 0.1] } as ChargeDataset;
  const b = { ...a, values: [-1, 0, 1] };
  assert.deepEqual(comparisonRange(defaultComparison(), a, b), [-1, 1]);
  assert.equal(comparisonRange(defaultComparison(), a, { ...b, kind: 'oxidation_state' }), undefined);
  assert.equal(comparisonRange({ ...defaultComparison(), rangeMode: 'auto' }, a, b), undefined);
  assert.deepEqual(comparisonRange({ ...defaultComparison(), rangeMode: 'manual', manualMin: '-2', manualMax: '3' }, a, b), [-2, 3]);
  for (const [manualMin, manualMax] of [['', '1'], ['1', '2'], ['-1', 'NaN'], ['-1', '0']]) {
    assert.equal(comparisonRange({ ...defaultComparison(), rangeMode: 'manual', manualMin, manualMax }, a, b), undefined);
  }
});

test('archive keeps unapplied drafts separate from applied project values', () => {
  const view = { ...defaultViewerState(), representation: 'spacefill' as const };
  const state = serializeClientWorkspace({ auxiliary: {}, viewers: { [viewerKey(entry)]: view },
    drafts: { one: { ...entryDraft(entry), note: 'not applied', cutoff: '' } },
    comparison: defaultComparison(), before: 'one', after: 'one', view: 'compare' }, [entry]);
  const workspace = { entries: [entry], project: { workspace_state: state } } as unknown as Workspace;
  const restored = restoreClientWorkspace(workspace);
  assert.equal(entry.note, 'saved'); assert.equal(restored.drafts.one.note, 'not applied');
  assert.equal(restored.drafts.one.cutoff, ''); assert.equal(restored.view, 'compare');
  assert.equal(restored.viewers[viewerKey(entry)].representation, 'spacefill');
});

test('mismatched draft bindings and foreign viewer keys are rejected', () => {
  const state = serializeClientWorkspace({ auxiliary: {}, viewers: {},
    drafts: { one: { ...entryDraft(entry), note: 'draft' } }, comparison: defaultComparison(),
    before: 'one', after: 'one', view: 'overview' }, [entry]);
  const workspace = { entries: [entry], project: { workspace_state: state } } as unknown as Workspace;
  state.drafts.one.sha256 = 'b'.repeat(64);
  assert.throws(() => restoreClientWorkspace(workspace), /matching CIF/);
  state.drafts = {}; state.viewers.foreign = defaultViewerState();
  assert.throws(() => restoreClientWorkspace(workspace), /matching CIF/);
});

test('duplicate sources and an unsupported axis retain source-matched electronic files', () => {
  const structure = { atom_count: 1, elements: ['C'], positions: [[0, 0, 0]] };
  const rawText = JSON.stringify({ schema_version: 1, structure_sha256: entry.sha256,
    kind: 'partial_charge', method: 'fixture', source: 'parser test',
    atoms: [{ index: 1, element: 'C', value: 0.1 }] });
  const state = { schema_version: 1, auxiliary: { [entry.sha256]: { schemaVersion: 1,
    charges: [{ id: 'charge1', name: 'Charge', filename: 'charge.json', rawText }], volumes: [] } },
  viewers: {}, drafts: {}, comparison: { ...defaultComparison(), before: entry.id, after: entry.id }, view: 'overview' };
  const supported = { ...entry, analysis: { report: structure, error: null } };
  const unsupported = { ...entry, id: 'other', analysis: { report: null, error: 'unsupported axis', auxiliary_structure: structure } };
  for (const entries of [[supported, { ...unsupported, analysis: { report: null, error: 'unsupported' } }], [unsupported]]) {
    const workspace = { entries, project: { workspace_state: state } } as unknown as Workspace;
    assert.equal(restoreClientWorkspace(workspace).auxiliary[entry.sha256].charges[0].rawText, rawText);
  }
});
