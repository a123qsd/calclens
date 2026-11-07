import assert from 'node:assert/strict';
import test from 'node:test';
import { layoutPngAnnotation, PNG_LIMITS, pngDataUrlDimensions, wrapPngText } from './pngAnnotations.ts';
import type { PNGAnnotation } from './pngAnnotations.ts';

const annotation: PNGAnnotation = { title: 'CalcLens', lines: ['검토용 구조 / Structure'], swatches: [] };
const measure = (text: string, size = 1): number => Array.from(text).length * size;

test('word wrapping preserves long scientific identifiers without truncation', () => {
  const hash = '0123456789abcdef'.repeat(4);
  const lines = wrapPngText(`SHA-256 ${hash}`, 16, measure);
  assert.equal(lines[0], 'SHA-256');
  assert.equal(lines.slice(1).join(''), hash);
  assert.ok(lines.every(line => measure(line) <= 16));
});

test('wrapping handles Korean and preserves complete Unicode graphemes', () => {
  assert.deepEqual(wrapPngText('원자핵기준두께', 3, measure), ['원자핵', '기준두', '께']);
  assert.deepEqual(wrapPngText('👩‍🔬👩‍🔬', 3, measure), ['👩‍🔬', '👩‍🔬']);
  assert.deepEqual(wrapPngText('a\r\n\r\nb', 4, measure), ['a', '', 'b']);
  assert.deepEqual(wrapPngText('', 4, measure), ['']);
});

test('wrapping rejects impossible widths and invalid metrics', () => {
  for (const width of [0, -1, Infinity, NaN]) assert.throws(() => wrapPngText('x', width, measure), /width/);
  assert.throws(() => wrapPngText('x', 1, () => 2), /cannot fit/);
  assert.throws(() => wrapPngText('x', 1, () => NaN), /measurement/);
  assert.throws(() => wrapPngText('x'.repeat(PNG_LIMITS.maxTextLength + 1), 10, measure), /character/);
});

test('layout scales fonts and keeps every annotation below the source image', () => {
  let previousSize = 0;
  for (const width of [800, 1600, 3200]) {
    const sourceHeight = width * 3 / 4;
    const layout = layoutPngAnnotation(width, sourceHeight, annotation, measure);
    assert.equal(layout.width, width);
    assert.equal(layout.sourceHeight, sourceHeight);
    assert.equal(layout.height, sourceHeight + layout.footerHeight);
    assert.ok(layout.footerHeight > 0);
    assert.ok(layout.texts.every(item => item.y >= sourceHeight && item.x >= 0));
    assert.ok(layout.texts[0].fontSize > previousSize);
    previousSize = layout.texts[0].fontSize;
  }
});

test('swatches wrap long labels and flow to additional rows within the footer', () => {
  const longLabel = 'source'.repeat(30);
  const layout = layoutPngAnnotation(800, 600, {
    title: '', lines: [], swatches: Array.from({ length: 4 }, () => ({ label: longLabel, color: '#123456' })),
  }, measure);
  assert.equal(layout.swatches.length, 4);
  assert.ok(layout.swatches[1].y > layout.swatches[0].y);
  assert.equal(layout.texts.map(item => item.text).join(''), longLabel.repeat(4));
  assert.ok(layout.texts.every(item => item.x + measure(item.text, item.fontSize) <= layout.width));
  assert.ok(layout.texts.every(item => item.y + item.fontSize <= layout.height));
});

test('layout accepts empty annotations but rejects dimension, area and text overflow', () => {
  assert.ok(layoutPngAnnotation(800, 600, { title: '', lines: [], swatches: [] }, measure).footerHeight > 0);
  for (const [width, height] of [[0, 600], [63, 600], [800.5, 600], [8193, 600], [800, 8193]]) {
    assert.throws(() => layoutPngAnnotation(width, height, annotation, measure), /dimensions/);
  }
  assert.throws(() => layoutPngAnnotation(8192, 4096, annotation, measure), /area limit/);
  assert.throws(() => layoutPngAnnotation(800, 8190, annotation, measure), /dimensions/);
  assert.throws(() => layoutPngAnnotation(800, 600, { ...annotation, lines: Array(65).fill('x') }, measure), /at most/);
  assert.throws(() => layoutPngAnnotation(800, 600, { ...annotation, title: 'x'.repeat(32769) }, measure), /character/);
});

function pngHeader(width: number, height: number): string {
  const bytes = Buffer.alloc(33);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(bytes);
  bytes.writeUInt32BE(13, 8);
  bytes.write('IHDR', 12);
  bytes.writeUInt32BE(width, 16);
  bytes.writeUInt32BE(height, 20);
  return `data:image/png;base64,${bytes.toString('base64')}`;
}

test('PNG header checks reject external URLs, other image kinds and excessive decode dimensions', () => {
  assert.deepEqual(pngDataUrlDimensions(pngHeader(800, 600)), { width: 800, height: 600 });
  for (const source of ['https://example.com/a.png', 'data:image/jpeg;base64,AAAA', 'data:image/png;base64,AAAA']) {
    assert.throws(() => pngDataUrlDimensions(source), /PNG|image\/png/);
  }
  assert.throws(() => pngDataUrlDimensions(pngHeader(8193, 600)), /dimensions/);
  assert.throws(() => pngDataUrlDimensions(pngHeader(8192, 8192)), /area limit/);
});
