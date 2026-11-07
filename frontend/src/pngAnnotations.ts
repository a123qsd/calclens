export interface PNGAnnotation {
  title: string;
  lines: string[];
  swatches: { label: string; color: string }[];
}

export const PNG_LIMITS = {
  maxDimension: 8192,
  maxArea: 32 * 1024 * 1024,
  maxDataUrlLength: 64 * 1024 * 1024,
  maxTextLength: 32768,
  maxLines: 64,
  maxSwatches: 32,
} as const;

interface TextPlacement {
  text: string;
  x: number;
  y: number;
  fontSize: number;
  bold: boolean;
}

export interface PNGAnnotationLayout {
  width: number;
  height: number;
  sourceHeight: number;
  footerHeight: number;
  texts: TextPlacement[];
  swatches: { x: number; y: number; size: number; color: string }[];
}

function checkDimensions(width: number, height: number): void {
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height)
    || width < 64 || height < 1 || width > PNG_LIMITS.maxDimension
    || height > PNG_LIMITS.maxDimension) {
    throw new Error(`PNG dimensions must have width 64–${PNG_LIMITS.maxDimension} and height 1–${PNG_LIMITS.maxDimension} pixels.`);
  }
  if (width * height > PNG_LIMITS.maxArea) {
    throw new Error(`Annotated PNG exceeds the ${PNG_LIMITS.maxArea}-pixel canvas area limit.`);
  }
}

function checkAnnotation(annotation: PNGAnnotation): void {
  if (!annotation || typeof annotation.title !== 'string'
    || !Array.isArray(annotation.lines) || !Array.isArray(annotation.swatches)
    || annotation.lines.length > PNG_LIMITS.maxLines
    || annotation.swatches.length > PNG_LIMITS.maxSwatches) {
    throw new Error(`PNG annotation requires a title, at most ${PNG_LIMITS.maxLines} lines and ${PNG_LIMITS.maxSwatches} swatches.`);
  }
  const labels = [annotation.title, ...annotation.lines];
  for (const swatch of annotation.swatches) {
    if (!swatch || typeof swatch.label !== 'string' || typeof swatch.color !== 'string'
      || !swatch.color.trim() || swatch.color.length > 128) {
      throw new Error('Each PNG swatch needs a text label and a valid color of at most 128 characters.');
    }
    labels.push(swatch.label);
  }
  if (labels.some(value => typeof value !== 'string')
    || labels.reduce((sum, value) => sum + value.length, 0) > PNG_LIMITS.maxTextLength) {
    throw new Error(`PNG annotation text exceeds the ${PNG_LIMITS.maxTextLength}-character limit or contains a non-text value.`);
  }
}

/** Wrap words, splitting long identifiers only at Unicode grapheme boundaries. */
export function wrapPngText(text: string, maxWidth: number, measure: (text: string) => number): string[] {
  if (typeof text !== 'string' || text.length > PNG_LIMITS.maxTextLength) {
    throw new Error(`PNG text must contain at most ${PNG_LIMITS.maxTextLength} characters.`);
  }
  if (!Number.isFinite(maxWidth) || maxWidth <= 0) {
    throw new Error('PNG text width must be finite and positive.');
  }
  const fits = (value: string): boolean => {
    const width = measure(value);
    if (!Number.isFinite(width) || width < 0) throw new Error('PNG text measurement must be finite and nonnegative.');
    return width <= maxWidth;
  };
  const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
  const result: string[] = [];
  for (const paragraph of text.split(/\r\n|\r|\n/u)) {
    let line = '';
    for (const word of paragraph.match(/\S+/gu) ?? []) {
      const candidate = line ? `${line} ${word}` : word;
      if (fits(candidate)) {
        line = candidate;
        continue;
      }
      if (line) result.push(line);
      line = '';
      for (const { segment } of segmenter.segment(word)) {
        if (!fits(segment)) throw new Error('A PNG text character cannot fit within the available width.');
        if (line && !fits(line + segment)) {
          result.push(line);
          line = '';
        }
        line += segment;
      }
    }
    result.push(line);
  }
  return result;
}

