/**
 * Motion switches off for a viewer who asked for less (frontend-plan §5.4, §11):
 * every transition and animation, the token durations, and the page morphs — whose
 * pseudo-elements the universal selector does not reach. And a morph never holds the
 * page frozen waiting for its far end: it starts only once the far end is ready.
 *
 * Read from disk, like the contrast test: Vitest serves CSS imports empty.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { afterEach, describe, expect, it, vi } from 'vitest';

import { canMorph, morphTo } from '@/lib/viewTransition';

const indexCss = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');
const tokensCss = readFileSync(resolve(process.cwd(), 'src/design/tokens.css'), 'utf8');

/** The body of the first `@media (prefers-reduced-motion: reduce)` block in `css`. */
function reducedMotionBlock(css: string): string {
  const at = css.indexOf('@media (prefers-reduced-motion: reduce)');
  expect(at, 'no reduced-motion block').toBeGreaterThanOrEqual(0);
  let depth = 0;
  for (let index = css.indexOf('{', at); index < css.length; index += 1) {
    if (css[index] === '{') depth += 1;
    if (css[index] === '}') depth -= 1;
    if (depth === 0) return css.slice(at, index + 1);
  }
  throw new Error('unclosed reduced-motion block');
}

describe('reduced motion', () => {
  it('makes every transition and animation instant', () => {
    const block = reducedMotionBlock(indexCss);
    expect(block).toMatch(/animation-duration:\s*0\.01ms !important/);
    expect(block).toMatch(/transition-duration:\s*0\.01ms !important/);
  });

  it('stops the page morphs, which the universal selector does not reach', () => {
    const block = reducedMotionBlock(indexCss);
    for (const pseudo of ['::view-transition-group(*)', '::view-transition-old(*)', '::view-transition-new(*)']) {
      expect(block).toContain(pseudo);
    }
    expect(block).toMatch(/animation:\s*none !important/);
  });

  it('zeroes the duration tokens the components animate with', () => {
    const block = reducedMotionBlock(tokensCss);
    for (const token of ['--dur-quick', '--dur-pop', '--dur-travel']) {
      expect(block).toMatch(new RegExp(`${token}:\\s*0ms`));
    }
  });
});

describe('morphTo', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    Reflect.deleteProperty(document, 'startViewTransition');
    document.body.innerHTML = '';
  });

  /** Records the name each call saw on `from`, and runs the update at once. */
  function offerViewTransitions(from?: HTMLElement) {
    const named: string[] = [];
    let finish: () => void = () => undefined;
    const start = vi.fn((update: () => Promise<void> | void) => {
      named.push(from?.style.getPropertyValue('view-transition-name') ?? '');
      void update();
      return { finished: new Promise<void>((resolve) => (finish = resolve)) } as ViewTransition;
    });
    Object.defineProperty(document, 'startViewTransition', { value: start, configurable: true });
    return { start, named, finish: () => finish() };
  }

  function prefersReducedMotion(reduce: boolean) {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) => ({ matches: reduce && query.includes('reduce'), media: query }) as MediaQueryList,
    );
  }

  /** A name on the register, drawn on `lines` lines (jsdom draws none). */
  function travellingName(lines = 1): HTMLElement {
    const from = document.createElement('span');
    document.body.append(from);
    from.getClientRects = () => Array.from({ length: lines }, () => new DOMRect()) as unknown as DOMRectList;
    return from;
  }

  /** A navigation that draws the dossier's title. */
  function navigation() {
    return vi.fn(() => {
      const title = document.createElement('h1');
      title.setAttribute('data-company-title', '');
      document.body.append(title);
    });
  }

  const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

  it('navigates plainly where the browser cannot morph', () => {
    const go = vi.fn();
    expect(canMorph()).toBe(false);
    morphTo(go, { from: travellingName(), name: 'n', arriveAt: '[data-company-title]', ready: Promise.resolve(true) });
    expect(go).toHaveBeenCalledTimes(1);
  });

  it('navigates plainly for a viewer who asked for less motion', () => {
    const { start } = offerViewTransitions();
    prefersReducedMotion(true);
    const go = vi.fn();
    morphTo(go, { from: travellingName(), name: 'n', arriveAt: '[data-company-title]', ready: Promise.resolve(true) });
    expect(go).toHaveBeenCalledTimes(1);
    expect(start).not.toHaveBeenCalled();
  });

  it('morphs once the far end is ready, naming only the travelling element and only while it travels', async () => {
    const from = travellingName();
    const { start, named, finish } = offerViewTransitions(from);
    prefersReducedMotion(false);
    const go = navigation();
    morphTo(go, { from, name: 'company-name-1', arriveAt: '[data-company-title]', ready: Promise.resolve(true) });
    expect(from.style.getPropertyValue('view-transition-name')).toBe('');
    await flush();
    expect(start).toHaveBeenCalledTimes(1);
    expect(go).toHaveBeenCalledTimes(1);
    expect(named).toEqual(['company-name-1']);
    finish();
    await flush();
    expect(from.style.getPropertyValue('view-transition-name')).toBe('');
  });

  it('navigates plainly when the far end is not ready in time, rather than freezing the page', async () => {
    vi.useFakeTimers();
    const { start } = offerViewTransitions();
    prefersReducedMotion(false);
    const go = vi.fn();
    morphTo(go, {
      from: travellingName(),
      name: 'n',
      arriveAt: '[data-company-title]',
      ready: new Promise<boolean>(() => undefined),
    });
    expect(go).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(100);
    expect(go).toHaveBeenCalledTimes(1);
    expect(start).not.toHaveBeenCalled();
  });

  it('navigates plainly when the far end could not be readied', async () => {
    const { start } = offerViewTransitions();
    prefersReducedMotion(false);
    const go = vi.fn();
    morphTo(go, { from: travellingName(), name: 'n', arriveAt: '[data-company-title]', ready: Promise.resolve(false) });
    await flush();
    expect(go).toHaveBeenCalledTimes(1);
    expect(start).not.toHaveBeenCalled();
  });

  it('navigates plainly for a name broken over two lines, which the browser cannot capture', async () => {
    const { start } = offerViewTransitions();
    prefersReducedMotion(false);
    const go = vi.fn();
    morphTo(go, { from: travellingName(2), name: 'n', arriveAt: '[data-company-title]', ready: Promise.resolve(true) });
    await flush();
    expect(go).toHaveBeenCalledTimes(1);
    expect(start).not.toHaveBeenCalled();
  });
});
