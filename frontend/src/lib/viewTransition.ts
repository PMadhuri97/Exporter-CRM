/**
 * A page change that morphs (frontend-plan §5.4, §12.3): the register's company name
 * travels into the dossier's title. It uses the browser's View Transitions where they
 * exist and the viewer has not asked for less motion; anywhere else the navigation
 * simply happens, with nothing lost.
 *
 * React Router's own `viewTransition` prop works only under a data router, and this
 * app mounts `<BrowserRouter>`, so the transition is started here instead.
 *
 * While a transition's update runs the browser shows a frozen picture of the old page,
 * so the morph keeps that short:
 * - Only the element that travels is named, and only for this morph. The browser
 *   captures every named element on its own; a register naming all 50 rows made it
 *   capture 50.
 * - The far end must be able to draw at once — its code loaded, its record cached —
 *   before the transition starts. Waiting for it inside the transition froze the page
 *   for over 300 ms; a click whose far end is not ready in time navigates plainly.
 * - The router runs every navigation inside `startTransition`, which `flushSync`
 *   cannot flush, so the update watches the page for the far end's arrival.
 */

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

/** Longest a click waits for the far end to be ready before navigating without the morph. */
const READY_LIMIT_MS = 100;

/** Longest the frozen picture is held for the far end to draw. It is ready, so normally a frame or two. */
const ARRIVAL_LIMIT_MS = 250;

/** Whether a navigation may morph here: the API exists and motion is welcome. */
export function canMorph(): boolean {
  if (typeof document === 'undefined' || typeof document.startViewTransition !== 'function') {
    return false;
  }
  return !(window.matchMedia?.(REDUCED_MOTION).matches ?? false);
}

/** The `view-transition-name` for one company's name — the same on both pages. */
export function companyNameTransition(companyId: string): string {
  return `company-name-${companyId.replace(/[^A-Za-z0-9_-]/g, '')}`;
}

/** Whether `ready` resolves `true` within `limitMs`. */
function readyWithin(ready: Promise<boolean>, limitMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), limitMs);
    ready.then(
      (isReady) => {
        clearTimeout(timer);
        resolve(isReady);
      },
      () => {
        clearTimeout(timer);
        resolve(false);
      },
    );
  });
}

/**
 * Resolves once `selector` is on the page, or after the limit. Watched with a
 * MutationObserver: its callbacks still run while a view transition holds rendering,
 * which animation frames do not.
 */
function arrival(selector: string): Promise<void> {
  return new Promise((resolve) => {
    if (document.querySelector(selector)) {
      resolve();
      return;
    }
    const done = () => {
      observer.disconnect();
      clearTimeout(timer);
      resolve();
    };
    const observer = new MutationObserver(() => {
      if (document.querySelector(selector)) done();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    const timer = setTimeout(done, ARRIVAL_LIMIT_MS);
  });
}

export interface Morph {
  /** The element that travels. A box broken over two lines cannot be captured, so it then does not morph. */
  from: Element | null;
  /** The name it travels under; the far end carries the same one. */
  name: string;
  /** The far end, as a selector: the new page is captured once it is there. */
  arriveAt: string;
  /** Resolves `true` once the far end can draw at once (its code and its data loaded). */
  ready: Promise<boolean>;
}

/**
 * Runs `go` (a navigation), morphing `from` into the far end when the browser can and
 * the far end is ready in time; otherwise `go` simply runs.
 */
export function morphTo(go: () => void, { from, name, arriveAt, ready }: Morph): void {
  if (!canMorph() || !(from instanceof HTMLElement)) {
    go();
    return;
  }
  void readyWithin(ready, READY_LIMIT_MS).then((isReady) => {
    if (!isReady || !from.isConnected || from.getClientRects().length !== 1) {
      go();
      return;
    }
    from.style.setProperty('view-transition-name', name);
    const transition = document.startViewTransition(async () => {
      go();
      await arrival(arriveAt);
    });
    const unname = () => from.style.removeProperty('view-transition-name');
    transition.finished.then(unname, unname);
  });
}

/** A click the browser would open elsewhere (new tab, window, download) is left alone. */
export function isPlainClick(event: {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
  defaultPrevented: boolean;
}): boolean {
  return (
    !event.defaultPrevented &&
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey
  );
}
