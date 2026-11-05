interface CameraViewer {
  getView(): number[];
  setView(view: number[], nolink?: boolean): unknown;
  setViewChangeCallback(callback: ((view: number[]) => void) | null): void;
}

const listeners = new WeakMap<CameraViewer, Set<(view: number[]) => void>>();

/** Share 3Dmol's single public camera callback between persistence and linking. */
export function observeCamera(viewer: CameraViewer, callback: (view: number[]) => void): () => void {
  let callbacks = listeners.get(viewer);
  if (!callbacks) {
    callbacks = new Set(); listeners.set(viewer, callbacks);
    viewer.setViewChangeCallback((view) => {
      for (const listener of listeners.get(viewer) ?? []) listener(view);
    });
  }
  callbacks.add(callback);
  return () => {
    callbacks.delete(callback);
    if (callbacks.size === 0) { viewer.setViewChangeCallback(null); listeners.delete(viewer); }
  };
}

/** Share orientation and zoom, preserving each structure's own center and pan. */
export function linkCameraViews(first: CameraViewer, second: CameraViewer): () => void {
  let updating = false;
  let active = true;
  function synchronize(source: CameraViewer, target: CameraViewer) {
    if (!active || updating) return;
    const from = source.getView();
    const to = target.getView();
    if (from.length < 8 || to.length < 8
      || !from.slice(3, 8).every(Number.isFinite)
      || from.slice(3, 8).every((value, index) => Math.abs(value - to[index + 3]) < 1e-10)) return;
    updating = true;
    try {
      target.setView([...to.slice(0, 3), ...from.slice(3, 8), ...to.slice(8)], true);
    } finally {
      updating = false;
    }
  }
  const stopFirst = observeCamera(first, () => synchronize(first, second));
  const stopSecond = observeCamera(second, () => synchronize(second, first));
  synchronize(first, second);
  return () => {
    active = false;
    stopFirst(); stopSecond();
  };
}
