import type { ChargeDataset, ChargeKind, ViewerAuxiliaryData, VolumeDataset } from './viewerData.ts';
import type { ColorMode, Quality, Representation } from './viewerPresentation.ts';

export interface ViewerState {
  schemaVersion: 1;
  repeat: 1 | 2 | 3;
  showBonds: boolean;
  showCell: boolean;
  showLabels: boolean;
  showDistance: boolean;
  representation: Representation;
  colorMode: ColorMode;
  quality: Quality;
  preset: 'default' | 'top' | 'side';
  projection: 'perspective' | 'orthographic';
  spinning: boolean;
  expanded: boolean;
  chargeDatasetIds: Partial<Record<ChargeKind, string>>;
  volumeDatasetId: string | null;
  surface: { enabled: boolean; level: number; opacity: number };
  /** 3Dmol translation, zoom and quaternion [x,y,z,w], in that order. */
  camera: number[] | null;
}

const CHARGE_KINDS: ChargeKind[] = ['partial_charge', 'formal_charge', 'ionic_charge', 'oxidation_state'];

export function defaultViewerState(compact = false): ViewerState {
  return {
    schemaVersion: 1, repeat: compact ? 1 : 3,
    showBonds: true, showCell: false, showLabels: false, showDistance: true,
    representation: 'ball-stick', colorMode: 'element', quality: 'balanced',
    preset: 'default', projection: 'perspective', spinning: false, expanded: false,
    chargeDatasetIds: {}, volumeDatasetId: null,
    surface: { enabled: false, level: 0.01, opacity: 0.35 }, camera: null,
  };
}

function requireValue(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function record(value: unknown): Record<string, unknown> {
  requireValue(value !== null && typeof value === 'object' && !Array.isArray(value), 'Viewer state must be an object.');
  return value as Record<string, unknown>;
}

function validId(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
}

export function validCamera(value: unknown): value is number[] {
  if (!Array.isArray(value) || value.length !== 8
    || !value.every((item) => typeof item === 'number' && Number.isFinite(item) && Math.abs(item) <= 10_000_000)) return false;
  return Math.abs(Math.hypot(...value.slice(4)) - 1) <= 0.001;
}

export function sameCamera(a: number[] | null, b: number[] | null): boolean {
  return a === b || Boolean(a && b && a.length === b.length
    && a.every((value, index) => Math.abs(value - b[index]) <= 1e-9));
}

/** Validate archived state without carrying arbitrary imported properties into the viewer. */
export function restoreViewerState(value: unknown, compact = false): ViewerState {
  if (value === undefined || value === null) return defaultViewerState(compact);
  const input = record(value);
  requireValue(input.schemaVersion === 1, 'Unsupported viewer-state schema version.');
  const state = defaultViewerState(compact);
  for (const key of ['showBonds', 'showCell', 'showLabels', 'showDistance', 'spinning', 'expanded'] as const) {
    requireValue(typeof input[key] === 'boolean', `Viewer ${key} must be a boolean.`);
    state[key] = input[key];
  }
  requireValue([1, 2, 3].includes(input.repeat as number), 'Viewer repeat must be 1, 2 or 3.');
  state.repeat = input.repeat as ViewerState['repeat'];
  const choices = {
    representation: ['ball-stick', 'stick', 'spacefill'],
    colorMode: ['element', 'metal', ...CHARGE_KINDS],
    quality: ['light', 'balanced', 'high'], preset: ['default', 'top', 'side'],
    projection: ['perspective', 'orthographic'],
  } as const;
  for (const key of Object.keys(choices) as (keyof typeof choices)[]) {
    requireValue((choices[key] as readonly unknown[]).includes(input[key]), `Viewer ${key} is unsupported.`);
  }
  state.representation = input.representation as Representation;
  state.colorMode = input.colorMode as ColorMode;
  state.quality = input.quality as Quality;
  state.preset = input.preset as ViewerState['preset'];
  state.projection = input.projection as ViewerState['projection'];
  const ids = record(input.chargeDatasetIds);
  requireValue(Object.keys(ids).every((kind) => CHARGE_KINDS.includes(kind as ChargeKind)), 'Unsupported charge dataset selection.');
  for (const kind of CHARGE_KINDS) if (ids[kind] !== undefined) {
    requireValue(validId(ids[kind]), 'Invalid selected charge dataset ID.'); state.chargeDatasetIds[kind] = ids[kind];
  }
  requireValue(input.volumeDatasetId === null || validId(input.volumeDatasetId), 'Invalid selected volume dataset ID.');
  state.volumeDatasetId = input.volumeDatasetId;
  const surface = record(input.surface);
  requireValue(typeof surface.enabled === 'boolean'
    && typeof surface.level === 'number' && Number.isFinite(surface.level) && surface.level > 0 && surface.level <= 3.4e38
    && typeof surface.opacity === 'number' && Number.isFinite(surface.opacity) && surface.opacity >= 0.05 && surface.opacity <= 1,
  'Viewer surface needs a positive finite isovalue and opacity between 0.05 and 1.');
  state.surface = { enabled: surface.enabled, level: surface.level, opacity: surface.opacity };
  requireValue(input.camera === null || validCamera(input.camera), 'Viewer camera must contain a finite translation, zoom and unit quaternion.');
  state.camera = input.camera === null ? null : [...input.camera as number[]];
  return state;
}

export function selectedCharge(data: ViewerAuxiliaryData | undefined, state: ViewerState, kind?: ChargeKind): ChargeDataset | undefined {
  const quantity = kind ?? (CHARGE_KINDS.includes(state.colorMode as ChargeKind) ? state.colorMode as ChargeKind : undefined);
  if (!quantity) return undefined;
  return data?.charges.find((dataset) => dataset.kind === quantity && dataset.id === state.chargeDatasetIds[quantity])
    ?? data?.charges.find((dataset) => dataset.kind === quantity);
}

export function selectedVolume(data: ViewerAuxiliaryData | undefined, state: ViewerState): VolumeDataset | undefined {
  return data?.volumes.find((dataset) => dataset.id === state.volumeDatasetId) ?? data?.volumes[0];
}

/** Persist a concrete selection while keeping each physical quantity independent. */
export function reconcileViewerDatasets(state: ViewerState, data: ViewerAuxiliaryData | undefined): ViewerState {
  if (!data) return state;
  const chargeDatasetIds: ViewerState['chargeDatasetIds'] = {};
  for (const kind of CHARGE_KINDS) {
    const dataset = selectedCharge(data, state, kind);
    if (dataset) chargeDatasetIds[kind] = dataset.id;
  }
  const volume = selectedVolume(data, state);
  const volumeChanged = (volume?.id ?? null) !== state.volumeDatasetId;
  const surface = volumeChanged
    ? { ...state.surface, enabled: false, level: volume?.suggestedIsovalue ?? 0.01 }
    : state.surface;
  if (!volumeChanged && CHARGE_KINDS.every((kind) => state.chargeDatasetIds[kind] === chargeDatasetIds[kind])) return state;
  return { ...state, chargeDatasetIds, volumeDatasetId: volume?.id ?? null, surface };
}
