interface CameraViewer {
  getView(): number[];
  setView(view: number[], nolink?: boolean): unknown;
  setViewChangeCallback(callback: ((view: number[]) => void) | null): void;
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
  first.setViewChangeCallback(() => synchronize(first, second));
  second.setViewChangeCallback(() => synchronize(second, first));
  synchronize(first, second);
  return () => {
    active = false;
    first.setViewChangeCallback(null);
    second.setViewChangeCallback(null);
  };
}
