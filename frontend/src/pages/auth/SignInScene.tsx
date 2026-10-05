import { useEffect, useRef } from 'react';

import sceneUrl from './sign-in-scene.json?url';

/**
 * The moving picture beside the sign-in form: a sales team round a table while one
 * of them walks the board's chart. Decorative only — hidden from screen readers,
 * and the page works the same if it never loads.
 *
 * "Business meeting in office" by Abdul Latif on LottieFiles, under the Lottie
 * Simple License (free for commercial use, no attribution required). It loops
 * seamlessly over 6 s.
 *
 * The player (lottie-web's SVG-only build) and the animation file are fetched
 * only once the panel shows, so neither weighs on the app's main bundle or on a
 * phone. Under `prefers-reduced-motion` it draws one still frame instead of playing.
 */

/** The frame shown still: the chart drawn and the blocks stacked. */
const STILL_FRAME = 45;

/** Tailwind's `lg`, where the sign-in page shows the panel this sits in. */
const SHOWN_FROM = '(min-width: 1024px)';

export function SignInScene({ className }: { className?: string }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let cancelled = false;
    let started = false;
    let destroy: (() => void) | undefined;

    const start = () => {
      started = true;
      import('lottie-web/build/player/lottie_light')
        .then(({ default: lottie }) => {
          if (cancelled) return;
          const animation = lottie.loadAnimation({
            container: node,
            renderer: 'svg',
            path: sceneUrl,
            loop: true,
            autoplay: !still,
          });
          if (still) animation.addEventListener('DOMLoaded', () => animation.goToAndStop(STILL_FRAME, true));
          destroy = () => animation.destroy();
        })
        // Decorative: if the player can't load, the panel keeps its words.
        .catch(() => undefined);
    };

    // The panel is hidden on narrow screens; fetch nothing until it shows.
    const shown = window.matchMedia(SHOWN_FROM);
    const onChange = () => {
      if (shown.matches && !started) start();
    };
    onChange();
    shown.addEventListener('change', onChange);

    return () => {
      cancelled = true;
      shown.removeEventListener('change', onChange);
      destroy?.();
    };
  }, []);

  return <div ref={container} aria-hidden className={className} />;
}
