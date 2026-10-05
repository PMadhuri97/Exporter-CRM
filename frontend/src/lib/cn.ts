/**
 * Joins class names and resolves Tailwind conflicts, so a component's default
 * classes can be overridden by a caller's `className` (`px-3` then `px-4`
 * keeps only `px-4`) instead of both landing in the DOM and the stylesheet's
 * order deciding.
 *
 * tailwind-merge has to be told the type scale's names (`tailwind.config.ts`
 * `fontSize`): it reads an unknown `text-*` as a colour, so without this
 * `text-ink-2 text-secondary` would lose the colour to the size.
 */

import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': [
        {
          text: ['caption', 'secondary', 'body', 'heading', 'title', 'count'],
        },
      ],
      shadow: [{ shadow: ['float'] }],
      duration: [{ duration: ['quick', 'pop'] }],
      ease: [{ ease: ['enter', 'exit'] }],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
