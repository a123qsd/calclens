import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { RefObject } from 'react';
import MolecularViewer from './MolecularViewer.tsx';
import AuxiliaryDataPanel from './AuxiliaryDataPanel.tsx';
import PreparationPanel from './PreparationPanel.tsx';
import { defaultViewerState } from './viewerState.ts';
import type { ViewerState } from './viewerState.ts';
import {
  comparisonRange, defaultComparison, entryDraft, hasDraftChanges, reconcileDraft,
  restoreClientWorkspace, selectedCharge, serializeClientWorkspace, viewerKey,
} from './workspaceState.ts';
import type { ClientWorkspace, ComparisonSettings, EntryDraft, View } from './workspaceState.ts';
import { linkCameraViews } from './viewerCameraLink';
import type { GLViewer } from '3dmol';
import type { ViewerAuxiliaryData } from './viewerData';
import {
  ApiError, bootstrap, dispatchAction, exportProject, fileToBase64, importProject, measure,
  reloadWorkspace, reportUrl,
} from './api.ts';
import { copy } from './i18n.ts';
import {
  Aperture, Book, Check, CheckSquare, Compare, Download, External, Flask, GitHub,
  Home, Info, Play, Ruler, Sliders, Trash, Upload,
} from './icons.tsx';
import type {
  AtomPick, Contact, Entry, Issue, Language, Measurement, PairSelection, Vec3, Workspace,
} from './types.ts';

type Notice = { tone: 'error' | 'info'; message: string };
const ZERO: Vec3 = [0, 0, 0];

function finite(value: number | undefined, digits = 3): string {
  return Number.isFinite(value) ? `${value!.toFixed(digits)} Å` : '—';
}

function entryState(entry: Entry) {
  if (entry.analysis.error || !entry.analysis.report) return 'unsupported' as const;
  return entry.analysis.report.review_required ? 'review' as const : 'clear' as const;
}

function StatusMark({ state }: { state: ReturnType<typeof entryState> | 'info' }) {
  return <span className={`status-mark status-${state}`}>{state === 'clear' ? <Check /> : <Info />}</span>;
}

function StatusPill({ entry, language }: { entry: Entry; language: Language }) {
  const c = copy(language);
  const state = entryState(entry);
  const label = state === 'unsupported' ? c.unsupported : state === 'review' ? c.needsReview : c.clear;
  return <span className={`status-pill status-${state}`}><StatusMark state={state} />{label}</span>;
}

function MetricCard({ label, value, hint, tone = 'teal' }: { label: string; value: string; hint: string; tone?: 'teal' | 'amber' }) {
  return <article className="metric-card">
    <span className={`metric-icon ${tone}`}><Ruler /></span>
    <div><strong>{label}</strong><div className="metric-value">{value}</div><small>{hint}</small></div>
  </article>;
}

function shiftText(shift: Vec3 | undefined): string { return `[${(shift ?? ZERO).join(', ')}]`; }
function parseShift(values: [string, string, string]): Vec3 {
  return values.map(Number) as Vec3;
}

function focusForIssue(issue: Issue): string {
  if (issue.code.includes('OVERLAP')) return 'overlap';
  if (issue.code.includes('SHORT')) return 'short';
  if (issue.code.includes('GAP') || issue.code === 'AMBIGUOUS_SLAB') return 'gap';
  return 'metadata';
}

