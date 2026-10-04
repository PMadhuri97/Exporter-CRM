/**
 * Replays the `settle` rise (`tailwind.config.ts`'s keyframes, §5.4) on content that
 * changed in place. Restarting the CSS animation would mean remounting the element,
 * and with it every row inside; this animates the element that is already there.
 *
 * The duration is the `--dur-pop` token, which reduced motion sets to 0, and then
 * nothing plays. Where the Web Animations API is missing, nothing plays either.
 */
export function settle(element: HTMLElement | null): void {
  if (!element || typeof element.animate !== 'function') return;
  const duration = Number.parseFloat(getComputedStyle(element).getPropertyValue('--dur-pop'));
  if (!(duration > 0)) return;
  element.animate(
    [
      { opacity: 0, transform: 'translateY(3px)' },
      { opacity: 1, transform: 'translateY(0)' },
    ],
    { duration, easing: 'cubic-bezier(.2,.8,.2,1)' },
  );
}
