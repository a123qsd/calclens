import type { Language, Measurement, Vec3, Workspace } from './types.ts';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code = 'request_failed',
    readonly revision?: number,
  ) {
    super(message);
  }
}

type ErrorEnvelope = { error?: { code?: string; message?: string }; revision?: number };

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  let envelope: ErrorEnvelope = {};
  try { envelope = await response.json() as ErrorEnvelope; } catch { /* non-JSON response */ }
  throw new ApiError(
    envelope.error?.message ?? `${response.status} ${response.statusText}`,
    response.status,
    envelope.error?.code,
    envelope.revision,
  );
}

export async function bootstrap(): Promise<Workspace> {
  return parseResponse(await fetch('/api/v1/bootstrap', { cache: 'no-store' }));
}

export async function reloadWorkspace(): Promise<Workspace> {
  return parseResponse(await fetch('/api/v1/workspace', { cache: 'no-store' }));
}

export async function dispatchAction(
  workspace: Workspace,
  action: Record<string, unknown>,
): Promise<Workspace> {
  return parseResponse(await fetch('/api/v1/actions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CalcLens-Token': workspace.token },
    body: JSON.stringify({ expected_revision: workspace.revision, action }),
  }));
}

export async function importProject(workspace: Workspace, bytes: ArrayBuffer): Promise<Workspace> {
  return parseResponse(await fetch('/api/v1/project/import', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CalcLens-Token': workspace.token,
      'X-CalcLens-Revision': String(workspace.revision),
    },
    body: bytes,
  }));
}

export async function measure(
  workspace: Workspace,
  entryId: string,
  i: number,
  j: number,
  firstShift: Vec3,
  secondShift: Vec3,
): Promise<Measurement> {
  return parseResponse(await fetch('/api/v1/measure', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CalcLens-Token': workspace.token },
    body: JSON.stringify({ expected_revision: workspace.revision, entry_id: entryId,
      i, j, first_shift: firstShift, second_shift: secondShift }),
  }));
}

export async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  const block = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += block) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + block));
  }
  return btoa(binary);
}

export function reportUrl(entryId: string, format: 'json' | 'csv', language: Language): string {
  return `/api/v1/entries/${encodeURIComponent(entryId)}/report.${format}?lang=${language}`;
}
