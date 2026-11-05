import { useEffect, useRef, useState } from 'react';
import type { GeometryReport, Language } from './types';
import {
  MAX_CHARGE_BYTES, MAX_CUBE_BYTES, MAX_AUXILIARY_DATASETS, appendAuxiliaryDataset,
  makeChargeTemplate, parseChargeData, parseCubeData,
} from './viewerData';
import type { ChargeKind, ViewerAuxiliaryData } from './viewerData';

interface Props {
  report: GeometryReport;
  sourceSha256: string;
  language: Language;
  data?: ViewerAuxiliaryData;
  onChange: (data: ViewerAuxiliaryData) => void;
}

const names = {
  ko: { partial_charge: '부분전하', ionic_charge: '이온 순전하', formal_charge: '형식 전하', oxidation_state: '산화수' },
  en: { partial_charge: 'Partial charge', ionic_charge: 'Ionic net charge', formal_charge: 'Formal charge', oxidation_state: 'Oxidation state' },
};

export default function AuxiliaryDataPanel({ report, sourceSha256, language, data, onChange }: Props) {
  const ko = language === 'ko';
  const [chargeKind, setChargeKind] = useState<ChargeKind>('partial_charge');
  const [chargeName, setChargeName] = useState('');
  const [volumeKind, setVolumeKind] = useState<'density' | 'orbital'>('density');
  const [volumeUnits, setVolumeUnits] = useState('e/bohr^3');
  const [volumeSource, setVolumeSource] = useState('');
  const [volumeName, setVolumeName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const dataRef = useRef(data);
  dataRef.current = data;
  useEffect(() => () => { generation.current += 1; }, []);

  async function importData(file: File | undefined, kind: 'charge' | 'volume') {
    if (!file || busy) return;
    const version = generation.current;
    const limit = kind === 'charge' ? MAX_CHARGE_BYTES : MAX_CUBE_BYTES;
    setError('');
    if (file.size > limit) {
      setError(ko ? `파일은 ${limit / 1024 / 1024} MiB 이하여야 합니다.` : `File must be at most ${limit / 1024 / 1024} MiB.`);
      return;
    }
    if (kind === 'volume' && !volumeSource.trim()) {
      setError(ko ? '계산 방법이나 데이터 출처를 입력해 주세요.' : 'Enter the calculation method or data source.');
      return;
    }
    setBusy(true);
    try {
      const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer());
      if (version !== generation.current) return;
      const current = dataRef.current ?? { charges: [], volumes: [] };
      if (kind === 'charge') {
        const charge = parseChargeData(text, report, sourceSha256, file.name, { name: chargeName.trim() || file.name });
        onChange(appendAuxiliaryDataset(current, charge));
        setChargeKind(charge.kind);
      } else {
        const volume = parseCubeData(text, report, {
          kind: volumeKind, source: volumeSource.trim(), units: volumeUnits,
        }, file.name, { name: volumeName.trim() || file.name });
        onChange(appendAuxiliaryDataset(current, volume));
      }
    } catch (cause) {
      if (version === generation.current) {
        const reason = cause instanceof Error ? cause.message : String(cause);
        setError(`${ko ? '불러오지 못했습니다. 기존 자료는 유지됩니다.' : 'Import rejected. Existing data is unchanged.'} ${reason}`);
      }
    } finally {
      if (version === generation.current) setBusy(false);
    }
  }

  function downloadTemplate() {
    const url = URL.createObjectURL(new Blob([makeChargeTemplate(report, sourceSha256, chargeKind)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `calclens-${chargeKind}-template.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }

  function downloadOriginal(rawText: string, filename: string) {
    const url = URL.createObjectURL(new Blob([rawText], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }

  return <details className="tool-card auxiliary-panel" data-testid="auxiliary-panel">
    <summary><span><b>{ko ? '전하·전자 표면 자료' : 'Charge & electronic surface data'}</b><small>{ko ? '계산된 자료를 연결해 표시합니다' : 'Display externally calculated data'}</small></span></summary>
    <div className="tool-body auxiliary-body" aria-busy={busy}>
      <p className="auxiliary-note">{ko
        ? `이 CIF에 최대 ${MAX_AUXILIARY_DATASETS}개 자료를 이름별로 연결할 수 있습니다. 원본 파일·방법·출처와 뷰어 설정을 작업에 함께 저장합니다. CalcLens가 전하나 전자밀도를 계산하지는 않습니다.`
        : `Attach up to ${MAX_AUXILIARY_DATASETS} named datasets to this CIF. Original files, methods, sources and viewer settings are included in saved projects. CalcLens does not calculate charges or electron density.`}</p>
      {error && <div role="alert" className="auxiliary-error" data-testid="auxiliary-error">{error}</div>}
      <fieldset disabled={busy}>
        <legend>{ko ? '원자별 전하·산화수 JSON' : 'Atomic charge / oxidation-state JSON'}</legend>
        <div className="auxiliary-fields">
          <label>{ko ? '서식의 값 종류' : 'Template quantity'}<select data-testid="charge-kind" value={chargeKind} onChange={(event) => setChargeKind(event.target.value as ChargeKind)}>
            {(Object.keys(names[language]) as ChargeKind[]).map((kind) => <option key={kind} value={kind}>{names[language][kind]}</option>)}
          </select></label>
          <button type="button" data-testid="charge-template" onClick={downloadTemplate}>{ko ? '이 구조의 입력 서식 저장' : 'Download template for this structure'}</button>
          <label>{ko ? '자료 이름 (선택)' : 'Dataset name (optional)'}<input data-testid="charge-name" maxLength={500} value={chargeName} onChange={(event) => setChargeName(event.target.value)} placeholder={ko ? '예: 계산 A · Hirshfeld' : 'e.g. Calculation A · Hirshfeld'} /></label>
          <label>{ko ? 'JSON 파일 불러오기' : 'Import JSON file'}<input data-testid="charge-import" type="file" accept=".json,application/json" onChange={(event) => { void importData(event.target.files?.[0], 'charge'); event.target.value = ''; }} /></label>
        </div>
        <p className="auxiliary-note">{ko ? '서식의 원자 번호·원소·CIF 식별값을 유지하고 값, 방법, 출처를 작성하세요. null은 정보 없음이며 0과 다릅니다. 불러올 값 종류는 파일의 kind 항목으로 확인합니다.' : 'Keep template atom indices, elements and CIF identity. Fill in values, method and source. null means unknown, not zero. The file kind determines the imported quantity.'}</p>
        <div className="auxiliary-datasets">{(data?.charges ?? []).map((charge) => {
          return <div key={charge.id} data-dataset-id={charge.id}><span><b>{charge.name}</b> · {names[language][charge.kind]}<small>{charge.filename} · {charge.method} · {charge.source}</small><small>ID: {charge.id}</small></span><div className="auxiliary-dataset-actions"><button type="button" onClick={() => downloadOriginal(charge.rawText, charge.filename)}>{ko ? '원본 저장' : 'Save original'}</button><button type="button" data-testid={`clear-charge-${charge.kind}`} aria-label={`${ko ? '자료 제거' : 'Remove data'}: ${charge.name}`} onClick={() => {
            onChange({ ...data!, charges: data!.charges.filter((item) => item.id !== charge.id) });
          }}>×</button></div></div>;
        })}</div>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>{ko ? '전자밀도·오비탈 Cube' : 'Electron density / orbital Cube'}</legend>
        <div className="auxiliary-fields">
          <label>{ko ? '자료 의미' : 'Field meaning'}<select data-testid="volume-kind" value={volumeKind} onChange={(event) => {
            const kind = event.target.value as 'density' | 'orbital'; setVolumeKind(kind);
            setVolumeUnits(kind === 'density' ? 'e/bohr^3' : 'bohr^-3/2');
          }}><option value="density">{ko ? '전자밀도' : 'Electron density'}</option><option value="orbital">{ko ? '오비탈' : 'Orbital'}</option></select></label>
          <label>{ko ? '격자 값의 단위' : 'Scalar-value units'}<select data-testid="volume-units" value={volumeUnits} onChange={(event) => setVolumeUnits(event.target.value)}>
            {(volumeKind === 'density' ? ['e/bohr^3', 'e/angstrom^3'] : ['bohr^-3/2', 'angstrom^-3/2', 'arbitrary']).map((unit) => <option value={unit} key={unit}>{unit}</option>)}
          </select></label>
          <label>{ko ? '계산 방법·출처' : 'Calculation method / source'}<input data-testid="volume-source" maxLength={500} value={volumeSource} onChange={(event) => setVolumeSource(event.target.value)} placeholder={ko ? '예: 계산 프로그램, 방법, 자료 식별자' : 'Program, method, data identifier'} /></label>
          <label>{ko ? '자료 이름 (선택)' : 'Dataset name (optional)'}<input data-testid="volume-name" maxLength={500} value={volumeName} onChange={(event) => setVolumeName(event.target.value)} placeholder={ko ? '예: HOMO · 계산 A' : 'e.g. HOMO · Calculation A'} /></label>
          <label>{ko ? 'Cube 파일 불러오기' : 'Import Cube file'}<input data-testid="volume-import" type="file" accept=".cube,.cub" onChange={(event) => { void importData(event.target.files?.[0], 'volume'); event.target.value = ''; }} /></label>
        </div>
        <p className="auxiliary-note">{ko ? '원자 순서·원소·좌표가 이 CIF와 일치하는 단일 격자만 받습니다. 좌표 단위는 격자 크기 부호로 확인합니다(양수: Bohr, 모두 음수: Å). 오비탈의 두 색은 전하가 아닌 파동함수 부호입니다.' : 'A single grid must match this CIF’s atom order, elements and coordinates. Positive grid counts mean Bohr; all-negative counts mean Å. Orbital colors indicate wavefunction sign, not charge.'}</p>
        <div className="auxiliary-datasets">{(data?.volumes ?? []).map((volume) => <div key={volume.id} data-dataset-id={volume.id}><span><b>{volume.name}</b> · {volume.kind === 'density' ? (ko ? '전자밀도' : 'Electron density') : (ko ? '오비탈' : 'Orbital')}<small>{volume.filename} · {volume.source} · {volume.units} · {volume.pointCount.toLocaleString()} {ko ? '격자점' : 'grid points'}</small><small>ID: {volume.id}</small></span><div className="auxiliary-dataset-actions"><button type="button" onClick={() => downloadOriginal(volume.rawText, volume.filename)}>{ko ? '원본 저장' : 'Save original'}</button><button type="button" data-testid="clear-volume" aria-label={`${ko ? '전자 표면 자료 제거' : 'Remove volume data'}: ${volume.name}`} onClick={() => onChange({ ...data!, volumes: data!.volumes.filter((item) => item.id !== volume.id) })}>×</button></div></div>)}</div>
      </fieldset>
      {busy && <p role="status">{ko ? '자료를 확인하는 중…' : 'Validating data…'}</p>}
    </div>
  </details>;
}
