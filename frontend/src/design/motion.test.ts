/**
 * Motion switches off for a viewer who asked for less (frontend-plan §5.6, §11):
 * every transition and animation, and the token durations the components use.
 *
 * Read from disk, like the contrast test: Vitest serves CSS imports empty.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

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

  it('zeroes the duration tokens the components animate with', () => {
    const block = reducedMotionBlock(tokensCss);
    for (const token of ['--dur-quick', '--dur-pop']) {
      expect(block).toMatch(new RegExp(`${token}:\\s*0ms`));
    }
  });
});

describe('page motion', () => {
  it('has no page morphs: only menus, popovers, dialogs and the side panel move', () => {
    expect(indexCss).not.toMatch(/view-transition/);
  });
});
