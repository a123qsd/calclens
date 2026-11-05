import { useEffect, useMemo, useRef, useState } from 'react';
import * as $3Dmol from '3dmol';
import type { AtomSpec, GLModel, GLViewer } from '3dmol';
import type { GeometryReport, MolecularViewerProps, Vec3 } from './types';
import {
  buildDisplayAtoms, cellCorners, cellEdges, contactEndpoints, inferDisplayBonds,
  gapBoundary, gapFractions, markAtomIndices, normalViewQuaternion, withContactEndpoints,
} from './viewerGeometry';
import type { DisplayAtom, DisplayBond } from './viewerGeometry';
import './viewer.css';

type RepeatCount = 1 | 2 | 3;

interface ViewerScene {
  structureKey: string;
  highlightKey: string;
  atomHighlightKey: string;
  extraAtomsKey: string;
  overlayKey: string;
  gapKey: string;
  highlightGap: boolean;
  showBonds: boolean;
  baseAtoms: DisplayAtom[];
  bonds: DisplayBond[];
  displayAtoms: DisplayAtom[];
  atomModel: GLModel;
  cornerModel: GLModel;
}

const text = {
  ko: {
    fallback: '이 브라우저에서 3D 보기를 시작하지 못했습니다.',
    fitAtoms: '원자 맞춤', fitCell: '셀 맞춤', reset: '초기화', rotate: '회전',
    stop: '회전 중지', labels: '원자 번호', cell: '단위 셀', bonds: '추정 연결',
    repeat: '반복', picked: '선택', ready: '마우스로 회전하고 원자를 선택할 수 있습니다.',
    inferred: '표시용 추정 연결 · 분석에 사용되지 않음', hidden: '추정 연결 숨김',
  },
  en: {
    fallback: 'The 3D view could not start in this browser.',
    fitAtoms: 'Fit atoms', fitCell: 'Fit cell', reset: 'Reset', rotate: 'Rotate',
    stop: 'Stop rotation', labels: 'Atom IDs', cell: 'Unit cell', bonds: 'Display bonds',
    repeat: 'Repeat', picked: 'Selected', ready: 'Drag to rotate and select an atom.',
    inferred: 'Display-only inferred connections · not used in analysis', hidden: 'Inferred connections hidden',
  },
} as const;

function xyz(position: Vec3) {
  return { x: position[0], y: position[1], z: position[2] };
}

function defaultCamera(viewer: GLViewer, report: GeometryReport) {
  const view = viewer.getView();
  viewer.setView([...view.slice(0, 4), ...normalViewQuaternion(report)]);
  viewer.zoomTo({ model: 0 });
  viewer.rotate(12, 'x');
  viewer.rotate(-18, 'y');
  viewer.render();
}

