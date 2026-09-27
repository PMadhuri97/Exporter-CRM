/**
 * Joins class names and resolves Tailwind conflicts, so a component's default
 * classes can be overridden by a caller's `className` (`px-3` then `px-4`
 * keeps only `px-4`) instead of both landing in the DOM and the stylesheet's
 * order deciding.
 */

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
