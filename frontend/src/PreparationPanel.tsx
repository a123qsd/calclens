import { useState } from 'react';
import { previewPreparation } from './api.ts';
import type { PreparationPreview } from './api.ts';
import type { Entry, Language, Workspace } from './types.ts';

interface Props {
  workspace: Workspace; entry: Entry; language: Language; busy: boolean;
  act: (action: Record<string, unknown>) => Promise<Workspace | null>;
}

const koreanNotices: Record<string, string> = {
  'Symmetry-equivalent sites expanded in the original conventional cell.': '원본 관습 단위 셀 안에서 대칭적으로 같은 위치를 전개했습니다.',
  'All resulting sites written explicitly as P1 with occupancy 1.': '전개된 모든 원자 위치를 점유율 1의 P1 구조로 명시했습니다.',
  'Original cell retained; no vacuum, layer selection, or relaxation performed.': '원본 셀을 유지했으며 진공 추가·층 선택·구조 최적화는 수행하지 않았습니다.',
  'The original cell is retained. This is symmetry expansion, not slab construction or relaxation.': '원본 셀에서 대칭 위치만 전개합니다. 슬랩 제작이나 구조 최적화를 수행하지 않습니다.',
  'Equivalent symmetry images are identified within at most 0.001 angstrom; deposited representative coordinates are retained.': '최대 0.001 Å 이내의 대칭적 중복 위치를 확인하며, 원본의 대표 좌표는 유지합니다.',
  'Occupancy was omitted; the coreCIF default 1.0 is made explicit for every resulting site.': '원본에 점유율이 없어 coreCIF 기본값 1.0을 적용하고 모든 원자 위치에 명시했습니다.',
  'Symmetry operations are generated from the explicit ASE standard-setting space group.': '원본에 명시된 공간군의 ASE 표준 설정으로 대칭 연산을 생성했습니다.',
};

export default function PreparationPanel({ workspace, entry, language, busy, act }: Props) {
  const ko = language === 'ko';
  const [preview, setPreview] = useState<PreparationPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  async function inspect() {
    setLoading(true); setError(''); setPreview(null);
    try { setPreview(await previewPreparation(workspace, entry.id)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }
  return <details className="tool-card preparation-panel" data-testid="p1-panel">
    <summary><span><b>{ko ? 'P1 구조 준비' : 'Prepare a P1 structure'}</b><small>{ko ? '대칭 전개 결과를 확인하고 적용합니다' : 'Preview symmetry expansion before applying'}</small></span></summary>
    <div className="tool-body">
      <p>{ko ? '완전 점유이며 무질서가 없는 CIF를 원자 위치가 전개된 P1 구조로 준비합니다. 원본과 변환 이력은 작업 파일에 함께 저장합니다. 부분 점유·무질서 구조는 지원하지 않습니다.' : 'Expand fully occupied, ordered CIF sites into P1. The original and conversion history are included in the project. Partial occupancy and disorder are unsupported.'}</p>
      <button data-testid="p1-preview" disabled={busy || loading} onClick={() => void inspect()}>{loading ? (ko ? '확인 중…' : 'Checking…') : (ko ? '변환 미리보기' : 'Preview conversion')}</button>
      {error && <p role="alert" className="error-text">{error}</p>}
      {preview && <div data-testid="p1-result">
        <dl><dt>{ko ? '공간군' : 'Space group'}</dt><dd>{preview.source_spacegroup.symbol ?? '—'} ({preview.source_spacegroup.number ?? '—'}) → P1</dd>
          <dt>{ko ? '원자 수' : 'Atom count'}</dt><dd>{preview.source_site_count} → {preview.prepared_site_count}</dd>
          <dt>{ko ? '원본 셀 (Å, °)' : 'Original cell (Å, °)'}</dt><dd>{preview.source_cell.map((value) => value.toFixed(5)).join(' · ')}</dd>
          <dt>{ko ? '준비된 셀 (Å, °)' : 'Prepared cell (Å, °)'}</dt><dd>{preview.prepared_cell.map((value) => value.toFixed(5)).join(' · ')}</dd></dl>
        <ul>{[...preview.changes, ...preview.warnings].map((item, index) => <li key={index}>{ko ? koreanNotices[item] ?? item : item}</li>)}</ul>
        <button data-testid="p1-apply" disabled={busy || loading || preview.source_sha256 !== entry.sha256} onClick={async () => {
          const next = await act({ type: 'prepare_p1', id: entry.id, source_sha256: preview.source_sha256 });
          if (next) setPreview(null);
        }}>{ko ? '준비된 P1 구조 적용' : 'Apply prepared P1 structure'}</button>
      </div>}
      {entry.preparation && <p role="status">{ko ? '이 구조의 원본과 P1 변환 이력이 보관되어 있습니다.' : 'The original and P1 conversion history are retained for this structure.'}</p>}
    </div>
  </details>;
}