export default function App() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<View>('overview');
  const [viewerEpoch, setViewerEpoch] = useState(0);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [inspectedIssue, setInspectedIssue] = useState<Issue | null>(null);
  const [reportLanguage, setReportLanguage] = useState<Language | 'interface'>('interface');
  const [conflictedEdit, setConflictedEdit] = useState<Record<string, unknown> | null>(null);
  const [measurement, setMeasurement] = useState<Measurement | null>(null);
  const [measuredSelection, setMeasuredSelection] = useState<PairSelection | null>(null);
  const [pairMode, setPairMode] = useState<PairSelection['mode']>('minimum_image');
  const [firstIndex, setFirstIndex] = useState('0');
  const [secondIndex, setSecondIndex] = useState('1');
  const [firstShift, setFirstShift] = useState<[string, string, string]>(['0', '0', '0']);
  const [secondShift, setSecondShift] = useState<[string, string, string]>(['0', '0', '0']);
  const [picked, setPicked] = useState<AtomPick[]>([]);
  const [compareBefore, setCompareBefore] = useState('');
  const [compareAfter, setCompareAfter] = useState('');
  const [sampleName, setSampleName] = useState('');
  const [reviewPanelOpen, setReviewPanelOpen] = useState(true);
  const [auxiliaryBySource, setAuxiliaryBySource] = useState<Record<string, ViewerAuxiliaryData>>({});
  const [drafts, setDrafts] = useState<Record<string, EntryDraft>>(Object.create(null));
  const [viewerStates, setViewerStates] = useState<Record<string, ViewerState>>({});
  const [comparison, setComparison] = useState<ComparisonSettings>(defaultComparison);
  const [unsaved, setUnsaved] = useState(false);
  const editGeneration = useRef(0);
  const markUnsaved = useCallback(() => { editGeneration.current += 1; setUnsaved(true); }, []);
  const viewerStatesRef = useRef(viewerStates);
  viewerStatesRef.current = viewerStates;
  const cifInput = useRef<HTMLInputElement>(null);
  const addInput = useRef<HTMLInputElement>(null);
  const projectInput = useRef<HTMLInputElement>(null);
  const replacementInput = useRef<HTMLInputElement>(null);

  const language = workspace?.language ?? 'ko';
  const c = copy(language);
  const exportLanguage = reportLanguage === 'interface' ? language : reportLanguage;
  useEffect(() => { document.documentElement.lang = language; }, [language]);

  function restoreClient(state: ClientWorkspace) {
    editGeneration.current += 1; setViewerEpoch((epoch) => epoch + 1);
    setAuxiliaryBySource(state.auxiliary); setDrafts(state.drafts); setViewerStates(state.viewers);
    setComparison(state.comparison); setCompareBefore(state.before); setCompareAfter(state.after);
    setView(state.view); setConflictedEdit(null); setUnsaved(false);
  }

  function confirmReplace() {
    return !unsaved || window.confirm(language === 'ko'
      ? '저장하지 않은 작업을 바꾸시겠습니까? 현재 작업을 이어가려면 먼저 작업 저장을 해 주세요.'
      : 'Replace the unsaved workspace? Save the project first to keep this work.');
  }

  useEffect(() => {
    if (!unsaved) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [unsaved]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await bootstrap();
      restoreClient(restoreClientWorkspace(next)); setWorkspace(next); setNotice(null);
    }
    catch (error) { setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) }); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const act = useCallback(async (action: Record<string, unknown>) => {
    if (!workspace || busy) return null;
    if (action.type === 'load_example' && !confirmReplace()) return null;
    setBusy(true); setNotice(null);
    try {
      const next = await dispatchAction(workspace, action);
      setWorkspace(next);
      if (action.type === 'load_example') restoreClient(restoreClientWorkspace(next));
      else markUnsaved();
      if (action.type === 'patch_entry') {
        setConflictedEdit(null);
        const updated = next.entries.find((entry) => entry.id === action.id);
        if (updated) setDrafts((current) => ({ ...current, [updated.id]: entryDraft(updated) }));
      }
      return next;
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        if (action.type === 'patch_entry') setConflictedEdit({ ...action });
        try { setWorkspace(await reloadWorkspace()); } catch { /* report original conflict */ }
        setNotice({ tone: 'info', message: c.conflict });
      } else {
        setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
      }
      return null;
    } finally { setBusy(false); }
  }, [workspace, busy, c.conflict, unsaved, language]);

  const selected = useMemo(() => workspace?.entries.find((entry) => entry.id === workspace.project.selected_id) ?? workspace?.entries[0] ?? null, [workspace]);
  const report = selected?.analysis.report ?? null;
  const activeSources = useRef(new Set<string>());
  activeSources.current = new Set(workspace?.entries.map((entry) => entry.sha256) ?? []);
  useEffect(() => {
    const sources = new Set(workspace?.entries.map((entry) => entry.sha256) ?? []);
    setAuxiliaryBySource((previous) => Object.keys(previous).every((key) => sources.has(key))
      ? previous : Object.fromEntries(Object.entries(previous).filter(([key]) => sources.has(key))));
  }, [workspace?.entries]);
  useEffect(() => {
    setDrafts((previous) => Object.fromEntries((workspace?.entries ?? []).map((entry) =>
      [entry.id, reconcileDraft(Object.hasOwn(previous, entry.id) ? previous[entry.id] : undefined, entry)])));
  }, [workspace?.entries]);

  const changeViewer = useCallback((key: string, state: ViewerState) => {
    const previous = viewerStatesRef.current[key];
    if (previous && JSON.stringify(previous) !== JSON.stringify(state)) markUnsaved();
    setViewerStates((previous) => {
      if (JSON.stringify(previous[key]) === JSON.stringify(state)) return previous;
      return { ...previous, [key]: state };
    });
  }, []);
  const selectedState = selected ? entryState(selected) : 'unsupported';
  const minimumIssues = report?.issues.filter((issue) => ['OVERLAPPING_SITES', 'SHORT_DISTANCE', 'SELF_IMAGE_CONTACT'].includes(issue.code)) ?? [];
  const minimumState = !report || minimumIssues.some((issue) => issue.severity === 'error') ? 'unsupported'
    : minimumIssues.some((issue) => issue.severity === 'warning') ? 'review' : 'clear';
  const gapState = !report ? 'unsupported' : report.gap_review_required ? 'review' : 'clear';
  const localizedIssues = selected && language === 'ko' && selected.analysis.issues_ko?.length
    ? selected.analysis.issues_ko : report?.issues ?? [];
  const reviewIssueCount = localizedIssues.filter((issue) => issue.severity === 'warning' || issue.severity === 'error').length;

  useEffect(() => {
    if (!selected) return;
    setMeasurement(null); setMeasuredSelection(null); setPicked([]); setInspectedIssue(null);
    setFirstIndex('0'); setSecondIndex(String(Math.min(1, (selected.analysis.report?.atom_count ?? 1) - 1)));
    setFirstShift(['0', '0', '0']); setSecondShift(['0', '0', '0']); setPairMode('minimum_image');
  }, [selected?.id, selected?.sha256, selected?.normal_axis, selected?.short_distance]);

  useEffect(() => {
    if (!workspace?.examples.length) return;
    setSampleName((current) => workspace.examples.some((example) => example.name === current) ? current : workspace.examples[0].name);
  }, [workspace?.examples]);

  useEffect(() => {
    if (!workspace?.entries.length) return;
    const ids = workspace.entries.map((entry) => entry.id);
    setCompareBefore((current) => ids.includes(current) ? current : ids[0]);
    setCompareAfter((current) => ids.includes(current) ? current : (ids[1] ?? ids[0]));
  }, [workspace?.entries]);

  const visibleEntries = useMemo(() => {
    if (!workspace) return [];
    return workspace.entries.filter((entry) => {
      const state = entryState(entry);
      const geometry = workspace.project.filter_mode;
      const progress = workspace.project.progress_filter;
      return (geometry === 'all' || (geometry === 'needs_review' && state === 'review') || (geometry === 'unsupported' && state === 'unsupported'))
        && (progress === 'all' || (progress === 'reviewed' && entry.reviewed) || (progress === 'unreviewed' && !entry.reviewed));
    });
  }, [workspace]);

  const activeIssue = useMemo(() => {
    if (inspectedIssue) return inspectedIssue;
    const focus = workspace?.project.review_focus;
    if (!report || !focus || focus === 'overview' || focus === 'minimum') return null;
    const tokens: Record<string, string[]> = {
      overlap: ['OVERLAP'], short: ['SHORT'], gap: ['GAP', 'AMBIGUOUS_SLAB'], metadata: ['OCCUPANCY', 'SYMMETRY', 'METADATA'],
    };
    return report.issues.find((issue) => (tokens[focus] ?? []).some((token) => issue.code.includes(token))) ?? null;
  }, [workspace?.project.review_focus, report, inspectedIssue]);
  const focusContact: Contact | null = measurement ? measurement[pairMode]
    : workspace?.project.review_focus === 'minimum' ? report?.metrics.minimum_pair ?? null
    : activeIssue?.representative_contact ?? null;
  const highlightGap = workspace?.project.review_focus === 'gap';
  const highlightedAtomIndices = activeIssue?.atom_indices;

  async function importCifs(files: FileList | null, mode: 'replace' | 'append') {
    if (!workspace || busy || !files?.length) return;
    if (mode === 'replace' && !confirmReplace()) return;
    const all = Array.from(files);
    if (all.length + (mode === 'append' ? workspace.entries.length : 0) > workspace.limits.max_files) {
      setNotice({ tone: 'error', message: `${workspace.limits.max_files} files maximum.` }); return;
    }
    const tooLarge = all.find((file) => file.size > workspace.limits.max_file_bytes);
    if (tooLarge) { setNotice({ tone: 'error', message: `${tooLarge.name}: file is too large.` }); return; }
    setBusy(true);
    try {
      const encoded = await Promise.all(all.map(async (file) => ({ filename: file.name, data_base64: await fileToBase64(file) })));
      const next = await dispatchAction(workspace, { type: 'import_cifs', files: encoded, mode });
      if (mode === 'replace') restoreClient(restoreClientWorkspace(next));
      setWorkspace(next); setNotice(null); markUnsaved();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setWorkspace(await reloadWorkspace()); setNotice({ tone: 'info', message: c.conflict });
      } else setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally { setBusy(false); }
  }

  async function openProject(file: File | undefined) {
    if (!workspace || busy || !file) return;
    if (!confirmReplace()) return;
    if (file.size > 128 * 1024 * 1024) {
      setNotice({ tone: 'error', message: language === 'ko' ? '작업 파일은 128 MiB 이하여야 합니다.' : 'Project files must be at most 128 MiB.' }); return;
    }
    setBusy(true);
    try {
      const bytes = await file.arrayBuffer();
      const preview = await importProject(workspace, bytes, true);
      const restored = restoreClientWorkspace(preview);
      const next = await importProject(workspace, bytes);
      restoreClient(restored); setWorkspace(next); setNotice(null);
    }
    catch (error) {
      if (error instanceof ApiError && error.status === 409) { setWorkspace(await reloadWorkspace()); setNotice({ tone: 'info', message: c.conflict }); }
      else setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally { setBusy(false); }
  }

  async function saveProject() {
    if (!workspace || busy) return;
    const savedGeneration = editGeneration.current;
    setBusy(true); setNotice(null);
    try {
      const state = serializeClientWorkspace({ auxiliary: auxiliaryBySource, viewers: viewerStates,
        drafts, comparison, before: compareBefore, after: compareAfter, view }, workspace.entries);
      const blob = await exportProject(workspace, state);
      const url = URL.createObjectURL(blob); const link = document.createElement('a');
      link.href = url; link.download = 'calclens-project.calclens.zip'; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1_000);
      if (editGeneration.current === savedGeneration) setUnsaved(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setWorkspace(await reloadWorkspace()); setNotice({ tone: 'info', message: c.conflict });
      } else setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally { setBusy(false); }
  }

  async function replaceSource(file: File | undefined) {
    if (!workspace || !selected || busy || !file) return;
    if (file.size > workspace.limits.max_file_bytes) { setNotice({ tone: 'error', message: `${file.name}: file is too large.` }); return; }
    await act({ type: 'replace_source', id: selected.id, filename: file.name, data_base64: await fileToBase64(file) });
  }

  async function calculatePair(selection?: PairSelection) {
    if (!workspace || !selected || !report || busy) return;
    const i = selection?.i ?? Number(firstIndex);
    const j = selection?.j ?? Number(secondIndex);
    const a = selection?.first_shift ?? parseShift(firstShift);
    const b = selection?.second_shift ?? parseShift(secondShift);
    if ([...a, ...b].some((value) => !Number.isInteger(value) || Math.abs(value) > 9)) {
      setNotice({ tone: 'error', message: language === 'ko' ? '이미지 이동은 -9부터 9까지의 정수로 입력하세요.' : 'Image shifts must be integers from -9 to 9.' }); return;
    }
    if (!Number.isInteger(i) || !Number.isInteger(j) || i < 0 || j < 0 || i >= report.atom_count || j >= report.atom_count || i === j) {
      setNotice({ tone: 'error', message: language === 'ko' ? `0부터 ${report.atom_count - 1}까지 서로 다른 정수 인덱스를 입력하세요.` : `Choose two different integer atom indices from 0 to ${report.atom_count - 1}.` }); return;
    }
    setBusy(true);
    try {
      setMeasurement(await measure(workspace, selected.id, i, j, a, b));
      setMeasuredSelection({ i, j, first_shift: a, second_shift: b, mode: selection?.mode ?? pairMode });
      setFirstIndex(String(i)); setSecondIndex(String(j));
      setFirstShift(a.map(String) as [string, string, string]); setSecondShift(b.map(String) as [string, string, string]);
      setPairMode(selection?.mode ?? pairMode); setNotice(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setMeasurement(null); setMeasuredSelection(null);
        try { setWorkspace(await reloadWorkspace()); } catch { /* retain the conflict message */ }
        setNotice({ tone: 'info', message: c.conflict });
      } else setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) });
    }
    finally { setBusy(false); }
  }

  function onAtomPick(atom: AtomPick) {
    if (busy) return;
    setMeasurement(null); setMeasuredSelection(null);
    const next = picked.length >= 2 ? [atom] : [...picked, atom];
    setPicked(next);
    if (next[0]) { setFirstIndex(String(next[0].index)); setFirstShift(next[0].shift.map(String) as [string, string, string]); }
    if (next[1]) { setSecondIndex(String(next[1].index)); setSecondShift(next[1].shift.map(String) as [string, string, string]); }
  }

  async function saveCurrentPair() {
    if (!selected || !measurement || !measuredSelection) return;
    await act({ type: 'save_measurement', id: selected.id, selection: measuredSelection });
  }

  function navigate(next: View) { if (view !== next) markUnsaved(); setView(next); window.scrollTo({ top: 0, behavior: 'smooth' }); }

  async function inspectFocus(focus: string, issue: Issue | null = null) {
    const result = await act({ type: 'patch_workspace', review_focus: focus });
    if (result) {
      setMeasurement(null); setMeasuredSelection(null); setInspectedIssue(issue);
      navigate('overview');
    }
  }

  if (loading && !workspace) return <main className="splash"><Aperture /><strong>CalcLens</strong><span>{c.loading}</span></main>;
  if (!workspace) return <main className="splash"><Aperture /><strong>CalcLens</strong><p className="error-text">{notice?.message}</p><button onClick={() => void load()}>{c.retry}</button></main>;

  const reviewedCount = workspace.entries.filter((entry) => entry.reviewed).length;
  const before = workspace.entries.find((entry) => entry.id === compareBefore) ?? null;
  const after = workspace.entries.find((entry) => entry.id === compareAfter) ?? null;

  return <div className="app-shell" data-testid="app-ready">
    <aside className="sidebar">
      <button className="brand" onClick={() => navigate('overview')}><Aperture /><span><b>CalcLens</b></span><small>COMPUTATIONAL CHEMISTRY</small></button>
      <nav aria-label="Primary navigation">
        <button className={view === 'overview' ? 'active' : ''} onClick={() => navigate('overview')}><Home />{c.overview}</button>
        <button data-testid="nav-compare" className={view === 'compare' ? 'active' : ''} onClick={() => navigate('compare')}><Compare />{c.compare}</button>
        <button className={view === 'review' ? 'active' : ''} onClick={() => navigate('review')}><CheckSquare />{c.review}</button>
        <button className={view === 'methods' ? 'active' : ''} onClick={() => navigate('methods')}><Book />{c.methods}</button>
      </nav>
      <div className="sidebar-spacer" />
      <button className="project-chip" onClick={() => navigate('overview')}>
        <Flask /><span><b>{selected?.filename ?? 'CalcLens project'}</b><small>{workspace.entries.length} CIF · {reviewedCount}/{workspace.entries.length} {c.reviewed}</small></span>
      </button>
      <div className="side-links"><a href="https://github.com/a123qsd/calclens#readme" target="_blank" rel="noreferrer"><Book />Documentation</a><a href="https://github.com/a123qsd/calclens" target="_blank" rel="noreferrer"><GitHub />GitHub</a></div>
      <small className="version">v{workspace.runtime?.calclens_version ?? workspace.project.calclens_version} · {workspace.runtime?.analysis_revision ?? workspace.project.analysis_revision}</small>
    </aside>

    <main className="workspace">
      <header className="topbar">
        <div><p className="breadcrumb">{c.workspace} / {selected?.filename}</p><h1>{view === 'overview' ? c.title : view === 'compare' ? c.compare : view === 'review' ? c.review : c.methods}</h1><p>{c.subtitle}</p></div>
        <div className="header-actions">
          <button className="button secondary" disabled={busy} onClick={() => projectInput.current?.click()}>{c.openProject}</button>
          <button data-testid="project-export-global" className="button secondary" disabled={busy} onClick={() => void saveProject()}><Download />{c.saveProject}</button>
          <button className="button secondary" onClick={() => cifInput.current?.click()} disabled={busy}><Upload />{c.open}</button>
          <div className="sample-control"><select aria-label={c.sample} value={sampleName} onChange={(event) => setSampleName(event.target.value)}>{workspace.examples.map((example) => <option value={example.name} key={example.name}>{language === 'ko' ? example.label_ko : example.label_en}</option>)}</select><button className="button primary" onClick={() => void act({ type: 'load_example', name: sampleName })} disabled={busy || !sampleName}><Play />{c.sample}</button></div>
          <button data-testid="language-toggle" disabled={busy} className="language" onClick={() => void act({ type: 'patch_workspace', language: language === 'ko' ? 'en' : 'ko' })} aria-label="Switch language"><b>{language === 'en' ? 'EN' : 'KR'}</b><span>/</span>{language === 'en' ? 'KR' : 'EN'}</button>
        </div>
      </header>

      <input data-testid="cif-replace-upload" hidden ref={cifInput} type="file" accept=".cif" multiple onChange={(event) => { void importCifs(event.target.files, 'replace'); event.target.value = ''; }} />
      <input hidden ref={addInput} type="file" accept=".cif" multiple onChange={(event) => { void importCifs(event.target.files, 'append'); event.target.value = ''; }} />
      <input data-testid="project-import" hidden ref={projectInput} type="file" accept=".json,.zip,.calclens.json,.calclens.zip,application/json,application/zip" onChange={(event) => { void openProject(event.target.files?.[0]); event.target.value = ''; }} />
      <input hidden ref={replacementInput} type="file" accept=".cif" onChange={(event) => { void replaceSource(event.target.files?.[0]); event.target.value = ''; }} />

      {notice && <div role="alert" className={`notice ${notice.tone}`}><Info /><span>{notice.message}</span><button onClick={() => setNotice(null)} aria-label={c.close}>×</button></div>}
      {workspace.entries.some((entry) => drafts[entry.id] && hasDraftChanges(drafts[entry.id], entry)) && <div className="notice info" role="status" data-testid="draft-status"><Info /><span>{language === 'ko' ? '적용 전 초안이 있습니다. 화면·파일을 바꾸어도 유지되며, 작업 저장에는 초안으로 포함됩니다. 분석 결과는 적용한 조건을 따릅니다.' : 'Unapplied drafts are preserved across screens and files and included in saved projects. Analysis uses the applied settings.'}</span></div>}
      {conflictedEdit && <section className="notice info conflict-recovery"><div><b>{language === 'ko' ? '충돌한 수정 내용을 보관했습니다' : 'Your conflicting edit is preserved'}</b><p>{String(conflictedEdit.normal_axis ?? '')} · {String(conflictedEdit.short_distance ?? '')} Å</p><textarea aria-label={language === 'ko' ? '보관한 메모' : 'Preserved note'} readOnly value={String(conflictedEdit.note ?? '')} /><button disabled={busy || !workspace.entries.some((entry) => entry.id === conflictedEdit.id)} onClick={() => void act(conflictedEdit)}>{language === 'ko' ? '확인한 내용 다시 적용' : 'Reapply after review'}</button><button onClick={() => setConflictedEdit(null)}>{c.close}</button></div></section>}
      {workspace.runtime && (workspace.project.analysis_revision !== workspace.runtime.analysis_revision || workspace.project.ase_version !== workspace.runtime.ase_version || workspace.project.calclens_version !== workspace.runtime.calclens_version) && <div className="notice info" role="status"><Info /><span>{language === 'ko' ? '저장 당시와 현재 버전이 다릅니다. 보고서를 다시 계산했으며, 원본·조건·계산 방식이 같은 검토 기록은 유지합니다.' : 'This project was saved with a different version. Reports were recalculated; reviews with matching inputs, settings and analysis remain current.'}</span></div>}
      {busy && <div className="progress" aria-label="Working"><span /></div>}

      {view === 'overview' && <>
        <section className="truth-banner"><Info /><strong>{language === 'ko' ? '실제 구조 선별' : 'Actual structure screening'}</strong><span /><p className="truth-description">{c.methodNote}</p></section>
        <section className="metrics-grid">
          <MetricCard label={c.minimum} value={finite(report?.metrics.minimum_distance_angstrom)} hint={report ? `${report.metrics.minimum_pair.element_i}${report.metrics.minimum_pair.i + 1} ↔ ${report.metrics.minimum_pair.element_j}${report.metrics.minimum_pair.j + 1}` : c.unsupported} tone={selectedState === 'clear' ? 'teal' : 'amber'} />
          <MetricCard label={c.thickness} value={finite(report?.metrics.nuclei_thickness_angstrom)} hint={report ? `${report.normal_axis} ${c.axes} · ${report.atom_count} ${c.atoms}` : c.unsupported} />
          <MetricCard label={c.gap} value={finite(report?.metrics.nuclei_gap_angstrom)} hint={report?.gap_review_required ? c.needsReview : (language === 'ko' ? '기하학적 후보 간격' : 'Geometric candidate')} tone={report?.gap_review_required ? 'amber' : 'teal'} />
        </section>

        <section className={`overview-grid ${reviewPanelOpen ? '' : 'overview-grid--wide'}`}>
          <article className="card viewer-card">
            <div className="card-heading"><div><h2>{c.structure}</h2><span>{c.actual}</span></div><div className="viewer-heading-actions"><StatusPill entry={selected!} language={language} /><button type="button" data-testid="review-panel-toggle" aria-expanded={reviewPanelOpen} aria-controls="overview-review-panel" onClick={() => setReviewPanelOpen((value) => !value)}>{reviewPanelOpen ? (language === 'ko' ? '검토 패널 접기' : 'Hide review panel') : (language === 'ko' ? '검토 패널 보기' : 'Show review panel')}</button></div></div>
            {report ? <MolecularViewer key={`${viewerEpoch}:${viewerKey(selected!)}`} report={report} language={language} highlight={focusContact} highlightGap={highlightGap} highlightedAtomIndices={highlightedAtomIndices} onAtomPick={onAtomPick} auxiliary={auxiliaryBySource[selected!.sha256]} state={viewerStates[viewerKey(selected!)]} onStateChange={(state) => changeViewer(viewerKey(selected!), state)} /> : <div data-testid="unsupported-empty" className="empty-view"><Info /><strong>{(language === 'ko' ? selected?.analysis.error_ko : selected?.analysis.error) ?? selected?.analysis.error ?? c.unsupported}</strong></div>}
            <div className="viewer-filename" title={selected?.filename}>{selected?.filename}</div>
          </article>

          <article id="overview-review-panel" className="card review-card" hidden={!reviewPanelOpen}>
            <div className="card-heading"><h2>{c.checks}</h2><span>{reviewedCount}/{workspace.entries.length}</span></div>
            <button className="check-row" onClick={() => void inspectFocus('minimum')}><StatusMark state={minimumState} /><span><b>{c.minimum}</b><small>{finite(report?.metrics.minimum_distance_angstrom, 4)}</small></span></button>
            <button className="check-row" onClick={() => void inspectFocus('gap')}><StatusMark state={gapState} /><span><b>{c.gap}</b><small>{!report ? c.unsupported : report.gap_review_required ? c.needsReview : c.clear}</small></span></button>
            <button className="check-row" onClick={() => navigate('review')}><StatusMark state={selectedState} /><span><b>{language === 'ko' ? '구조 경고' : 'Geometry warnings'}</b><small>{reviewIssueCount} {language === 'ko' ? '개' : 'found'}</small></span></button>
            <button data-testid="reviewed-toggle" className="check-row" onClick={() => void act({ type: 'set_reviewed', id: selected!.id, value: !selected!.reviewed })}><StatusMark state={selected?.reviewed && selected.review_current ? 'clear' : 'review'} /><span><b>{c.markReviewed}</b><small>{selected?.reviewed ? c.reviewed : c.unreviewed}</small></span></button>
            <div className={`review-callout ${selectedState === 'clear' ? 'methodology' : ''}`}><Info /><div><b>{selectedState === 'clear' ? (language === 'ko' ? '판정 범위' : 'Screening scope') : c.needsReview}</b><p>{selectedState === 'clear' ? c.methodNote : localizedIssues.find((issue) => issue.severity !== 'info')?.message ?? selected?.analysis.error ?? c.methodNote}</p></div></div>
            {report && <a className="evidence-link" href={reportUrl(selected!.id, 'json', exportLanguage)} target="_blank"><External />{c.evidence}</a>}
          </article>
        </section>

        <Records workspace={workspace} entries={visibleEntries} selected={selected} language={language} act={act} />

        <WorkspaceTools
          workspace={workspace} selected={selected!} act={act} busy={busy} language={language}
          replacementInput={replacementInput} addInput={addInput} projectInput={projectInput}
          calculatePair={calculatePair} measurement={measurement} pairMode={pairMode} setPairMode={(mode) => { setPairMode(mode); setMeasuredSelection((value) => value ? { ...value, mode } : null); }}
          firstIndex={firstIndex} setFirstIndex={(value) => { setFirstIndex(value); setMeasurement(null); setMeasuredSelection(null); }} secondIndex={secondIndex} setSecondIndex={(value) => { setSecondIndex(value); setMeasurement(null); setMeasuredSelection(null); }}
          firstShift={firstShift} setFirstShift={(value) => { setFirstShift(value); setMeasurement(null); setMeasuredSelection(null); }} secondShift={secondShift} setSecondShift={(value) => { setSecondShift(value); setMeasurement(null); setMeasuredSelection(null); }}
          saveCurrentPair={saveCurrentPair} measuredSelection={measuredSelection}
          draft={drafts[selected!.id] ?? entryDraft(selected!)}
          onDraftChange={(draft) => { setDrafts((previous) => ({ ...previous, [selected!.id]: draft })); markUnsaved(); }}
          saveProject={saveProject}
        />

        <PreparationPanel key={`prepare:${viewerEpoch}:${selected!.id}:${selected!.sha256}`} workspace={workspace} entry={selected!} language={language} busy={busy} act={act} />

        {report && selected && <AuxiliaryDataPanel key={`auxiliary:${viewerEpoch}:${selected.id}:${selected.sha256}`} report={report} sourceSha256={selected.sha256} language={language} data={auxiliaryBySource[selected.sha256]} onChange={(data) => {
          const sha = selected.sha256;
          if (activeSources.current.has(sha)) { setAuxiliaryBySource((previous) => ({ ...previous, [sha]: data })); markUnsaved(); }
        }} />}

      </>}

      {view === 'compare' && <ComparisonView workspace={workspace} language={language} before={before} after={after} beforeId={compareBefore} afterId={compareAfter} setBefore={(id) => { setCompareBefore(id); markUnsaved(); }} setAfter={(id) => { setCompareAfter(id); markUnsaved(); }} auxiliaryBySource={auxiliaryBySource} viewerStates={viewerStates} viewerEpoch={viewerEpoch} onViewerState={changeViewer} settings={comparison} onSettings={(settings) => { setComparison(settings); markUnsaved(); }} />}
      {view === 'review' && <ReviewView workspace={workspace} selected={selected!} issues={localizedIssues} language={language} act={act} onInspect={(issue) => void inspectFocus(focusForIssue(issue), issue)} />}
      {view === 'methods' && <MethodView selected={selected!} language={language} reportLanguage={reportLanguage} setReportLanguage={setReportLanguage} />}
      <footer>CalcLens · Local workflow · Inspectable results</footer>
    </main>
  </div>;
}

