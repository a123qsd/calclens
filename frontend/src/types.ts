export type Vec3 = [number, number, number];
export type Language = 'ko' | 'en';
export interface Contact {
  i: number; j: number; element_i: string; element_j: string;
  shift: Vec3; distance_angstrom: number; is_self_image: boolean;
  start_shift?: Vec3; end_shift?: Vec3; displacement_cartesian?: Vec3;
  distance_kind?: string;
}
export interface Issue {
  code: string; severity: string; message: string;
  atom_indices?: number[]; representative_contact?: Contact; contact_count?: number;
}
export interface GeometryReport {
  schema_version: string; formula: string; atom_count: number;
  elements: string[]; cell: Vec3[]; positions: Vec3[]; scaled_positions: Vec3[];
  periodic_axes: boolean[]; normal_axis: string; normal_axis_index: number;
  in_plane_axes: string[]; review_required: boolean; gap_review_required: boolean;
  metrics: {
    minimum_distance_angstrom: number; minimum_pair: Contact;
    c_height_angstrom: number; normal_height_angstrom: number;
    nuclei_thickness_angstrom: number; nuclei_gap_angstrom: number;
    gap_fraction: number; gap_start_fraction: number; gap_end_fraction: number;
    second_largest_gap_angstrom: number;
  };
  short_distance_threshold_angstrom: number; short_contacts: Contact[];
  short_contact_count: number; short_contacts_truncated: boolean;
  issues: Issue[]; assumptions: string[]; limitations: string[];
  provenance?: { original_filename: string; sha256: string; calclens_version?: string; ase_version?: string };
}
export interface PairSelection {
  i: number; j: number; first_shift: Vec3; second_shift: Vec3;
  mode: 'minimum_image' | 'displayed';
}
export interface AtomPick { index: number; shift: Vec3; element: string }
export interface Entry {
  id: string; filename: string; sha256: string; normal_axis: string;
  short_distance: number; note: string; reviewed: boolean; review_current: boolean;
  review_stamp: Record<string, unknown> | null; measurements: PairSelection[];
  preparation?: Record<string, unknown> | null;
  analysis: { report: GeometryReport | null; error: string | null;
    auxiliary_structure?: Pick<GeometryReport, 'atom_count' | 'elements' | 'positions'> | null;
    issues_ko?: Issue[]; error_ko?: string | null;
    assumptions_ko?: string[]; limitations_ko?: string[] };
}
export interface Workspace {
  api_version: 1; token: string; revision: number; language: Language;
  runtime?: { calclens_version: string; ase_version: string; analysis_revision: string };
  examples: { name: string; label_ko: string; label_en: string }[];
  limits: { max_files: number; max_file_bytes: number; max_pair_selections: number };
  project: { selected_id: string; review_focus: string; filter_mode: string;
    progress_filter: string; calclens_version: string; ase_version: string;
    analysis_revision: string; workspace_state?: unknown };
  entries: Entry[];
}
export interface Measurement { i: number; j: number; displayed: Contact; minimum_image: Contact }
export interface MolecularViewerProps {
  report: GeometryReport; language: Language;
  source?: { filename: string; sha256: string };
  highlight?: Contact | null;
  highlightGap?: boolean;
  highlightedAtomIndices?: number[];
  onAtomPick?: (atom: AtomPick) => void;
  compact?: boolean;
  auxiliary?: ViewerAuxiliaryData;
  state?: ViewerState;
  onStateChange?: (state: ViewerState) => void;
  chargeRange?: [number, number];
  onViewerReady?: (viewer: GLViewer | null) => void;
}
import type { GLViewer } from '3dmol';
import type { ViewerAuxiliaryData } from './viewerData';
import type { ViewerState } from './viewerState';
