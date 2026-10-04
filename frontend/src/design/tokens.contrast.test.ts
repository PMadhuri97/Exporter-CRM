/**
 * The tokens meet WCAG AA in both themes (frontend-plan §5.2, §11).
 *
 * jsdom does not compute colours, so axe cannot check contrast in a unit test; this
 * reads `tokens.css` itself and does the arithmetic. Text pairs need 4.5:1; the
 * solids — dots, lamps, fills that carry a state beside a label — need 3:1 against
 * the surfaces they sit on. A token change that breaks a pair fails here.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

// Read from disk: Vitest serves CSS imports empty, `?raw` included, and under jsdom
// `import.meta.url` is not a file URL. Vitest runs from the frontend root.
const css = readFileSync(resolve(process.cwd(), 'src/design/tokens.css'), 'utf8');

type Rgb = [number, number, number];

function block(selectorStart: string): Record<string, Rgb> {
  const at = css.indexOf(selectorStart);
  expect(at, `no block starting ${selectorStart}`).toBeGreaterThanOrEqual(0);
  const open = css.indexOf('{', at);
  const close = css.indexOf('}', open);
  const vars: Record<string, Rgb> = {};
  for (const match of css.slice(open, close).matchAll(/--([a-z0-9-]+):\s*(\d+) (\d+) (\d+);/g)) {
    vars[match[1]!] = [Number(match[2]), Number(match[3]), Number(match[4])];
  }
  return vars;
}

function luminance([r, g, b]: Rgb): number {
  const [lr, lg, lb] = [r, g, b].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as Rgb;
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
}

function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const LIGHT = block(':root,');
const DARK = block("[data-theme='dark'] {");
const SYSTEM_DARK = block(":root:not([data-theme='light'])");
const WHITE: Rgb = [255, 255, 255];
const MEANINGS = ['positive', 'negative', 'attention', 'progress', 'idle'] as const;
const SURFACES = ['surface', 'paper', 'raised'] as const;

describe.each([
  ['light', LIGHT],
  ['dark', DARK],
])('the %s theme', (_name, theme) => {
  const t = (name: string): Rgb => {
    const value = theme[name];
    expect(value, `--${name} is missing`).toBeDefined();
    return value!;
  };

  it.each(['ink', 'ink-2', 'ink-3'])('%s is readable on every surface and in wells', (ink) => {
    for (const surface of [...SURFACES, 'sunken']) {
      expect(contrast(t(ink), t(surface)), `${ink} on ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(MEANINGS)('%s text is readable on the surfaces and on its own tint', (meaning) => {
    for (const background of [...SURFACES, `${meaning}-tint`]) {
      expect(contrast(t(meaning), t(background)), `${meaning} on ${background}`).toBeGreaterThanOrEqual(
        4.5,
      );
    }
  });

  it.each(MEANINGS)('the %s solid stands out as a lamp or dot', (meaning) => {
    for (const surface of SURFACES) {
      expect(contrast(t(`${meaning}-solid`), t(surface)), `${meaning}-solid on ${surface}`).toBeGreaterThanOrEqual(3);
    }
  });

  it('keeps the primary button and CRITICAL legible', () => {
    // Primary: paper text on an ink fill. CRITICAL: white on the negative solid.
    expect(contrast(t('paper'), t('ink'))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(WHITE, t('negative-solid'))).toBeGreaterThanOrEqual(4.5);
  });
});

describe('the two dark blocks', () => {
  it('are the same palette, so `data-theme="dark"` and the system preference agree', () => {
    expect(SYSTEM_DARK).toEqual(DARK);
    expect(Object.keys(DARK).sort()).toEqual(Object.keys(LIGHT).sort());
  });
});
