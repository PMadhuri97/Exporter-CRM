/**
 * The generated shapes cover the names (frontend-plan §5.5): every glyph in
 * `icon-names.ts` has its regular paths in `icon-paths.ts`, and every glyph in
 * `FILLED` its filled ones. Fails after an edit to the names until
 * `pnpm icons` (scripts/build-icons.mjs) is run again.
 */

import { render } from '@testing-library/react';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';

import { FILLED, ICON_NAMES } from './icon-names';
import { ICON_PATHS } from './icon-paths';
import { Icon } from './icons';

describe('icons', () => {
  it.each(Object.entries(ICON_NAMES))('%s (%s) has its regular shapes', (_key, glyph) => {
    expect(ICON_PATHS[glyph]?.regular.length ?? 0).toBeGreaterThan(0);
  });

  it.each(FILLED)('%s has a filled weight for the active rail row', (key) => {
    expect(ICON_PATHS[ICON_NAMES[key]]?.fill?.length ?? 0).toBeGreaterThan(0);
  });

  it('draws a 256-unit glyph in the current colour, at the size asked', () => {
    const { container } = render(createElement(Icon.desk, { size: 18, 'aria-hidden': true }));
    const svg = container.querySelector('svg')!;
    expect(svg).toHaveAttribute('viewBox', '0 0 256 256');
    expect(svg).toHaveAttribute('width', '18');
    expect(svg).toHaveAttribute('fill', 'currentColor');
    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(svg.querySelector('path')).not.toBeNull();
  });
});
