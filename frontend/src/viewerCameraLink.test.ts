import assert from 'node:assert/strict';
import test from 'node:test';
import { linkCameraViews } from './viewerCameraLink.ts';

function camera(initial: number[]) {
  let view = initial.slice();
  let callback: ((view: number[]) => void) | null = null;
  let updates = 0;
  return {
    getView: () => view.slice(),
    setView(next: number[]) { view = next.slice(); updates += 1; callback?.(view); },
    setViewChangeCallback(next: typeof callback) { callback = next; },
    emit: () => callback?.(view),
    get updates() { return updates; },
  };
}

test('linked cameras preserve different structure centers and pan without feedback loops', () => {
  const first = camera([1, 2, 3, -50, 0, 0, 0, 1, 4, 5]);
  const second = camera([11, 12, 13, -10, 1, 0, 0, 0, 14, 15]);
  const unlink = linkCameraViews(first, second);
  assert.deepEqual(second.getView(), [11, 12, 13, -50, 0, 0, 0, 1, 14, 15]);
  assert.equal(second.updates, 1);
  assert.equal(first.updates, 0);
  first.emit(); second.emit();
  assert.equal(second.updates, 1);
  second.setView([11, 12, 13, -25, 0, 1, 0, 0, 14, 15]);
  assert.deepEqual(first.getView(), [1, 2, 3, -25, 0, 1, 0, 0, 4, 5]);
  assert.equal(first.updates, 1);
  unlink();
  second.setView([11, 12, 13, -75, 0, 0, 1, 0]);
  assert.equal(first.getView()[3], -25);
});
