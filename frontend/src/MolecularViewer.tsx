import { useEffect, useMemo, useRef, useState } from 'react';
import * as $3Dmol from '3dmol';
import type { AtomSpec, AtomStyleSpec, GLModel, GLShape, GLViewer, Label } from '3dmol';
import type { AtomPick, GeometryReport, MolecularViewerProps, Vec3 } from './types';
import {
  buildDisplayAtoms, cellCorners, cellEdges, contactEndpoints, inferDisplayBonds,
  gapBoundary, gapFractions, markAtomIndices, normalViewQuaternion, withContactEndpoints,
} from './viewerGeometry';
import type { DisplayAtom, DisplayBond } from './viewerGeometry';
import { atomicNumber, isMetalElement } from './viewerData';
import type { ChargeKind, VolumeDataset } from './viewerData';
import { BOND_LIMIT, LABEL_LIMIT, assertSurfaceBudget, chargeColor, elementColor, exportDimensions,
  chargeDisplayRange, labelAtoms, repeatDimensions } from './viewerPresentation';
import type { ColorMode, Quality, Representation } from './viewerPresentation';
import { reconcileViewerDatasets, restoreViewerState, sameCamera, selectedCharge, selectedVolume, validCamera } from './viewerState';
import type { ViewerState } from './viewerState';
import { observeCamera } from './viewerCameraLink';
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
  styleKey: string;
  bondsTruncated: boolean;
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

function defaultCamera(viewer: GLViewer, report: GeometryReport, preset = 'default') {
  const view = viewer.getView();
  viewer.setView([...view.slice(0, 4), ...normalViewQuaternion(report)]);
  viewer.zoomTo({ model: 0 });
  if (preset === 'side') viewer.rotate(90, 'x');
  if (preset === 'default') {
    viewer.rotate(12, 'x');
    viewer.rotate(-18, 'y');
  }
  viewer.render();
}

