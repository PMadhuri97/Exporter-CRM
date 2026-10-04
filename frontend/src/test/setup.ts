import '@testing-library/jest-dom/vitest';

// jsdom leaves out a few browser APIs that Radix (popovers, hover cards, toggle
// groups, selects) and cmdk call. Each stub is the smallest thing that lets the
// component run; none of them is asserted on.

if (!('ResizeObserver' in globalThis)) {
  class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(globalThis, 'ResizeObserver', { value: ResizeObserver, writable: true });
}

if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => undefined;
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => undefined;
}
