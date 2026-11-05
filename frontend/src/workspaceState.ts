import type { Entry, Workspace } from './types.ts';
import { restoreAuxiliaryData, serializeAuxiliaryData } from './viewerData.ts';
import type { ViewerAuxiliaryData } from './viewerData.ts';
import { restoreViewerState, selectedCharge } from './viewerState.ts';
export { selectedCharge } from './viewerState.ts';
import type { ViewerState } from './viewerState.ts';

export type View = 'overview' | 'compare' | 'review' | 'methods';
export interface EntryDraft {
  sha256: string;
  axis: string;
  cutoff: string;
  note: string;
  baseline: { axis: string; cutoff: string; note: string };
}
export interface ComparisonSettings {
  rangeMode: 'auto' | 'shared' | 'manual';
  manualMin: string;
  manualMax: string;
  sync: boolean;
}
export const defaultComparison = (): ComparisonSettings => ({
  rangeMode: 'shared', manualMin: '-1', manualMax: '1', sync: false,
});

export function entryDraft(entry: Entry): EntryDraft {
  const fields = { axis: entry.normal_axis, cutoff: String(entry.short_distance), note: entry.note };
  return { ...fields, sha256: entry.sha256, baseline: { ...fields } };
}

/** Update untouched fields after a server refresh, preserving each user's draft. */
export function reconcileDraft(previous: EntryDraft | undefined, entry: Entry): EntryDraft {
  const next = entryDraft(entry);
  if (!previous) return next;
  for (const field of ['axis', 'cutoff', 'note'] as const) {
    if (previous[field] !== previous.baseline[field]) next[field] = previous[field];
  }
  return next;
}

export function hasDraftChanges(draft: EntryDraft, entry: Entry): boolean {
  return draft.axis !== entry.normal_axis || Number(draft.cutoff) !== entry.short_distance
    || draft.cutoff.trim() === '' || draft.note !== entry.note;
}

export function viewerKey(entry: Pick<Entry, 'id' | 'sha256'>, slot = 'overview'): string {
  return `${slot}:${entry.id}:${entry.sha256}`;
}

export function comparisonRange(
  settings: ComparisonSettings,
  left: ReturnType<typeof selectedCharge>, right: ReturnType<typeof selectedCharge>,
): [number, number] | undefined {
  if (!left || !right || left.kind !== right.kind || settings.rangeMode === 'auto') return undefined;
  if (settings.rangeMode === 'manual') {
    const minimum = Number(settings.manualMin); const maximum = Number(settings.manualMax);
    return settings.manualMin.trim() && settings.manualMax.trim()
      && Number.isFinite(minimum) && Number.isFinite(maximum)
      && minimum < 0 && maximum > 0 ? [minimum, maximum] : undefined;
  }
  const extent = Math.max(0, ...left.values.map((value) => Math.abs(value ?? 0)),
    ...right.values.map((value) => Math.abs(value ?? 0))) || 1;
  return [-extent, extent];
}

export interface ClientWorkspace {
  auxiliary: Record<string, ViewerAuxiliaryData>;
  viewers: Record<string, ViewerState>;
  drafts: Record<string, EntryDraft>;
  comparison: ComparisonSettings;
  before: string;
  after: string;
  view: View;
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid saved workspace state.');
  return value as Record<string, unknown>;
}
function text(value: unknown, maximum: number): string {
  if (typeof value !== 'string' || value.length > maximum) throw new Error('Invalid saved workspace text.');
  return value;
}

/** Reparse original electronic files before passing anything to the renderer. */
export function restoreClientWorkspace(workspace: Workspace): ClientWorkspace {
  const empty: ClientWorkspace = { auxiliary: Object.create(null), viewers: Object.create(null), drafts: Object.create(null),
    comparison: defaultComparison(), before: '', after: '', view: 'overview' };
  const raw = workspace.project.workspace_state;
  if (raw == null || Object.keys(object(raw)).length === 0) return empty;
  const saved = object(raw);
  if (saved.schema_version !== 1) throw new Error('Unsupported workspace-state version.');
  const byId = new Map(workspace.entries.map((entry) => [entry.id, entry]));
  for (const [sha, value] of Object.entries(object(saved.auxiliary))) {
    const entry = workspace.entries.find((candidate) => candidate.sha256 === sha
      && (candidate.analysis.report || candidate.analysis.auxiliary_structure));
    const structure = entry?.analysis.report ?? entry?.analysis.auxiliary_structure;
    if (!structure) throw new Error('Saved electronic data has no matching supported CIF.');
    empty.auxiliary[sha] = restoreAuxiliaryData(value, structure, sha);
  }
  const allowedKeys = new Set(workspace.entries.flatMap((entry) =>
    ['overview', 'left', 'right'].map((slot) => viewerKey(entry, slot))));
  for (const [key, value] of Object.entries(object(saved.viewers))) {
    if (!allowedKeys.has(key)) throw new Error('Saved view has no matching CIF.');
    empty.viewers[key] = restoreViewerState(value, !key.startsWith('overview:'));
  }
  for (const [id, value] of Object.entries(object(saved.drafts))) {
    const entry = byId.get(id); const draft = object(value); const baseline = object(draft.baseline);
    if (!entry || draft.sha256 !== entry.sha256) throw new Error('Saved draft has no matching CIF.');
    const restored = { sha256: entry.sha256, axis: text(draft.axis, 1),
      cutoff: text(draft.cutoff, 32), note: text(draft.note, 10_000),
      baseline: { axis: text(baseline.axis, 1), cutoff: text(baseline.cutoff, 32), note: text(baseline.note, 10_000) } };
    if (!['a', 'b', 'c'].includes(restored.axis) || !['a', 'b', 'c'].includes(restored.baseline.axis)) {
      throw new Error('Invalid saved draft axis.');
    }
    empty.drafts[id] = reconcileDraft(restored, entry);
  }
  const comparison = object(saved.comparison);
  if (!['auto', 'shared', 'manual'].includes(String(comparison.rangeMode)) || typeof comparison.sync !== 'boolean') {
    throw new Error('Invalid comparison settings.');
  }
  empty.comparison = { rangeMode: comparison.rangeMode as ComparisonSettings['rangeMode'],
    manualMin: text(comparison.manualMin, 32), manualMax: text(comparison.manualMax, 32), sync: comparison.sync };
  empty.before = text(comparison.before, 128); empty.after = text(comparison.after, 128);
  if (!['overview', 'compare', 'review', 'methods'].includes(String(saved.view))) throw new Error('Invalid saved screen.');
  empty.view = saved.view as View;
  return empty;
}

export function serializeClientWorkspace(state: ClientWorkspace, entries: Entry[]) {
  const sources = new Set(entries.map((entry) => entry.sha256));
  const allowedKeys = new Set(entries.flatMap((entry) =>
    ['overview', 'left', 'right'].map((slot) => viewerKey(entry, slot))));
  const auxiliary = Object.fromEntries(Object.entries(state.auxiliary)
    .filter(([sha]) => sources.has(sha)).map(([sha, data]) => [sha, serializeAuxiliaryData(data)]));
  const drafts = Object.fromEntries(entries.flatMap((entry) => {
    const draft = reconcileDraft(state.drafts[entry.id], entry);
    return hasDraftChanges(draft, entry) ? [[entry.id, draft]] : [];
  }));
  return { schema_version: 1, auxiliary,
    viewers: Object.fromEntries(Object.entries(state.viewers).filter(([key]) => allowedKeys.has(key))),
    drafts, comparison: { ...state.comparison, before: state.before, after: state.after }, view: state.view };
}