export default function MolecularViewer({
  report, language, highlight = null, highlightGap = false, highlightedAtomIndices,
  onAtomPick, compact = false, auxiliary, onViewerReady, state, onStateChange, chargeRange,
}: MolecularViewerProps) {
  const labels = text[language];
  const sectionRef = useRef<HTMLElement | null>(null);
  const fullscreenButtonRef = useRef<HTMLButtonElement | null>(null);
  const ownFullscreenRef = useRef(false);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<GLViewer | null>(null);
  const onAtomPickRef = useRef(onAtomPick);
  const overlayShapesRef = useRef<GLShape[]>([]);
  const volumeShapesRef = useRef<GLShape[]>([]);
  const volumeCacheRef = useRef<{ source: VolumeDataset; data: InstanceType<typeof $3Dmol.VolumeData> } | null>(null);
  const surfaceGeometryRef = useRef<{ source: VolumeDataset; level: number } | null>(null);
  const distanceLabelRef = useRef<Label | null>(null);
  const exportingRef = useRef(false);
  const sceneRef = useRef<ViewerScene | null>(null);
  const [settings, setSettings] = useState(() => restoreViewerState(state, compact));
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const onStateChangeRef = useRef(onStateChange);
  onStateChangeRef.current = onStateChange;
  const lastPublishedRef = useRef(JSON.stringify(settings));
  const applyingCameraRef = useRef(false);
  const { repeat, showBonds, showCell, showLabels, spinning, representation, colorMode, quality,
    preset, projection, expanded, showDistance, surface } = settings;
  function settingSetter<K extends keyof ViewerState>(key: K) {
    return (value: ViewerState[K] | ((current: ViewerState[K]) => ViewerState[K])) => {
      setSettings((current) => {
        const next = typeof value === 'function' ? (value as (previous: ViewerState[K]) => ViewerState[K])(current[key]) : value;
        return current[key] === next ? current : { ...current, [key]: next };
      });
    };
  }
  const setRepeat = settingSetter('repeat');
  const setShowBonds = settingSetter('showBonds'); const setShowCell = settingSetter('showCell');
  const setShowLabels = settingSetter('showLabels'); const setSpinning = settingSetter('spinning');
  const setRepresentation = settingSetter('representation'); const setColorMode = settingSetter('colorMode');
  const setQuality = settingSetter('quality'); const setPreset = settingSetter('preset');
  const setProjection = settingSetter('projection'); const setExpanded = settingSetter('expanded');
  const setShowDistance = settingSetter('showDistance'); const setSurface = settingSetter('surface');
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<AtomPick | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [exportSize, setExportSize] = useState(1600);
  const [exportBackground, setExportBackground] = useState('white');
  const [exportDistance, setExportDistance] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [actionMessage, setActionMessage] = useState('');
  const [displayStats, setDisplayStats] = useState({ atoms: report.atom_count * (compact ? 1 : 9), bonds: 0, capped: false });
  const volume = selectedVolume(auxiliary, settings);
  const [draftLevel, setDraftLevel] = useState(String(surface.level));
  const [draftOpacity, setDraftOpacity] = useState(String(surface.opacity));
  const surfaceEnabled = Boolean(volume && surface.enabled);
  const charge = selectedCharge(auxiliary, settings);
  const effectiveColor = colorMode !== 'element' && colorMode !== 'metal' && !charge ? 'element' : colorMode;
  const colorRange = chargeDisplayRange(charge?.values ?? [], chargeRange);
  const chargeKey = charge ? JSON.stringify([charge.kind, charge.values]) : '';
  const styleKey = JSON.stringify([showBonds, representation, effectiveColor, chargeKey, colorRange, picked?.index, picked?.shift]);
  const t = (ko: string, en: string) => language === 'ko' ? ko : en;

  const structureKey = useMemo(() => JSON.stringify([
    report.elements, report.positions, report.cell, report.normal_axis_index, repeat,
  ]), [report, repeat]);
  const highlightKey = highlight ? [highlight.i, highlight.j, ...(highlight.start_shift ?? [0, 0, 0]),
    ...(highlight.end_shift ?? highlight.shift)].join(',') : '';
  const atomHighlightKey = highlightedAtomIndices?.join(',') ?? '';
  const gapKey = highlightGap ? gapFractions(report).join(',') : '';
  const overlayKey = JSON.stringify([showCell, showLabels, highlightKey, highlight?.distance_angstrom, gapKey, language, showDistance, showLabels ? [picked?.index, atomHighlightKey] : null]);

  useEffect(() => { onAtomPickRef.current = onAtomPick; }, [onAtomPick]);
  useEffect(() => { setPicked(null); }, [report.normal_axis, report.short_distance_threshold_angstrom]);

  useEffect(() => {
    if (!state) return;
    const restored = restoreViewerState(state, compact);
    const key = JSON.stringify(restored);
    if (key === JSON.stringify(settingsRef.current)) return;
    // Parent echoes are identical. A genuinely different archive restore must be
    // applied without publishing the stale state from this same effect flush.
    settingsRef.current = restored;
    lastPublishedRef.current = key;
    setSettings(restored);
    const viewer = viewerRef.current;
    if (viewer && restored.camera && !sameCamera(viewer.getView(), restored.camera)) {
      applyingCameraRef.current = true;
      try { viewer.setView(restored.camera); viewer.render(); }
      finally { applyingCameraRef.current = false; }
    }
  }, [state, compact]);

  useEffect(() => {
    const key = JSON.stringify(settings);
    if (key !== JSON.stringify(settingsRef.current) || key === lastPublishedRef.current) return;
    lastPublishedRef.current = key;
    onStateChangeRef.current?.(settings);
  }, [settings]);

  useEffect(() => { setSettings((current) => reconcileViewerDatasets(current, auxiliary)); },
    [auxiliary, settings.chargeDatasetIds, settings.volumeDatasetId]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    try {
      const viewer = $3Dmol.createViewer(host, {
        backgroundColor: '#FFFFFF', backgroundAlpha: 0,
      });
      viewerRef.current = viewer;
      const stopCamera = observeCamera(viewer, (view: number[]) => {
        if (exportingRef.current || applyingCameraRef.current || !sceneRef.current || !validCamera(view)) return;
        setSettings((current) => sameCamera(current.camera, view) ? current : { ...current, camera: [...view] });
      });
      setError(null);
      const observer = new ResizeObserver(() => { if (!exportingRef.current) viewer.resize(); });
      observer.observe(host);
      return () => {
        observer.disconnect();
        stopCamera();
        viewer.spin(false);
        viewer.removeAllLabels();
        viewer.removeAllShapes();
        viewer.removeAllModels();
        viewerRef.current = null;
        sceneRef.current = null;
        overlayShapesRef.current = [];
        volumeShapesRef.current = [];
        volumeCacheRef.current = null;
        surfaceGeometryRef.current = null;
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
      const inferred = sameStructure ? previous.bonds : inferDisplayBonds(baseAtoms, BOND_LIMIT + 1);
      const bondsTruncated = sameStructure ? previous.bondsTruncated : inferred.length > BOND_LIMIT;
      const bonds = inferred.length > BOND_LIMIT ? inferred.slice(0, BOND_LIMIT) : inferred;
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
      const updateStyles = rebuildModels || !sameHighlights || previous?.styleKey !== styleKey;
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
          setPicked({ index, shift, element });
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
        const colorfunc = (atom: AtomSpec) => {
          const element = String(atom.elem ?? '');
          if (effectiveColor === 'metal') return isMetalElement(element) ? '#B9824F' : '#BEC7CF';
          if (charge && effectiveColor !== 'element') {
            return chargeColor(charge.values[Number(atom.properties?.calclensIndex)], colorRange);
          }
          return elementColor(element);
        };
        const style: AtomStyleSpec = representation === 'spacefill'
          ? { sphere: { scale: 1, colorfunc } }
          : representation === 'stick' && showBonds
            ? { sphere: { radius: 0.12, colorfunc }, stick: { radius: 0.13, colorfunc, showNonBonded: true } }
            : { sphere: { scale: showBonds ? 0.25 : 0.32, colorfunc },
              ...(showBonds ? { stick: { radius: 0.085, colorfunc } } : {}) };
        atomModel.setStyle({}, style);
        atomModel.setStyle({ predicate: (atom) => Boolean(atom.properties?.calclensHighlight)
          || Boolean(picked && atom.properties?.calclensIndex === picked.index
            && (atom.properties.calclensShift as Vec3).every((value, axis) => value === picked.shift[axis])) }, {
          // Additive styles retain the base colorfunc, which takes priority over color.
          sphere: { scale: representation === 'spacefill' ? 1.05 : 0.42, color: '#F59E0B', colorfunc: () => '#F59E0B' },
          ...(showBonds && representation !== 'spacefill' ? { stick: { radius: 0.13, color: '#F59E0B', colorfunc: () => '#F59E0B' } } : {}),
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
        for (const shape of overlayShapesRef.current) viewer.removeShape(shape);
        overlayShapesRef.current = [];
        distanceLabelRef.current = null;
      }
      if (updateOverlays && showCell) {
        for (const edge of cellEdges(report.cell)) {
          overlayShapesRef.current.push(viewer.addLine({ start: xyz(edge.start), end: xyz(edge.end), color: '#8FA0B3',
            linewidth: 1, opacity: 0.68 }));
        }
      }
      if (updateOverlays && highlight) {
        const endpoints = contactEndpoints(report, highlight);
        overlayShapesRef.current.push(viewer.addCylinder({ start: xyz(endpoints.start), end: xyz(endpoints.end),
          radius: 0.055, color: '#F59E0B', dashed: false }));
        if (showDistance) {
          const midpoint = endpoints.start.map((value, axis) => (value + endpoints.end[axis]) / 2) as Vec3;
          distanceLabelRef.current = viewer.addLabel(`${highlight.distance_angstrom.toFixed(3)} Å`, {
            position: xyz(midpoint), fontSize: 13, fontColor: '#7C4B08', backgroundColor: '#FFF6DF',
            backgroundOpacity: 0.92, borderColor: '#E5B863', borderThickness: 1, inFront: true,
          }, undefined, true);
        }
      }
      if (updateOverlays && highlightGap) {
        const fractions = gapFractions(report);
        fractions.forEach((fraction, boundaryIndex) => {
          const vertices = gapBoundary(report, fraction);
          overlayShapesRef.current.push(viewer.addCustom({ vertexArr: vertices.map(xyz), faceArr: [0, 1, 2, 0, 2, 3, 2, 1, 0, 3, 2, 0],
            color: boundaryIndex ? '#0F766E' : '#22B8A9', opacity: 0.13 }));
          for (let index = 0; index < 4; index += 1) {
            overlayShapesRef.current.push(viewer.addLine({ start: xyz(vertices[index]), end: xyz(vertices[(index + 1) % 4]),
              color: boundaryIndex ? '#0F766E' : '#22B8A9', linewidth: 2, dashed: true }));
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
        for (const atom of labelAtoms(displayAtoms, picked?.index)) {
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
      const savedCamera = settingsRef.current.camera;
      const restoredCamera = !previous && savedCamera;
      if (!sameStructure) {
        if (savedCamera) viewer.setView(savedCamera);
        else defaultCamera(viewer, report, preset);
      } else if (updateStyles || updateOverlays) {
        viewer.render();
      }
      if (shouldFitGap && !restoredCamera) {
        viewer.zoomTo({ model: [0, 1] }, sameStructure ? 350 : 0);
        viewer.render();
      } else if (shouldFitContact && !restoredCamera) {
        viewer.zoomTo({ model: 0 }, sameStructure ? 350 : 0);
        viewer.render();
      }
      sceneRef.current = {
        structureKey, highlightKey, atomHighlightKey, extraAtomsKey, overlayKey, gapKey,
        highlightGap, styleKey, bondsTruncated, baseAtoms, bonds, displayAtoms, atomModel, cornerModel,
      };
      const camera = viewer.getView();
      if (validCamera(camera)) setSettings((current) => sameCamera(current.camera, camera) ? current : { ...current, camera: [...camera] });
      setDisplayStats((current) => current.atoms === displayAtoms.length && current.bonds === bonds.length && current.capped === bondsTruncated
        ? current : { atoms: displayAtoms.length, bonds: bonds.length, capped: bondsTruncated });
      setError(null);
    } catch (cause) {
      sceneRef.current = null;
      setError(cause instanceof Error ? cause.message : labels.fallback);
    }
  }, [atomHighlightKey, highlight, highlightGap, highlightKey, labels.fallback, language, repeat,
    report, showBonds, showCell, showLabels, structureKey, gapKey, overlayKey, styleKey, representation, effectiveColor, charge, picked?.index, showDistance, preset]);

  useEffect(() => {
    viewerRef.current?.spin(spinning ? 'y' : false, 0.8, true);
  }, [spinning]);

  useEffect(() => {
    onViewerReady?.(viewerRef.current);
    return () => onViewerReady?.(null);
  }, [onViewerReady]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.setViewStyle(quality === 'light' ? { style: 'none' } : {
      style: quality === 'high' ? 'outline ambientOcclusion' : 'outline',
      color: '#4B5C70', width: 0.015, strength: 0.25,
    });
    viewer.render();
  }, [quality]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.setProjection(projection);
    viewer.render();
  }, [projection]);

  useEffect(() => {
    const changed = () => {
      const active = document.fullscreenElement === sectionRef.current;
      const wasActive = ownFullscreenRef.current;
      ownFullscreenRef.current = active;
      setFullscreen(active);
      if (wasActive && !active) fullscreenButtonRef.current?.focus();
    };
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, []);

  useEffect(() => {
    setDraftLevel(String(surface.level));
    setDraftOpacity(String(surface.opacity));
    setActionMessage('');
  }, [volume, surface.level, surface.opacity]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    if (volumeCacheRef.current?.source !== volume) {
      for (const shape of volumeShapesRef.current) viewer.removeShape(shape);
      volumeShapesRef.current = [];
      surfaceGeometryRef.current = null;
      volumeCacheRef.current = null;
    }
    if (!surfaceEnabled || !volume) {
      for (const shape of volumeShapesRef.current) shape.updateStyle({ hidden: true });
      viewer.render();
      return;
    }
    try {
      const extent = volume.kind === 'density' ? volume.max : Math.max(Math.abs(volume.min), Math.abs(volume.max));
      if (surface.level > extent) throw new Error(t('등치값이 선택한 자료의 범위를 벗어났습니다.', 'Isovalue exceeds the selected dataset range.'));
      if (volumeCacheRef.current?.source !== volume) {
        volumeCacheRef.current = { source: volume, data: new $3Dmol.VolumeData(volume.cubeText, 'cube') };
      }
      if (surfaceGeometryRef.current?.source !== volume || surfaceGeometryRef.current.level !== surface.level) {
        const data = volumeCacheRef.current.data;
        const levels = volume.kind === 'density' ? [surface.level]
          : [surface.level, -surface.level].filter((value) => value >= volume.min && value <= volume.max);
        assertSurfaceBudget(data.data, data.size, levels);
        for (const shape of volumeShapesRef.current) viewer.removeShape(shape);
        volumeShapesRef.current = [];
        for (const level of levels) {
          volumeShapesRef.current.push(viewer.addIsosurface(data, {
            isoval: level, opacity: surface.opacity, smoothness: 1,
            color: volume.kind === 'density' ? '#4D9DB0' : level > 0 ? '#8064AD' : '#1EAA9A',
          }));
        }
        surfaceGeometryRef.current = { source: volume, level: surface.level };
      }
      for (const shape of volumeShapesRef.current) shape.updateStyle({ hidden: false, opacity: surface.opacity });
      viewer.render();
    } catch (cause) {
      for (const shape of volumeShapesRef.current) viewer.removeShape(shape);
      volumeShapesRef.current = [];
      surfaceGeometryRef.current = null;
      setSurface((current) => ({ ...current, enabled: false }));
      setActionMessage(cause instanceof Error ? cause.message : 'Surface could not be rendered.');
      viewer.render();
    }
  }, [volume, surfaceEnabled, surface.level, surface.opacity]);

  function applySurface(enabled = surfaceEnabled) {
    if (!volume) return;
    const level = Number(draftLevel);
    const opacity = Number(draftOpacity);
    const extent = volume.kind === 'density' ? volume.max : Math.max(Math.abs(volume.min), Math.abs(volume.max));
    if (!Number.isFinite(level) || level <= 0 || level > extent || !Number.isFinite(opacity) || opacity < 0.05 || opacity > 1) {
      setActionMessage(t('등치값은 자료 범위 안의 양수, 불투명도는 0.05–1이어야 합니다.',
        'Use a positive isovalue within the data range and opacity from 0.05 to 1.'));
      return;
    }
    setSurface({ enabled, level, opacity });
    setActionMessage('');
  }

  function cameraPreset(value: ViewerState['preset']) {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.spin(false); setSpinning(false); setPreset(value);
    defaultCamera(viewer, report, value);
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === sectionRef.current) await document.exitFullscreen();
      else if (sectionRef.current?.requestFullscreen) await sectionRef.current.requestFullscreen();
      else {
        setExpanded((current) => !current);
        setActionMessage(t('전체 화면 대신 확장 보기를 사용합니다.', 'Using expanded view because fullscreen is unavailable.'));
      }
    } catch {
      setExpanded(true);
      setActionMessage(t('전체 화면을 사용할 수 없어 보기를 확장했습니다.', 'Fullscreen is unavailable; the viewer has been expanded.'));
    }
  }

  async function savePng() {
    const viewer = viewerRef.current;
    const host = hostRef.current;
    if (!viewer || !host || exportingRef.current) return;
    setExporting(true); setActionMessage(''); exportingRef.current = true;
    // Give the pending state a frame before the synchronous WebGL export.
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const view = viewer.getView();
    const distanceLabel = distanceLabelRef.current;
    viewer.spin(false);
    try {
      const dimensions = exportDimensions(host.clientWidth, host.clientHeight, exportSize);
      const ratio = viewer.getCanvas().width / host.clientWidth || 1;
      viewer.setWidth(dimensions.width / ratio);
      viewer.setHeight(dimensions.height / ratio);
      viewer.setBackgroundColor('#FFFFFF', exportBackground === 'transparent' ? 0 : 1);
      if (!exportDistance) distanceLabel?.hide();
      viewer.setView(view, true);
      viewer.render();
      const data = viewer.pngURI();
      if (!data.startsWith('data:image/png')) throw new Error('PNG export failed.');
      const anchor = document.createElement('a');
      anchor.href = data;
      anchor.download = `CalcLens-${report.formula.replace(/[^a-zA-Z0-9_-]/g, '_')}-${dimensions.width}x${dimensions.height}.png`;
      anchor.click();
      setActionMessage(t(`${dimensions.width} × ${dimensions.height} PNG를 저장했습니다.`,
        `Saved ${dimensions.width} × ${dimensions.height} PNG.`));
    } catch (cause) {
      setActionMessage(cause instanceof Error ? cause.message : t('PNG 저장에 실패했습니다.', 'PNG export failed.'));
    } finally {
      distanceLabel?.show();
      viewer.setBackgroundColor('#FFFFFF', 0);
      viewer.resize();
      viewer.setView(view, true);
      viewer.render();
      if (spinning) viewer.spin('y', 0.8, true);
      exportingRef.current = false; setExporting(false);
    }
  }

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
    setPreset('default');
    defaultCamera(viewer, report);
  }

  function toggleSpin() {
    setSpinning((value) => !value);
  }

  return <section ref={sectionRef} className={`molecule-viewer ${compact ? 'molecule-viewer--compact' : ''} ${expanded ? 'molecule-viewer--expanded' : ''}`}
    aria-label={t('원자 구조 3D 보기', '3D atomic structure')}>
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
    <div className="viewer-summary">
      <p data-testid="viewer-counts">{t('원본 셀', 'Original cell')}: {report.atom_count} · {t('화면 원자', 'Displayed atoms')}: {displayStats.atoms} · a×b×c: {repeatDimensions(report.normal_axis_index, repeat).join('×')}
        {displayStats.atoms > report.atom_count * repeat * repeat && ` · +${displayStats.atoms - report.atom_count * repeat * repeat} ${t('접촉 이미지', 'contact images')}`}</p>
      <div className="viewer-utility">
        <button type="button" data-testid="viewer-expanded" aria-pressed={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? t('기본 높이', 'Normal height') : t('크게 보기', 'Expand view')}</button>
        <button ref={fullscreenButtonRef} type="button" data-testid="viewer-fullscreen" aria-pressed={fullscreen} onClick={() => void toggleFullscreen()}>{fullscreen ? t('전체 화면 종료', 'Exit fullscreen') : t('전체 화면', 'Fullscreen')}</button>
      </div>
    </div>
    <details className="viewer-settings">
      <summary data-testid="viewer-settings-toggle">{t('표시 설정 및 이미지 저장', 'Display settings and image export')}</summary>
      <div className="viewer-settings-grid">
        <label>{t('원자 표현', 'Representation')}<select data-testid="viewer-representation" value={representation} onChange={(event) => setRepresentation(event.target.value as Representation)}>
          <option value="ball-stick">{t('구·막대', 'Ball and stick')}</option><option value="stick">{t('막대', 'Sticks')}</option><option value="spacefill">{t('공간 채움', 'Space filling')}</option>
        </select></label>
        <label>{t('색상 기준', 'Color by')}<select data-testid="viewer-color" value={effectiveColor} onChange={(event) => setColorMode(event.target.value as ColorMode)}>
          <option value="element">{t('원소', 'Element')}</option><option value="metal">{t('금속 원소 강조', 'Metal elements')}</option>
          <option value="ionic_charge" disabled={!auxiliary?.charges.some((dataset) => dataset.kind === 'ionic_charge')}>{t('이온 순전하', 'Ionic net charge')}</option>
          <option value="formal_charge" disabled={!auxiliary?.charges.some((dataset) => dataset.kind === 'formal_charge')}>{t('형식전하', 'Formal charge')}</option>
          <option value="partial_charge" disabled={!auxiliary?.charges.some((dataset) => dataset.kind === 'partial_charge')}>{t('부분전하', 'Partial charge')}</option>
          <option value="oxidation_state" disabled={!auxiliary?.charges.some((dataset) => dataset.kind === 'oxidation_state')}>{t('산화수', 'Oxidation state')}</option>
        </select></label>
        {charge && <label>{t('전하·산화수 자료 선택', 'Charge / oxidation-state dataset')}<select data-testid="viewer-charge-dataset" value={charge.id} onChange={(event) => {
          const id = event.target.value;
          setSettings((current) => ({ ...current, chargeDatasetIds: { ...current.chargeDatasetIds, [charge.kind]: id } }));
        }}>{auxiliary!.charges.filter((dataset) => dataset.kind === charge.kind).map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · {dataset.method}</option>)}</select></label>}
        <label>{t('그래픽 품질', 'Graphics quality')}<select data-testid="viewer-quality" value={quality} onChange={(event) => setQuality(event.target.value as Quality)}>
          <option value="light">{t('가볍게 · 추가 효과 없음', 'Light · no extra effects')}</option><option value="balanced">{t('균형 · 얇은 외곽선', 'Balanced · fine outlines')}</option><option value="high">{t('고품질 · 입체 음영', 'High · ambient shading')}</option>
        </select></label>
        <label>{t('시점', 'Viewpoint')}<select data-testid="viewer-preset" value={preset} onChange={(event) => cameraPreset(event.target.value as ViewerState['preset'])}>
          <option value="default">{t('기본 입체 시점', 'Default 3D')}</option><option value="top">{t('위에서 보기', 'Top')}</option><option value="side">{t('옆에서 보기', 'Side')}</option>
        </select></label>
        <label>{t('투영', 'Projection')}<select data-testid="viewer-projection" value={projection} onChange={(event) => setProjection(event.target.value as ViewerState['projection'])}>
          <option value="perspective">{t('원근', 'Perspective')}</option><option value="orthographic">{t('정사영', 'Orthographic')}</option>
        </select></label>
        <label className="viewer-checkbox"><input data-testid="viewer-distance" type="checkbox" checked={showDistance} onChange={(event) => setShowDistance(event.target.checked)} />{t('선택 거리 표시', 'Show selected distance')}</label>
      </div>
      <fieldset className="viewer-electronic">
        <legend>{t('전자 표면', 'Electronic surface')}</legend>
        {Boolean(auxiliary?.volumes.length) && <label>{t('전자밀도·오비탈 자료 선택', 'Density / orbital dataset')}<select data-testid="viewer-volume-dataset" value={volume?.id ?? ''} onChange={(event) => {
          const dataset = auxiliary?.volumes.find((item) => item.id === event.target.value);
          if (dataset) setSettings((current) => ({ ...current, volumeDatasetId: dataset.id,
            surface: { ...current.surface, enabled: false, level: dataset.suggestedIsovalue } }));
        }}>{auxiliary!.volumes.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name} · {dataset.kind === 'density' ? t('전자밀도', 'Density') : t('오비탈', 'Orbital')}</option>)}</select></label>}
        <label className="viewer-checkbox"><input data-testid="viewer-volume-enabled" type="checkbox" disabled={!volume} checked={surfaceEnabled} onChange={(event) => event.target.checked ? applySurface(true) : setSurface((current) => ({ ...current, enabled: false }))} />{volume?.kind === 'orbital' ? t('오비탈 등치면', 'Orbital isosurfaces') : t('전자밀도 등치면', 'Electron-density isosurface')}</label>
        {!volume ? <p>{t('전자밀도 또는 오비탈 .cube 파일을 가져오면 사용할 수 있습니다.', 'Import an electron-density or orbital .cube file to enable this view.')}</p> : <>
          <p className="viewer-source">{volume.name} · {volume.filename} · {volume.units} · {volume.pointCount.toLocaleString()} {t('격자점', 'grid points')}<br />{volume.source}</p>
          <div className="viewer-settings-grid">
            <label>{t('등치값 크기', 'Isovalue magnitude')}<input data-testid="viewer-isovalue" type="number" min="0" step="any" value={draftLevel} onChange={(event) => setDraftLevel(event.target.value)} /></label>
            <label>{t('불투명도', 'Opacity')}<input data-testid="viewer-opacity" type="number" min="0.05" max="1" step="0.05" value={draftOpacity} onChange={(event) => setDraftOpacity(event.target.value)} /></label>
            <button data-testid="viewer-surface-apply" type="button" onClick={() => applySurface(true)}>{t('표면 적용', 'Apply surface')}</button>
          </div>
          <p>{t('표면은 입력 격자 한 영역에만 표시하며 반복 셀에 자동 복제하지 않습니다.', 'The surface covers its supplied grid only; it is not copied to repeated cells.')}</p>
          {volume.kind === 'orbital' && <p><span className="legend-dot" style={{ background: '#8064AD' }} />+ ψ <span className="legend-dot" style={{ background: '#1EAA9A' }} />− ψ · {t('파동함수 부호이며 전하 부호가 아닙니다.', 'Wavefunction sign, not electric charge.')}</p>}
        </>}
      </fieldset>
      <fieldset className="viewer-export">
        <legend>{t('PNG 이미지 저장', 'Export PNG image')}</legend>
        <div className="viewer-settings-grid">
          <label>{t('긴 변의 해상도', 'Longest edge')}<select data-testid="viewer-export-size" value={exportSize} onChange={(event) => setExportSize(Number(event.target.value))}><option value={1600}>1600 px</option><option value={3200}>3200 px</option></select></label>
          <label>{t('이미지 배경', 'Image background')}<select data-testid="viewer-export-background" value={exportBackground} onChange={(event) => setExportBackground(event.target.value)}><option value="white">{t('흰색', 'White')}</option><option value="transparent">{t('투명', 'Transparent')}</option></select></label>
          <label className="viewer-checkbox"><input data-testid="viewer-export-distance" type="checkbox" checked={exportDistance} onChange={(event) => setExportDistance(event.target.checked)} />{t('표시 중인 거리 포함', 'Include visible distance')}</label>
          <button type="button" data-testid="viewer-export-png" disabled={exporting || Boolean(error)} onClick={() => void savePng()}>{exporting ? t('이미지 생성 중…', 'Rendering image…') : t('PNG 저장', 'Save PNG')}</button>
        </div>
        <p>{t('현재 시점과 표현을 실제 고해상도로 다시 그립니다. 투명 배경에는 화면의 그라디언트가 포함되지 않습니다.', 'Re-renders the current view at the selected resolution. Transparent images do not include the page gradient.')}</p>
      </fieldset>
    </details>
    <div data-testid="viewer-legend" className="viewer-legend" aria-label={t('색상 범례', 'Color legend')}>
      {effectiveColor === 'element' ? [...new Set(report.elements)].map((element) => <span key={element}><i className="legend-dot" style={{ background: elementColor(element) }} />{element}</span>) : effectiveColor === 'metal' ? <><span><i className="legend-dot" style={{ background: '#B9824F' }} />{t('금속 원소', 'Metal element')}</span><span><i className="legend-dot" style={{ background: '#BEC7CF' }} />{t('다른 원소', 'Other element')}</span><small>{t('물질의 금속성을 판정하지 않습니다.', 'Does not classify the material as metallic.')}</small></> : charge && <>
        <strong>{charge.kind === 'partial_charge' ? t('부분전하', 'Partial charge') : charge.kind === 'formal_charge' ? t('형식전하', 'Formal charge') : charge.kind === 'ionic_charge' ? t('이온 순전하', 'Ionic net charge') : t('산화수 · 무차원', 'Oxidation state · dimensionless')}</strong>
        <span><i className="legend-dot" style={{ background: chargeColor(colorRange[0], colorRange) }} />{colorRange[0].toPrecision(3)}</span>
        {colorRange[0] < 0 && colorRange[1] > 0 && <span><i className="legend-dot" style={{ background: chargeColor(0, colorRange) }} />0</span>}
        <span><i className="legend-dot" style={{ background: chargeColor(colorRange[1], colorRange) }} />{colorRange[1].toPrecision(3)} {charge.kind === 'oxidation_state' ? '' : 'e'}</span>
        <span><i className="legend-dot" style={{ background: chargeColor(null, colorRange) }} />{t('정보 없음', 'Unknown')}</span>
        <small>{charge.name} · {charge.method} · {charge.source}<br />{chargeRange ? t('비교 화면에서 지정한 색상 범위 · 범위를 벗어난 값은 끝 색으로 표시', 'Color range set by comparison · values beyond the range use endpoint colors') : t('이 자료의 자동 색상 범위', 'Automatic range for this dataset')}</small>
      </>}
      {(picked || highlight || Boolean(highlightedAtomIndices?.length)) && <span><i className="legend-dot" style={{ background: '#F59E0B' }} />{t('선택·검토 강조', 'Selection / review highlight')}</span>}
    </div>
    {picked && <div className="viewer-atom-detail" data-testid="viewer-atom-detail">
      <strong>{picked.element}{picked.index + 1} · [{picked.shift.join(', ')}]</strong>
      <span>{t('원자핵 전하', 'Nuclear charge')}: +{atomicNumber(picked.element)}e</span>
      {([
        ['ionic_charge', t('이온 순전하', 'Ionic net charge')],
        ['formal_charge', t('형식전하', 'Formal charge')],
        ['partial_charge', t('부분전하', 'Partial charge')],
        ['oxidation_state', t('산화수', 'Oxidation state')],
      ] as [ChargeKind, string][]).map(([kind, name]) => {
        const dataset = selectedCharge(auxiliary, settings, kind); const value = dataset?.values[picked.index];
        return <span key={kind}>{name}: {value == null ? t('정보 없음', 'Unknown') : `${value > 0 ? '+' : ''}${value}${kind === 'oxidation_state' ? '' : ' e'}`}{dataset ? ` · ${dataset.name} · ${dataset.method}` : ''}</span>;
      })}
    </div>}
    {highlight && showDistance && <p className="viewer-contact-note">{highlight.element_i}{highlight.i + 1} [{(highlight.start_shift ?? [0, 0, 0]).join(',')}] ↔ {highlight.element_j}{highlight.j + 1} [{(highlight.end_shift ?? highlight.shift).join(',')}] · {highlight.distance_angstrom.toFixed(3)} Å<br />{t('[a,b,c]는 각 격자 벡터 방향으로 이동한 셀 수입니다.', '[a,b,c] gives the integer cell translation along each lattice vector.')}</p>}
    <div data-testid="viewer-notices">
      {(showLabels && displayStats.atoms > LABEL_LIMIT) && <p className="viewer-limit" role="status">{t(`원자 번호 ${LABEL_LIMIT}/${displayStats.atoms}개 표시 · 선택한 원자 우선`, `Showing ${LABEL_LIMIT}/${displayStats.atoms} atom labels · selected atoms first`)}</p>}
      {showBonds && representation !== 'spacefill' && displayStats.capped && <p className="viewer-limit" role="status">{t(`추정 연결이 ${BOND_LIMIT.toLocaleString()}개로 제한되어 일부 연결은 표시되지 않습니다.`, `Display connections are capped at ${BOND_LIMIT.toLocaleString()}; some are omitted.`)}</p>}
    </div>
    {actionMessage && <p className="viewer-action-message" role="status">{actionMessage}</p>}
    <div className="molecule-status" aria-live="polite">
      <span>{showBonds && representation !== 'spacefill' ? labels.inferred : labels.hidden}</span>
      <span>{picked ? `${labels.picked}: ${picked.element}${picked.index + 1} · [${picked.shift.join(', ')}]` : labels.ready}</span>
    </div>
  </section>;
}