export default function MolecularViewer({
  report, language, highlight = null, highlightGap = false, highlightedAtomIndices,
  onAtomPick, compact = false,
}: MolecularViewerProps) {
  const labels = text[language];
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<GLViewer | null>(null);
  const onAtomPickRef = useRef(onAtomPick);
  const sceneRef = useRef<ViewerScene | null>(null);
  const [repeat, setRepeat] = useState<RepeatCount>(compact ? 1 : 3);
  const [showBonds, setShowBonds] = useState(true);
  const [showCell, setShowCell] = useState(false);
  const [showLabels, setShowLabels] = useState(false);
  const [spinning, setSpinning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);

  const structureKey = useMemo(() => JSON.stringify([
    report.elements, report.positions, report.cell, report.normal_axis_index, repeat,
  ]), [report, repeat]);
  const highlightKey = highlight ? [highlight.i, highlight.j, ...(highlight.start_shift ?? [0, 0, 0]),
    ...(highlight.end_shift ?? highlight.shift)].join(',') : '';
  const atomHighlightKey = highlightedAtomIndices?.join(',') ?? '';
  const gapKey = highlightGap ? gapFractions(report).join(',') : '';
  const overlayKey = JSON.stringify([showCell, showLabels, highlightKey, gapKey, language]);

  useEffect(() => { onAtomPickRef.current = onAtomPick; }, [onAtomPick]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    try {
      const viewer = $3Dmol.createViewer(host, {
        backgroundColor: '#fdfdfc', backgroundAlpha: 1,
      });
      viewerRef.current = viewer;
      setError(null);
      const observer = new ResizeObserver(() => viewer.resize());
      observer.observe(host);
      return () => {
        observer.disconnect();
        viewer.spin(false);
        viewer.removeAllLabels();
        viewer.removeAllShapes();
        viewer.removeAllModels();
        viewerRef.current = null;
        sceneRef.current = null;
        host.replaceChildren();
      };
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : labels.fallback);
    }
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    try {
      const previous = sceneRef.current;
      const sameStructure = previous?.structureKey === structureKey;
      if (!sameStructure) setPicked(null);
      const shouldFitGap = highlightGap && (!sameStructure || !previous?.highlightGap);
      const shouldFitContact = Boolean(highlightKey && highlightKey !== previous?.highlightKey);

      // Display geometry and inferred connectivity depend on the structure, not the toolbar.
      const baseAtoms = sameStructure ? previous.baseAtoms : buildDisplayAtoms(report, repeat);
      const bonds = sameStructure ? previous.bonds : inferDisplayBonds(baseAtoms);
      const sameHighlights = sameStructure && previous.highlightKey === highlightKey
        && previous.atomHighlightKey === atomHighlightKey;
      const displayAtoms = sameHighlights ? previous.displayAtoms : markAtomIndices(
        withContactEndpoints(baseAtoms, report, highlight), highlightedAtomIndices,
      );
      // A selected periodic contact may add atoms outside the current repeat range.
      const extraAtomsKey = JSON.stringify(displayAtoms.slice(baseAtoms.length).map((atom) => [
        atom.index, atom.shift, atom.position,
      ]));
      const rebuildModels = !sameStructure || previous.extraAtomsKey !== extraAtomsKey;
      const updateStyles = rebuildModels || !sameHighlights || previous?.showBonds !== showBonds;
      const updateOverlays = rebuildModels || previous?.overlayKey !== overlayKey;
      const previousView = rebuildModels && sameStructure ? viewer.getView() : null;
      let atomModel: GLModel;
      let cornerModel: GLModel;
      if (rebuildModels) {
        viewer.removeAllModels();
        const atomSpecs: AtomSpec[] = displayAtoms.map((atom) => ({
          x: atom.position[0], y: atom.position[1], z: atom.position[2], elem: atom.element,
          atom: `${atom.element}${atom.index + 1}`, serial: atom.displayIndex + 1,
          bonds: [], bondOrder: [], clickable: true,
          properties: {
            calclensIndex: atom.index, calclensShift: atom.shift,
            calclensElement: atom.element, calclensHighlight: atom.highlight,
          },
        }));
        for (const bond of bonds) {
          atomSpecs[bond.a].bonds?.push(bond.b);
          atomSpecs[bond.a].bondOrder?.push(1);
          atomSpecs[bond.b].bonds?.push(bond.a);
          atomSpecs[bond.b].bondOrder?.push(1);
        }
        atomModel = viewer.addModel();
        atomModel.addAtoms(atomSpecs);
        cornerModel = viewer.addModel();
        viewer.setClickable({ model: 0 }, true, (atom: AtomSpec) => {
          const properties = atom.properties ?? {};
          const index = Number(properties.calclensIndex);
          const shift = properties.calclensShift as Vec3;
          const element = String(properties.calclensElement ?? atom.elem ?? '');
          if (!Number.isInteger(index) || !Array.isArray(shift)) return;
          setPicked(`${element}${index + 1} · [${shift.join(', ')}]`);
          onAtomPickRef.current?.({ index, shift, element });
        });
      } else {
        atomModel = previous.atomModel;
        cornerModel = previous.cornerModel;
      }
      if (updateStyles) {
        atomModel.selectedAtoms({}).forEach((atom, index) => {
          if (atom.properties) atom.properties.calclensHighlight = displayAtoms[index].highlight;
        });
        atomModel.setStyle({}, showBonds
          ? { sphere: { scale: 0.32 }, stick: { radius: 0.105 } }
          : { sphere: { scale: 0.36 } });
        atomModel.setStyle({ predicate: (atom) => Boolean(atom.properties?.calclensHighlight) }, {
          sphere: { scale: 0.48, color: '#F59E0B' },
          ...(showBonds ? { stick: { radius: 0.14, color: '#F59E0B' } } : {}),
        }, true);
      }
      if (rebuildModels || previous?.gapKey !== gapKey) {
        const corners = cellCorners(report.cell);
        if (highlightGap) {
          corners.push(...gapFractions(report).flatMap((fraction) => gapBoundary(report, fraction)));
        }
        cornerModel.removeAtoms(cornerModel.selectedAtoms({}));
        cornerModel.addAtoms(corners.map((point, index) => ({
          ...xyz(point), elem: 'X', atom: `cell${index}`, bonds: [], bondOrder: [],
          properties: { calclensCellCorner: true },
        })));
        cornerModel.setStyle({}, {});
      }
      if (updateOverlays) {
        viewer.removeAllLabels();
        viewer.removeAllShapes();
      }
      if (updateOverlays && showCell) {
        for (const edge of cellEdges(report.cell)) {
          viewer.addLine({ start: xyz(edge.start), end: xyz(edge.end), color: '#8FA0B3',
            linewidth: 1, opacity: 0.68 });
        }
      }
      if (updateOverlays && highlight) {
        const endpoints = contactEndpoints(report, highlight);
        viewer.addCylinder({ start: xyz(endpoints.start), end: xyz(endpoints.end),
          radius: 0.055, color: '#F59E0B', dashed: false });
      }
      if (updateOverlays && highlightGap) {
        const fractions = gapFractions(report);
        fractions.forEach((fraction, boundaryIndex) => {
          const vertices = gapBoundary(report, fraction);
          viewer.addCustom({ vertexArr: vertices.map(xyz), faceArr: [0, 1, 2, 0, 2, 3, 2, 1, 0, 3, 2, 0],
            color: boundaryIndex ? '#0F766E' : '#22B8A9', opacity: 0.13 });
          for (let index = 0; index < 4; index += 1) {
            viewer.addLine({ start: xyz(vertices[index]), end: xyz(vertices[(index + 1) % 4]),
              color: boundaryIndex ? '#0F766E' : '#22B8A9', linewidth: 2, dashed: true });
          }
        });
        const labelPosition = gapBoundary(report, report.metrics.gap_start_fraction)[0];
        viewer.addLabel(language === 'ko' ? '후보 핵간격 경계' : 'Candidate nuclear-gap boundary', {
          position: xyz(labelPosition), font: 'sans-serif', fontSize: 12, fontColor: '#075E57',
          backgroundColor: '#E9F8F5', backgroundOpacity: 0.9, borderColor: '#22B8A9',
          borderThickness: 1, inFront: true,
        }, undefined, true);
      }
      if (updateOverlays && showLabels) {
        // Batch labels; addLabel otherwise draws the whole scene for each label.
        for (const atom of displayAtoms.slice(0, 180)) {
          viewer.addLabel(`${atom.element}${atom.index + 1}`, {
            position: xyz(atom.position), font: 'sans-serif', fontSize: 11,
            fontColor: '#172331', backgroundColor: '#FFFFFF', backgroundOpacity: 0.72,
            borderThickness: 0, inFront: true,
          }, undefined, true);
        }
      }
      if (previousView) {
        viewer.setView(previousView);
      }
      if (!sameStructure) {
        defaultCamera(viewer, report);
      } else if (updateStyles || updateOverlays) {
        viewer.render();
      }
      if (shouldFitGap) {
        viewer.zoomTo({ model: [0, 1] }, sameStructure ? 350 : 0);
        viewer.render();
      } else if (shouldFitContact) {
        viewer.zoomTo({ model: 0 }, sameStructure ? 350 : 0);
        viewer.render();
      }
      sceneRef.current = {
        structureKey, highlightKey, atomHighlightKey, extraAtomsKey, overlayKey, gapKey,
        highlightGap, showBonds, baseAtoms, bonds, displayAtoms, atomModel, cornerModel,
      };
      setError(null);
    } catch (cause) {
      sceneRef.current = null;
      setError(cause instanceof Error ? cause.message : labels.fallback);
    }
  }, [atomHighlightKey, highlight, highlightGap, highlightKey, labels.fallback, language, repeat,
    report, showBonds, showCell, showLabels, structureKey, gapKey, overlayKey]);

  useEffect(() => {
    viewerRef.current?.spin(spinning ? 'y' : false, 0.8, true);
  }, [spinning]);

  function fitAtoms() {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.zoomTo({ model: 0 }, 350);
    viewer.render();
  }

  function fitCell() {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.zoomTo({ model: 1 }, 350);
    viewer.render();
  }

  function reset() {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.spin(false);
    setSpinning(false);
    defaultCamera(viewer, report);
  }

  function toggleSpin() {
    setSpinning((value) => !value);
  }

  return <section className={`molecule-viewer ${compact ? 'molecule-viewer--compact' : ''}`}
    aria-label={language === 'ko' ? '분자 구조 3D 보기' : '3D molecular structure'}>
    <div className="molecule-canvas-wrap">
      <div ref={hostRef} className="molecule-canvas" data-testid="molecule-canvas" />
      {error && <div className="molecule-fallback" role="alert">{labels.fallback}<small>{error}</small></div>}
      <div className="molecule-badge">3D · {report.formula}</div>
    </div>
    <div className="molecule-toolbar" role="toolbar" aria-label={language === 'ko' ? '3D 보기 도구' : '3D viewer tools'}>
      <button type="button" onClick={fitAtoms} title={labels.fitAtoms}>⌖ <span>{labels.fitAtoms}</span></button>
      <button type="button" onClick={fitCell} title={labels.fitCell}>□ <span>{labels.fitCell}</span></button>
      <button type="button" onClick={reset} title={labels.reset}>↻ <span>{labels.reset}</span></button>
      <button type="button" className={spinning ? 'is-active' : ''} aria-pressed={spinning}
        onClick={toggleSpin} title={spinning ? labels.stop : labels.rotate}>⟳ <span>{spinning ? labels.stop : labels.rotate}</span></button>
      <button type="button" className={showLabels ? 'is-active' : ''} aria-pressed={showLabels}
        onClick={() => setShowLabels((value) => !value)} title={labels.labels}># <span>{labels.labels}</span></button>
      <button type="button" className={showCell ? 'is-active' : ''} aria-pressed={showCell}
        onClick={() => setShowCell((value) => !value)} title={labels.cell}>▱ <span>{labels.cell}</span></button>
      <button type="button" className={showBonds ? 'is-active' : ''} aria-pressed={showBonds}
        onClick={() => setShowBonds((value) => !value)} title={labels.bonds}>⌁ <span>{labels.bonds}</span></button>
      <label>{labels.repeat}
        <select value={repeat} onChange={(event) => setRepeat(Number(event.target.value) as RepeatCount)}>
          <option value={1}>1×1</option><option value={2}>2×2</option><option value={3}>3×3</option>
        </select>
      </label>
    </div>
    <div className="molecule-status" aria-live="polite">
      <span>{showBonds ? labels.inferred : labels.hidden}</span>
      <span>{picked ? `${labels.picked}: ${picked}` : labels.ready}</span>
    </div>
  </section>;
}
