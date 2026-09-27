import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * One query-string parameter as state — the selected tab of a page, so a link,
 * a reload or the back button lands on the same tab.
 *
 * A value outside `allowed` (a stale bookmark, a hand-typed URL) reads as
 * `fallback` rather than rendering an empty tab. Setting the fallback removes
 * the parameter, keeping the plain URL canonical. Changes replace the history
 * entry: switching tabs is not navigation the back button should replay.
 */
export function useSearchParamState<T extends string>(
  name: string,
  allowed: readonly T[],
  fallback: T,
): [T, (value: T) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get(name);
  const value = raw !== null && (allowed as readonly string[]).includes(raw) ? (raw as T) : fallback;

  const setValue = useCallback(
    (next: T) => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current);
          if (next === fallback) updated.delete(name);
          else updated.set(name, next);
          return updated;
        },
        { replace: true },
      );
    },
    [name, fallback, setParams],
  );

  return [value, setValue];
}