interface ToolsProps {
  workspace: Workspace; selected: Entry; language: Language; busy: boolean;
  act: (action: Record<string, unknown>) => Promise<Workspace | null>;
  replacementInput: RefObject<HTMLInputElement | null>; addInput: RefObject<HTMLInputElement | null>; projectInput: RefObject<HTMLInputElement | null>;
  calculatePair: (selection?: PairSelection) => Promise<void>; measurement: Measurement | null;
  pairMode: PairSelection['mode']; setPairMode: (mode: PairSelection['mode']) => void;
  firstIndex: string; setFirstIndex: (value: string) => void; secondIndex: string; setSecondIndex: (value: string) => void;
  firstShift: [string, string, string]; setFirstShift: (value: [string, string, string]) => void;
  secondShift: [string, string, string]; setSecondShift: (value: [string, string, string]) => void;
  saveCurrentPair: () => Promise<void>;
  measuredSelection: PairSelection | null;
  draft: EntryDraft;
  onDraftChange: (draft: EntryDraft) => void;
  saveProject: () => Promise<void>;
}

function WorkspaceTools(props: ToolsProps) {
  const { workspace, selected, language, busy, act } = props;
  const c = copy(language);
  const report = selected.analysis.report;
  const { axis: draftAxis, cutoff: draftCutoff, note: draftNote } = props.draft;
  const setDraftAxis = (axis: string) => props.onDraftChange({ ...props.draft, axis });
  const setDraftCutoff = (cutoff: string) => props.onDraftChange({ ...props.draft, cutoff });
  const setDraftNote = (note: string) => props.onDraftChange({ ...props.draft, note });
  const settingsChanged = hasDraftChanges(props.draft, selected);
  const shiftFields = (values: [string, string, string], setter: (value: [string, string, string]) => void, label: string) => <fieldset className="shift-fields"><legend>{label}</legend>{values.map((value, index) => <label key={index}>{['a', 'b', 'c'][index]}<input disabled={busy} type="number" min="-9" max="9" value={value} onChange={(event) => { const next = [...values] as [string, string, string]; next[index] = event.target.value; setter(next); }} /></label>)}</fieldset>;
  return <section className="tool-grid">
    <details className="tool-card"><summary><Sliders /><span><b>{c.settings}</b><small>{selected.normal_axis} · {selected.short_distance} Å</small></span></summary>
      <div className="tool-body two-column">
        <label>{c.normal}<select data-testid="selected-axis" disabled={busy} value={draftAxis} onChange={(event) => setDraftAxis(event.target.value)}><option>a</option><option>b</option><option>c</option></select></label>
        <label>{c.cutoff}<input data-testid="selected-cutoff" disabled={busy} type="number" min="0.1" max="3" step="0.05" value={draftCutoff} onChange={(event) => setDraftCutoff(event.target.value)} /></label>
        <label className="wide">{c.notes}<textarea data-testid="review-note" disabled={busy} maxLength={10000} value={draftNote} onChange={(event) => setDraftNote(event.target.value)} /></label>
        <div className="wide tool-actions">{settingsChanged && <small role="status">{language === 'ko' ? '아직 적용하지 않은 변경이 있습니다.' : 'There are unapplied changes.'}</small>}<button className="primary-action" disabled={!settingsChanged || busy || !draftCutoff.trim() || !Number.isFinite(Number(draftCutoff)) || Number(draftCutoff) < 0.1 || Number(draftCutoff) > 3} onClick={() => void act({ type: 'patch_entry', id: selected.id, normal_axis: draftAxis, short_distance: Number(draftCutoff), note: draftNote })}>{language === 'ko' ? '변경 적용' : 'Apply changes'}</button><button onClick={() => props.addInput.current?.click()}><Upload />{c.add}</button><button onClick={() => props.replacementInput.current?.click()}><Upload />{c.replace}</button><button onClick={() => props.projectInput.current?.click()}>{c.openProject}</button><button data-testid="project-export" disabled={busy} onClick={() => void props.saveProject()}><Download />{c.saveProject}</button><button className="danger" disabled={workspace.entries.length <= 1 || busy} onClick={() => { if (window.confirm(`${c.remove}: ${selected.filename}?`)) void act({ type: 'remove_entry', id: selected.id }); }}><Trash />{c.remove}</button></div>
      </div>
    </details>

    <details className="tool-card"><summary><Ruler /><span><b>{c.measurement}</b><small>{c.selectTwo}</small></span></summary>
      <div className="tool-body">
        <small>{language === 'ko' ? '인덱스는 0부터 시작합니다. 그림의 C1은 인덱스 0입니다.' : 'Indices start at 0. A viewer label such as C1 means index 0.'}</small><div className="index-fields"><label>{c.firstAtom}<input data-testid="measure-first-index" disabled={busy} type="number" min="0" max={(report?.atom_count ?? 1) - 1} value={props.firstIndex} onChange={(event) => props.setFirstIndex(event.target.value)} /></label><label>{c.secondAtom}<input data-testid="measure-second-index" disabled={busy} type="number" min="0" max={(report?.atom_count ?? 1) - 1} value={props.secondIndex} onChange={(event) => props.setSecondIndex(event.target.value)} /></label></div>
        <div className="shift-row">{shiftFields(props.firstShift, props.setFirstShift, c.firstAtom)}{shiftFields(props.secondShift, props.setSecondShift, c.secondAtom)}</div>
        <div className="mode-tabs"><button className={props.pairMode === 'minimum_image' ? 'active' : ''} onClick={() => props.setPairMode('minimum_image')}>{c.mic}</button><button className={props.pairMode === 'displayed' ? 'active' : ''} onClick={() => props.setPairMode('displayed')}>{c.displayed}</button></div>
        <div className="tool-actions"><button data-testid="measure-pair" className="primary-action" disabled={!report || busy} onClick={() => void props.calculatePair()}>{c.measure}</button><button data-testid="save-pair" disabled={!props.measurement || !props.measuredSelection || busy || selected.measurements.length >= workspace.limits.max_pair_selections} onClick={() => void props.saveCurrentPair()}>{c.savePair}</button></div>
        {props.measurement && <div className="measurement-result"><div><span>{c.mic}</span><b>{finite(props.measurement.minimum_image.distance_angstrom, 6)}</b><small>{shiftText(props.measurement.minimum_image.shift)}</small></div><div><span>{c.displayed}</span><b>{finite(props.measurement.displayed.distance_angstrom, 6)}</b><small>{shiftText(props.measurement.displayed.shift)}</small></div></div>}
        {selected.measurements.length > 0 && <div className="saved-pairs"><b>{c.savedPairs} · {selected.measurements.length}/{workspace.limits.max_pair_selections}</b>{selected.measurements.map((selection, index) => <div key={`${selection.i}-${selection.j}-${index}`}><button onClick={() => void props.calculatePair(selection)}>#{selection.i + 1} ↔ #{selection.j + 1} · {selection.mode === 'minimum_image' ? c.mic : c.displayed}</button><button aria-label={c.remove} onClick={() => void act({ type: 'remove_measurement', id: selected.id, index })}>×</button></div>)}</div>}
      </div>
    </details>
  </section>;
}

function Records({ workspace, entries, selected, language, act }: { workspace: Workspace; entries: Entry[]; selected: Entry | null; language: Language; act: (action: Record<string, unknown>) => Promise<Workspace | null> }) {
  const c = copy(language);
  return <section className="card records-card">
    <div className="card-heading records-heading"><h2>{c.records}</h2><div className="record-actions"><select data-testid="geometry-filter" aria-label={c.geometryFilter} value={workspace.project.filter_mode} onChange={(event) => void act({ type: 'patch_workspace', filter_mode: event.target.value })}><option value="all">{c.viewAll}</option><option value="needs_review">{c.viewReview}</option><option value="unsupported">{c.viewUnsupported}</option></select><select data-testid="progress-filter" aria-label={c.progressFilter} value={workspace.project.progress_filter} onChange={(event) => void act({ type: 'patch_workspace', progress_filter: event.target.value })}><option value="all">{c.all}</option><option value="unreviewed">{c.unreviewed}</option><option value="reviewed">{c.reviewed}</option></select><a className="button-link" href={`/api/v1/comparison.csv?lang=${language}`} download><Download />{c.exportCsv}</a></div></div>
    {entries.length ? <div className="table-wrap"><table><thead><tr><th>{c.file}</th><th>{c.formula}</th><th>{c.axes}</th><th>{c.atoms}</th><th>{c.status}</th><th>{c.reviewed}</th></tr></thead><tbody>{entries.map((entry) => <tr className={entry.id === selected?.id ? 'selected' : ''} key={entry.id} onClick={() => void act({ type: 'patch_workspace', selected_id: entry.id })}><td><button>{entry.filename}</button></td><td>{entry.analysis.report?.formula ?? '—'}</td><td>{entry.normal_axis}</td><td>{entry.analysis.report?.atom_count ?? '—'}</td><td><StatusPill entry={entry} language={language} /></td><td><button className={`review-toggle ${entry.reviewed ? 'done' : ''}`} onClick={(event) => { event.stopPropagation(); void act({ type: 'set_reviewed', id: entry.id, value: !entry.reviewed }); }}>{entry.reviewed ? <Check /> : '—'} {entry.reviewed ? c.reviewed : c.unreviewed}</button></td></tr>)}</tbody></table></div> : <div className="empty-records">{c.noResults}</div>}
  </section>;
}

function ComparisonView({ workspace, language, before, after, beforeId, afterId, setBefore, setAfter, auxiliaryBySource, viewerStates, viewerEpoch, onViewerState, settings, onSettings }: { workspace: Workspace; language: Language; before: Entry | null; after: Entry | null; beforeId: string; afterId: string; setBefore: (id: string) => void; setAfter: (id: string) => void; auxiliaryBySource: Record<string, ViewerAuxiliaryData>; viewerStates: Record<string, ViewerState>; viewerEpoch: number; onViewerState: (key: string, state: ViewerState) => void; settings: ComparisonSettings; onSettings: (settings: ComparisonSettings) => void }) {
  const c = copy(language);
  const synchronized = settings.sync;
  const setSynchronized = (sync: boolean) => onSettings({ ...settings, sync });
  const [leftViewer, setLeftViewer] = useState<GLViewer | null>(null);
  const [rightViewer, setRightViewer] = useState<GLViewer | null>(null);
  useEffect(() => {
    if (synchronized && leftViewer && rightViewer) return linkCameraViews(leftViewer, rightViewer);
  }, [synchronized, leftViewer, rightViewer]);
  const leftState = before ? viewerStates[viewerKey(before, 'left')] ?? defaultViewerState(true) : defaultViewerState(true);
  const rightState = after ? viewerStates[viewerKey(after, 'right')] ?? defaultViewerState(true) : defaultViewerState(true);
  const leftCharge = selectedCharge(before ? auxiliaryBySource[before.sha256] : undefined, leftState);
  const rightCharge = selectedCharge(after ? auxiliaryBySource[after.sha256] : undefined, rightState);
  const comparable = Boolean(leftCharge && rightCharge && leftCharge.kind === rightCharge.kind);
  const chargeRange = comparisonRange(settings, leftCharge, rightCharge);
  const selectors = (value: string, setter: (id: string) => void, label: string, testId: string) => <label>{label}<select data-testid={testId} value={value} onChange={(event) => setter(event.target.value)}>{workspace.entries.map((entry) => <option value={entry.id} key={entry.id}>{entry.filename}</option>)}</select></label>;
  return <>
    <section className="compare-controls card"><div>{selectors(beforeId, setBefore, c.before, 'compare-before')}{selectors(afterId, setAfter, c.after, 'compare-after')}</div><label className="compare-sync"><span><input data-testid="compare-sync" type="checkbox" checked={synchronized} onChange={(event) => setSynchronized(event.target.checked)} />{language === 'ko' ? '회전·확대 동기화' : 'Sync rotation & zoom'}</span><small>{language === 'ko' ? '각 구조의 중심 유지 · 자동 구조 정렬 아님' : 'Keeps each center · no automatic structure alignment'}</small></label><a className="button-link" href={`/api/v1/comparison.csv?lang=${language}`} download><Download />{c.exportCsv}</a></section>
    <section className="card compare-range" data-testid="compare-range-panel">
      <label>{language === 'ko' ? '전하 색상 범위' : 'Charge color range'}<select data-testid="compare-range-mode" value={settings.rangeMode} onChange={(event) => onSettings({ ...settings, rangeMode: event.target.value as ComparisonSettings['rangeMode'] })}>
        <option value="auto">{language === 'ko' ? '각 자료에 맞춰 자동 설정' : 'Automatic for each dataset'}</option><option value="shared">{language === 'ko' ? '두 화면에 공통 범위 적용' : 'Shared across both views'}</option><option value="manual">{language === 'ko' ? '최솟값·최댓값 지정' : 'Manual minimum / maximum'}</option>
      </select></label>
      {settings.rangeMode === 'manual' && <div className="range-fields"><label>{language === 'ko' ? '최솟값 (0 미만)' : 'Minimum (below zero)'}<input data-testid="compare-range-min" type="number" step="any" value={settings.manualMin} onChange={(event) => onSettings({ ...settings, manualMin: event.target.value })} /></label><label>{language === 'ko' ? '최댓값 (0 초과)' : 'Maximum (above zero)'}<input data-testid="compare-range-max" type="number" step="any" value={settings.manualMax} onChange={(event) => onSettings({ ...settings, manualMax: event.target.value })} /></label></div>}
      {settings.rangeMode !== 'auto' && !comparable && <small>{language === 'ko' ? '양쪽에서 같은 종류의 전하 자료를 선택하면 공통 범위가 적용됩니다.' : 'Select the same charge quantity in both views to use a common range.'}</small>}
      {comparable && settings.rangeMode === 'manual' && !chargeRange && <p role="alert">{language === 'ko' ? '0보다 작은 최솟값과 0보다 큰 최댓값을 입력하세요. 현재는 각 자료의 자동 범위를 사용합니다.' : 'Enter a negative minimum and positive maximum. Each dataset uses its automatic range until these are valid.'}</p>}
      {chargeRange && <small data-testid="shared-range">{chargeRange[0]} … {chargeRange[1]} {leftCharge?.kind === 'oxidation_state' ? '' : 'e'} · {language === 'ko' ? '양쪽 동일 기준 · 계산 방법은 자료별로 확인하세요' : 'Same scale in both views · check each dataset’s method'}</small>}
    </section>
    <section className="comparison-grid">{[before, after].map((entry, index) => <article data-testid={`compare-card-${index}`} className="card compare-card" key={`${entry?.id}-${index}`}><div className="card-heading"><div><h2>{index ? c.after : c.before}</h2><span title={entry?.filename}>{entry?.filename}</span></div>{entry && <StatusPill entry={entry} language={language} />}</div>{entry?.analysis.report ? <MolecularViewer key={`${viewerEpoch}:${viewerKey(entry, index ? 'right' : 'left')}`} report={entry.analysis.report} language={language} compact auxiliary={auxiliaryBySource[entry.sha256]} state={viewerStates[viewerKey(entry, index ? 'right' : 'left')]} onStateChange={(state) => onViewerState(viewerKey(entry, index ? 'right' : 'left'), state)} chargeRange={chargeRange} onViewerReady={index === 0 ? setLeftViewer : setRightViewer} /> : <div className="empty-view">{entry?.analysis.error ?? c.unsupported}</div>}<MetricRows entry={entry} language={language} /></article>)}</section>
    <ComparisonDetails before={before} after={after} language={language} />
  </>;
}

function MetricRows({ entry, language }: { entry: Entry | null; language: Language }) {
  const c = copy(language); const m = entry?.analysis.report?.metrics;
  return <div className="metric-rows"><div><span>{c.minimum}</span><b>{finite(m?.minimum_distance_angstrom)}</b></div><div><span>{c.thickness}</span><b>{finite(m?.nuclei_thickness_angstrom)}</b></div><div><span>{c.gap}</span><b>{finite(m?.nuclei_gap_angstrom)}</b></div></div>;
}

function ComparisonDetails({ before, after, language }: { before: Entry | null; after: Entry | null; language: Language }) {
  const c = copy(language); const a = before?.analysis.report; const b = after?.analysis.report;
  const row = (label: string, av: number | undefined, bv: number | undefined) => <tr><th>{label}</th><td>{finite(av)}</td><td>{finite(bv)}</td><td>{Number.isFinite(av) && Number.isFinite(bv) ? `${(bv! - av!).toFixed(3)} Å` : '—'}</td></tr>;
  return <section className="card comparison-details"><h2>{language === 'ko' ? '구조 차이' : 'Structure differences'}</h2><div className="table-wrap"><table><thead><tr><th>{language === 'ko' ? '지표' : 'Metric'}</th><th>{c.before}</th><th>{c.after}</th><th>Δ</th></tr></thead><tbody><tr><th>{c.formula}</th><td>{a?.formula ?? '—'}</td><td>{b?.formula ?? '—'}</td><td>—</td></tr><tr><th>{c.atoms}</th><td>{a?.atom_count ?? '—'}</td><td>{b?.atom_count ?? '—'}</td><td>{a && b ? b.atom_count - a.atom_count : '—'}</td></tr>{row(c.minimum, a?.metrics.minimum_distance_angstrom, b?.metrics.minimum_distance_angstrom)}{row(c.thickness, a?.metrics.nuclei_thickness_angstrom, b?.metrics.nuclei_thickness_angstrom)}{row(c.gap, a?.metrics.nuclei_gap_angstrom, b?.metrics.nuclei_gap_angstrom)}<tr><th>{language === 'ko' ? '셀 벡터' : 'Cell vectors'}</th><td className="cell-value">{a?.cell.map((v) => v.map((x) => x.toFixed(3)).join(', ')).join(' · ') ?? '—'}</td><td className="cell-value">{b?.cell.map((v) => v.map((x) => x.toFixed(3)).join(', ')).join(' · ') ?? '—'}</td><td>—</td></tr><tr><th>{c.review}</th><td>{a?.issues.length ?? '—'}</td><td>{b?.issues.length ?? '—'}</td><td>{a && b ? b.issues.length - a.issues.length : '—'}</td></tr></tbody></table></div></section>;
}

function ReviewView({ workspace, selected, issues, language, act, onInspect }: { workspace: Workspace; selected: Entry; issues: Issue[]; language: Language; act: (action: Record<string, unknown>) => Promise<Workspace | null>; onInspect: (issue: Issue) => void }) {
  const c = copy(language);
  return <section className="review-layout"><article className="card review-list"><div className="card-heading"><div><h2>{selected.filename}</h2><span>{selected.analysis.report?.formula}</span></div><StatusPill entry={selected} language={language} /></div>{!selected.analysis.report ? <div className="issue issue-error"><StatusMark state="unsupported" /><p>{(language === 'ko' ? selected.analysis.error_ko : selected.analysis.error) ?? selected.analysis.error ?? c.unsupported}</p></div> : issues.length ? issues.map((issue, index) => <button className={`issue issue-${issue.severity}`} key={`${issue.code}-${index}`} onClick={() => onInspect(issue)}><StatusMark state={issue.severity === 'error' ? 'unsupported' : issue.severity === 'info' ? 'info' : 'review'} /><div><b>{issue.code.replaceAll('_', ' ')}</b><p>{issue.message}</p>{issue.representative_contact && <small>#{issue.representative_contact.i + 1} ↔ #{issue.representative_contact.j + 1} · {finite(issue.representative_contact.distance_angstrom, 6)}</small>}</div></button>) : <div className="all-clear"><Check /><h3>{c.clear}</h3><p>{c.methodNote}</p></div>}</article><aside className="card file-rail"><h2>{c.records}</h2>{workspace.entries.map((entry) => <button className={entry.id === selected.id ? 'active' : ''} key={entry.id} onClick={() => void act({ type: 'patch_workspace', selected_id: entry.id })}><StatusMark state={entryState(entry)} /><span><b>{entry.filename}</b><small>{entry.analysis.report?.formula ?? c.unsupported}</small></span></button>)}</aside></section>;
}

function MethodView({ selected, language, reportLanguage, setReportLanguage }: { selected: Entry; language: Language; reportLanguage: Language | 'interface'; setReportLanguage: (language: Language | 'interface') => void }) {
  const c = copy(language); const report = selected.analysis.report;
  const exportLanguage = reportLanguage === 'interface' ? language : reportLanguage;
  const assumptions = language === 'ko' ? selected.analysis.assumptions_ko ?? report?.assumptions : report?.assumptions;
  const limitations = language === 'ko' ? selected.analysis.limitations_ko ?? report?.limitations : report?.limitations;
  return <section className="method-grid"><article className="card prose-card"><h2>{c.methods}</h2><p className="lead">{c.methodNote}</p><h3>{language === 'ko' ? '가정' : 'Assumptions'}</h3><ul>{assumptions?.map((item) => <li key={item}>{item}</li>)}</ul><h3>{language === 'ko' ? '한계' : 'Limitations'}</h3><ul>{limitations?.map((item) => <li key={item}>{item}</li>)}</ul></article><aside className="card provenance-card"><h2>{language === 'ko' ? '재현 정보' : 'Reproducibility'}</h2><dl><dt>SHA-256</dt><dd>{selected.sha256}</dd><dt>{c.normal}</dt><dd>{selected.normal_axis}</dd><dt>{c.cutoff}</dt><dd>{selected.short_distance} Å</dd><dt>{c.reviewed}</dt><dd>{selected.review_current ? c.current : selected.reviewed ? c.needsReview : c.unreviewed}</dd></dl><label>{language === 'ko' ? '보고서 언어' : 'Report language'}<select value={reportLanguage} onChange={(event) => setReportLanguage(event.target.value as Language | 'interface')}><option value="interface">{language === 'ko' ? '화면 언어와 같게' : 'Same as interface'}</option><option value="ko">한국어</option><option value="en">English</option></select></label>{report && <><a className="button-link" href={reportUrl(selected.id, 'json', exportLanguage)} download><Download />JSON</a><a className="button-link" href={reportUrl(selected.id, 'csv', exportLanguage)} download><Download />CSV</a></>}{selected.review_stamp && <details className="review-history"><summary>{language === 'ko' ? '이전 검토 기록' : 'Recorded review'}</summary><dl>{Object.entries(selected.review_stamp).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value ?? '—')}</dd></div>)}</dl></details>}</aside></section>;
}
