/**
 * Which columns an export writes, chosen before it is written.
 *
 * Teams want different files out of the same list: sales wants who and where,
 * operations wants the checks and the paperwork. One file holding every column serves
 * neither — the columns you did not want are the ones you scroll past.
 *
 * **The choice is remembered on this browser** (`localStorage`), because it is a team's
 * habit rather than a one-off: whoever exports the same columns every week should not
 * re-tick them every week. It is per-viewer and never leaves the machine, so two people
 * on the same screen keep their own. If storage is unavailable — a private window, a
 * blocked origin — the picker opens on the defaults and the export still works.
 */

import { useEffect, useState } from 'react';

import { Button, Sheet } from '@/components';

import { DEFAULT_COLUMN_IDS, EXPORT_COLUMNS, type ExportColumn } from '../exportCompanies';

/** Per viewer, per browser. Versioned so a later change to the ids can retire it. */
const REMEMBERED = 'aner.companies.exportColumns.v1';

/** The remembered choice, or the defaults. Never throws: storage can be unavailable. */
function rememberedColumnIds(): string[] {
  try {
    const stored = window.localStorage.getItem(REMEMBERED);
    if (!stored) return [...DEFAULT_COLUMN_IDS];
    const parsed: unknown = JSON.parse(stored);
    if (!Array.isArray(parsed)) return [...DEFAULT_COLUMN_IDS];
    // Only ids that still exist: a column removed since the choice was made would
    // otherwise be an empty column in every export from this browser.
    const known = new Set(EXPORT_COLUMNS.map((column) => column.id));
    const ids = parsed.filter((id): id is string => typeof id === 'string' && known.has(id));
    return ids.length > 0 ? ids : [...DEFAULT_COLUMN_IDS];
  } catch {
    return [...DEFAULT_COLUMN_IDS];
  }
}

function remember(ids: readonly string[]): void {
  try {
    window.localStorage.setItem(REMEMBERED, JSON.stringify(ids));
  } catch {
    // The choice just will not outlive this page view.
  }
}

/** The groups in the order `EXPORT_COLUMNS` introduces them. */
function grouped(): [ExportColumn['group'], ExportColumn[]][] {
  const groups = new Map<ExportColumn['group'], ExportColumn[]>();
  for (const column of EXPORT_COLUMNS) {
    const list = groups.get(column.group) ?? [];
    list.push(column);
    groups.set(column.group, list);
  }
  return [...groups.entries()];
}

export function ExportColumnsPanel({
  appliedFilters,
  onExport,
  onClose,
}: {
  /**
   * The filters in force, in words. Shown because this panel has its own *Source* and
   * *Background check* boxes, and those pick **columns** — which companies are in the
   * file is the Filters panel's question, answered before this one opens.
   */
  appliedFilters: readonly string[];
  /**
   * Writes the file. It gathers the rows itself — the list on screen is one page of
   * them — so it is awaited and the button says it is working.
   */
  onExport: (columnIds: string[]) => Promise<void> | void;
  onClose: () => void;
}) {
  const [chosen, setChosen] = useState<string[]>(rememberedColumnIds);
  const [writing, setWriting] = useState(false);

  // Written as it changes rather than only on export, so a cancelled visit that
  // reorganised the columns is not lost.
  useEffect(() => remember(chosen), [chosen]);

  const toggle = (id: string) =>
    setChosen((previous) =>
      previous.includes(id) ? previous.filter((value) => value !== id) : [...previous, id],
    );

  return (
    <Sheet
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Export columns"
      description="Every company the filters match, not just the page on screen."
      footer={
        <div className="flex items-center justify-between gap-2">
          <Button size="sm" variant="subtle" onClick={() => setChosen([...DEFAULT_COLUMN_IDS])}>
            Reset
          </Button>
          <div className="flex gap-2">
            <Button size="sm" onClick={onClose} disabled={writing}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              disabled={chosen.length === 0}
              loading={writing}
              onClick={() => {
                // Gathering is several requests on a long list, so the button holds
                // rather than letting a second click start a second file.
                setWriting(true);
                void Promise.resolve(onExport(chosen)).finally(() => setWriting(false));
              }}
            >
              Export
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-5 p-4">
        <div className="rounded border border-line bg-sunken p-3">
          <p className="text-caption font-semibold uppercase tracking-wide text-ink-3">
            Companies in this file
          </p>
          {appliedFilters.length === 0 ? (
            <p className="mt-1 text-secondary text-ink-2">
              Every company on the list. Narrow it with <strong className="font-semibold">Filters</strong>{' '}
              before exporting — the boxes below choose columns, not companies.
            </p>
          ) : (
            <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-secondary text-ink-2">
              {appliedFilters.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </div>

        <p className="text-secondary text-ink-2" aria-live="polite">
          {chosen.length === 0
            ? 'Choose at least one column.'
            : `${chosen.length} ${chosen.length === 1 ? 'column' : 'columns'} selected.`}
        </p>

        {grouped().map(([group, columns]) => (
          <fieldset key={group} className="border-0 p-0">
            <legend className="mb-2 text-caption font-semibold uppercase tracking-wide text-ink-3">
              {group}
            </legend>
            <div className="flex flex-col gap-2">
              {columns.map((column) => (
                <label key={column.id} className="flex items-center gap-2 text-body text-ink">
                  <input
                    type="checkbox"
                    checked={chosen.includes(column.id)}
                    onChange={() => toggle(column.id)}
                    className="h-4 w-4 rounded border-line-strong accent-accent-solid"
                  />
                  {column.heading}
                </label>
              ))}
            </div>
          </fieldset>
        ))}

        <p className="text-caption text-ink-3">
          Identifiers are written as this account may read them: a role that sees a PAN
          masked on screen exports it masked.
        </p>
      </div>
    </Sheet>
  );
}
