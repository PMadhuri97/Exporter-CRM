/**
 * A list's sort, kept in the URL as `?sort=` and `?order=` — the state behind `SortMenu`.
 *
 * Both are written in one update: two separate writes in the same tick would each start
 * from the old URL, and the second would undo the first. The default leaves the URL
 * clean. A page that already writes the URL for other reasons (a selection to clear at
 * the same time) may write `sort` and `order` itself in its own single update.
 */

import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

export type SortDirection = 'asc' | 'desc';

export interface SortState<K extends string> {
  key: K;
  order: SortDirection;
}

export interface SortColumn<K extends string> {
  key: K;
  label: string;
  /** The direction a first click sorts in: `asc` for names, `desc` for dates. */
  firstOrder: SortDirection;
}

const DIRECTIONS: readonly SortDirection[] = ['asc', 'desc'];

/** The list's sort, read from and written to `?sort=` and `?order=`. */
export function useSortParams<K extends string>(
  columns: readonly SortColumn<K>[],
  fallback: SortState<K>,
): [SortState<K>, (next: SortState<K>) => void] {
  const [params, setParams] = useSearchParams();
  const rawKey = params.get('sort');
  const rawOrder = params.get('order');
  const key = columns.some((column) => column.key === rawKey) ? (rawKey as K) : fallback.key;
  const order =
    rawOrder !== null && (DIRECTIONS as readonly string[]).includes(rawOrder)
      ? (rawOrder as SortDirection)
      : key === fallback.key
        ? fallback.order
        : (columns.find((column) => column.key === key)?.firstOrder ?? fallback.order);

  const setSort = useCallback(
    (next: SortState<K>) => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current);
          // The default leaves the URL clean.
          if (next.key === fallback.key && next.order === fallback.order) {
            updated.delete('sort');
            updated.delete('order');
          } else {
            updated.set('sort', next.key);
            updated.set('order', next.order);
          }
          return updated;
        },
        { replace: true },
      );
    },
    [fallback.key, fallback.order, setParams],
  );

  return [{ key, order }, setSort];
}
