/**
 * Every icon the app draws, named by what it means (frontend-plan §5.8).
 *
 * Screens say `<Icon.followUp />`, never a glyph's own name, so the set can change
 * in one place: `icon-names.ts`. The shapes are Fluent UI System Icons' (20 px,
 * regular style, as Dynamics 365 draws them), copied into `icon-paths.ts` by
 * `scripts/build-icons.mjs` so the bundle carries only the glyphs it draws.
 *
 * A glyph carries meaning only beside a label or a shape: pass `aria-hidden` where
 * the text next to it already says the thing, and an `aria-label` on the control
 * where it does not.
 */

import { createElement, forwardRef, type SVGProps } from 'react';

import { ICON_NAMES, type IconName } from './icon-names';
import { ICON_PATHS } from './icon-paths';

export type { IconName } from './icon-names';

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'ref'> {
  /** Pixels (or any CSS length). Defaults to the text size, `1em`. */
  size?: number | string;
  /** `fill` exists for the glyphs listed in `FILLED`; others draw `regular`. */
  weight?: 'regular' | 'fill';
}

export type IconComponent = ReturnType<typeof makeIcon>;

function makeIcon(glyph: string) {
  const drawn = ICON_PATHS[glyph];
  const component = forwardRef<SVGSVGElement, IconProps>(function FluentGlyph(
    { size = '1em', weight = 'regular', ...rest },
    ref,
  ) {
    const shapes = (weight === 'fill' && drawn?.fill) || drawn?.regular || [];
    return createElement(
      'svg',
      {
        ref,
        xmlns: 'http://www.w3.org/2000/svg',
        viewBox: '0 0 20 20',
        width: size,
        height: size,
        fill: 'currentColor',
        focusable: 'false',
        ...rest,
      },
      ...shapes.map(([tag, attrs], index) => createElement(tag, { key: index, ...attrs })),
    );
  });
  component.displayName = `Icon(${glyph})`;
  return component;
}

export const Icon = Object.fromEntries(
  Object.entries(ICON_NAMES).map(([key, glyph]) => [key, makeIcon(glyph)]),
) as Record<IconName, IconComponent>;