/** Pure layout; the caller supplies actual font metrics when rendering. */
export function layoutPngAnnotation(
  width: number,
  sourceHeight: number,
  annotation: PNGAnnotation,
  measure: (text: string, fontSize: number, bold: boolean) => number,
): PNGAnnotationLayout {
  checkDimensions(width, sourceHeight);
  checkAnnotation(annotation);
  const fontSize = Math.max(12, Math.round(width / 64));
  const padding = Math.max(12, Math.round(width / 64));
  const lineHeight = Math.ceil(fontSize * 1.45);
  const contentWidth = width - 2 * padding;
  const texts: TextPlacement[] = [];
  const swatches: PNGAnnotationLayout['swatches'] = [];
  let y = sourceHeight + padding;
  const addText = (text: string, size: number, bold: boolean): void => {
    for (const line of wrapPngText(text, contentWidth, value => measure(value, size, bold))) {
      texts.push({ text: line, x: padding, y, fontSize: size, bold });
      y += Math.ceil(size * 1.45);
    }
  };
  if (annotation.title) {
    addText(annotation.title, Math.round(fontSize * 1.2), true);
    y += Math.ceil(fontSize / 2);
  }
  for (const line of annotation.lines) addText(line, fontSize, false);
  if (annotation.swatches.length && texts.length) y += Math.ceil(fontSize / 2);
  const size = fontSize;
  const gap = Math.ceil(fontSize / 2);
  let x = padding;
  let rowHeight = 0;
  for (const swatch of annotation.swatches) {
    const lines = wrapPngText(swatch.label, contentWidth - size - gap,
      value => measure(value, fontSize, false));
    const labelWidth = Math.max(0, ...lines.map(value => measure(value, fontSize, false)));
    const itemWidth = size + gap + labelWidth;
    if (x > padding && x + itemWidth > width - padding) {
      y += rowHeight + gap;
      x = padding;
      rowHeight = 0;
    }
    swatches.push({ x, y, size, color: swatch.color });
    lines.forEach((text, index) => texts.push({
      text, x: x + size + gap, y: y + index * lineHeight, fontSize, bold: false,
    }));
    rowHeight = Math.max(rowHeight, size, lines.length * lineHeight);
    x += itemWidth + 2 * fontSize;
  }
  const height = Math.ceil(y + rowHeight + padding);
  checkDimensions(width, height);
  return { width, height, sourceHeight, footerHeight: height - sourceHeight, texts, swatches };
}

/** Inspect the PNG header before asking the browser to allocate decoded pixels. */
export function pngDataUrlDimensions(dataUrl: string): { width: number; height: number } {
  if (typeof dataUrl !== 'string' || dataUrl.length > PNG_LIMITS.maxDataUrlLength
    || !/^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/u.test(dataUrl)) {
    throw new Error('PNG export requires a base64 data:image/png URL within the 64 MiB text limit.');
  }
  let header: string;
  try {
    header = atob(dataUrl.slice(dataUrl.indexOf(',') + 1, dataUrl.indexOf(',') + 45));
  } catch {
    throw new Error('PNG export contains invalid base64 data.');
  }
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (header.length < 24 || signature.some((value, index) => header.charCodeAt(index) !== value)
    || header.slice(12, 16) !== 'IHDR'
    || [8, 9, 10, 11].some((index, offset) => header.charCodeAt(index) !== [0, 0, 0, 13][offset])) {
    throw new Error('PNG export contains an invalid PNG header.');
  }
  const number = (offset: number): number => [0, 1, 2, 3]
    .reduce((value, index) => value * 256 + header.charCodeAt(offset + index), 0);
  const width = number(16);
  const height = number(20);
  checkDimensions(width, height);
  return { width, height };
}

function font(size: number, bold: boolean): string {
  return `${bold ? '600 ' : ''}${size}px sans-serif`;
}

export async function annotatePng(
  dataUrl: string,
  annotation: PNGAnnotation,
): Promise<{ dataUrl: string; width: number; height: number }> {
  const dimensions = pngDataUrlDimensions(dataUrl);
  checkAnnotation(annotation);
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  if (!context) throw new Error('A Canvas 2D context is required for annotated PNG export.');
  const layout = layoutPngAnnotation(dimensions.width, dimensions.height, annotation, (text, size, bold) => {
    context.font = font(size, bold);
    return context.measureText(text).width;
  });
  for (const swatch of annotation.swatches) {
    context.fillStyle = '#010203';
    context.fillStyle = swatch.color;
    const first = context.fillStyle;
    context.fillStyle = '#040506';
    context.fillStyle = swatch.color;
    if (context.fillStyle !== first) throw new Error(`Invalid PNG swatch color: ${swatch.color}`);
  }
  const source = new Image();
  source.decoding = 'async';
  source.src = dataUrl;
  try {
    await source.decode();
  } catch {
    throw new Error('The PNG image could not be decoded for annotation.');
  }
  if (source.naturalWidth !== dimensions.width || source.naturalHeight !== dimensions.height) {
    throw new Error('Decoded PNG dimensions disagree with its header.');
  }
  canvas.width = layout.width;
  canvas.height = layout.height;
  context.drawImage(source, 0, 0);
  context.fillStyle = '#ffffff';
  context.fillRect(0, layout.sourceHeight, layout.width, layout.footerHeight);
  context.textBaseline = 'top';
  for (const swatch of layout.swatches) {
    context.fillStyle = swatch.color;
    context.fillRect(swatch.x, swatch.y, swatch.size, swatch.size);
  }
  context.fillStyle = '#111827';
  for (const placement of layout.texts) {
    context.font = font(placement.fontSize, placement.bold);
    context.fillText(placement.text, placement.x, placement.y);
  }
  return { dataUrl: canvas.toDataURL('image/png'), width: layout.width, height: layout.height };
}
