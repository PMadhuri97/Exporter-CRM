/**
 * Import companies (frontend-plan §8.4): a drop zone, the server's reading of the file
 * before anything is sent for import, then the server's report as rows grouped by
 * outcome — failed, possible duplicates, created or matched — each in the server's
 * words. The client re-checks nothing.
 *
 * Bulk company import.
 *
 * Download the server's template (Excel, with instructions and dropdowns, or CSV),
 * upload either kind of file, read the per-row report. Every check and every match is
 * the server's — the same rules as adding a company by hand — and each row comes back
 * accepted (created or matched), rejected or possible_duplicate with the server's
 * codes and messages. A possible duplicate is never merged: it is left for a person to
 * settle. A rejected row reads "Failed" on this page.
 */

import { useState, type DragEvent } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { Button, Count, PageHeader, Tag, type TagTone } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { getCompanyImportTemplate, type ImportTemplateFormat } from '../api';
import { saveObjectUrl } from '../components/useOpenDocument';
import { useCompanyImportPreview, useImportCompanies } from '../hooks';
import { paths } from '../paths';
import type { ImportPreview, ImportReport } from '../types';

const STATUS_TONE: Record<string, TagTone> = {
  accepted: 'positive',
  rejected: 'negative',
  possible_duplicate: 'attention',
};

/** What each server status reads as here. */
const STATUS_LABEL: Record<string, string> = {
  accepted: 'Imported',
  rejected: 'Failed',
  possible_duplicate: 'Possible duplicate',
};

/** How the report groups its rows (frontend-plan §8.4): failures first, they need a person. */
const GROUPS: { status: string; title: string; glyph: 'error' | 'warning' | 'passed' }[] = [
  { status: 'rejected', title: 'Failed rows', glyph: 'error' },
  { status: 'possible_duplicate', title: 'Possible duplicates — a person should choose', glyph: 'warning' },
  { status: 'accepted', title: 'Created or matched', glyph: 'passed' },
];

const TEMPLATE_NAME: Record<ImportTemplateFormat, string> = {
  xlsx: 'company-import-template.xlsx',
  csv: 'company-import-template.csv',
};

async function downloadTemplate(format: ImportTemplateFormat) {
  try {
    const blob = await getCompanyImportTemplate(format);
    const url = URL.createObjectURL(blob);
    saveObjectUrl(url, TEMPLATE_NAME[format]);
    URL.revokeObjectURL(url);
  } catch (error) {
    toast.error(error instanceof Error ? error.message : "Couldn't download the template.");
  }
}

function headerProblems(preview: ImportPreview): string[] {
  const problems: string[] = [];
  if (preview.missing_columns.length > 0) {
    problems.push(`Missing columns: ${preview.missing_columns.join(', ')}.`);
  }
  if (preview.unknown_columns.length > 0) {
    problems.push(`Not in the template: ${preview.unknown_columns.join(', ')}.`);
  }
  if (preview.duplicate_columns.length > 0) {
    problems.push(`Given more than once: ${preview.duplicate_columns.join(', ')}.`);
  }
  if (preview.total_rows > preview.max_rows) {
    problems.push(
      `The file has ${preview.total_rows.toLocaleString()} rows; at most ${preview.max_rows.toLocaleString()} can be imported at once.`,
    );
  }
  return problems;
}

/**
 * The file as the server read it: its header and first rows in a grid, with every empty
 * cell kept in its own column so a shifted row shows as shifted. Header problems are
 * listed above it and stop the import, as the import itself would.
 */
function Preview({ preview }: { preview: ImportPreview }) {
  const problems = headerProblems(preview);
  const unknown = new Set([...preview.unknown_columns, ...preview.duplicate_columns]);
  const width = Math.max(preview.columns.length, ...preview.rows.map((row) => row.cells.length));
  return (
    <div role="group" aria-label="What will be imported" className="space-y-2">
      <p className="text-caption text-ink-3">
        {preview.total_rows === 0
          ? 'The file has a header but no rows.'
          : `${preview.total_rows.toLocaleString()} ${preview.total_rows === 1 ? 'row' : 'rows'} in the file${
              preview.total_rows > preview.rows.length ? `; the first ${preview.rows.length} are shown` : ''
            }. Every row is checked when you import.`}
      </p>
      {problems.length > 0 && (
        <div role="alert" className="rounded border border-negative bg-negative-tint px-3 py-2 text-secondary text-ink">
          <p className="font-semibold">File not accepted — fix the header and choose the file again.</p>
          <ul className="mt-1 list-disc pl-5">
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="overflow-x-auto rounded border border-line">
        <table className="w-full border-collapse text-left text-secondary">
          <thead className="bg-sunken">
            <tr>
              <th scope="col" className="sticky left-0 bg-sunken px-3 py-2 font-semibold text-ink-3">
                Row
              </th>
              {Array.from({ length: width }, (_, index) => {
                const column = preview.columns[index];
                return (
                  <th
                    key={index}
                    scope="col"
                    className={cn(
                      'whitespace-nowrap px-3 py-2 font-semibold',
                      column === undefined || unknown.has(column) ? 'text-negative' : 'text-ink',
                    )}
                  >
                    {column ?? '(no column)'}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {preview.rows.map((row) => (
              <tr key={row.line}>
                <th scope="row" className="sticky left-0 bg-surface px-3 py-1.5 font-normal tabular-nums text-ink-3">
                  {row.line}
                </th>
                {Array.from({ length: width }, (_, index) => (
                  <td key={index} className="max-w-[16rem] truncate whitespace-nowrap px-3 py-1.5 text-ink-2">
                    {row.cells[index] ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Report({ report }: { report: ImportReport }) {
  return (
    <section aria-label="Import report" className="space-y-4">
      <div className="flex flex-wrap items-end gap-x-10 gap-y-4 rounded border border-line bg-surface p-4">
        <div>
          <Count value={report.created} size="lg" />
          <p className="text-caption text-ink-3">created</p>
        </div>
        <div>
          <Count value={report.matched} size="lg" />
          <p className="text-caption text-ink-3">matched</p>
        </div>
        <div>
          <Count value={report.rejected} size="lg" className={report.rejected ? 'text-negative' : undefined} />
          <p className="text-caption text-ink-3">failed</p>
        </div>
        <div>
          <Count
            value={report.possible_duplicates}
            size="lg"
            className={report.possible_duplicates ? 'text-attention' : undefined}
          />
          <p className="text-caption text-ink-3">possible duplicates</p>
        </div>
        <p data-testid="import-summary" className="text-secondary text-ink-3">
          {report.total_rows} rows · {report.created} created · {report.matched} matched ·{' '}
          {report.rejected} failed · {report.possible_duplicates} possible duplicates
        </p>
      </div>

      {GROUPS.map((group) => {
        const rows = report.rows.filter((row) => row.status === group.status);
        if (rows.length === 0) return null;
        const Glyph = Icon[group.glyph];
        return (
          <div key={group.status} role="group" aria-label={group.title} className="rounded border border-line bg-surface">
            <h2 className="flex items-center gap-2 px-4 py-3 text-heading font-semibold text-ink">
              <Glyph size={20} className="text-ink-3" aria-hidden />
              {group.title}
              <span className="font-normal tabular-nums text-ink-3">({rows.length})</span>
            </h2>
            <ul className="divide-y divide-line border-t border-line">
              {rows.map((row) => (
                <li key={row.line} className="grid gap-x-4 gap-y-1 px-4 py-2.5 sm:grid-cols-[4.5rem_1fr_auto]">
                  <span className="text-secondary tabular-nums text-ink-3">Row {row.line}</span>
                  <div className="min-w-0">
                    <span className="flex flex-wrap items-center gap-2">
                      <Tag tone={STATUS_TONE[row.status] ?? 'idle'}>{STATUS_LABEL[row.status] ?? row.status}</Tag>
                      {row.action && <span className="text-secondary text-ink-2">{row.action}</span>}
                    </span>
                    {[...row.reasons, ...row.warnings].length > 0 && (
                      <ul className="mt-1 space-y-0.5 text-secondary text-ink-2">
                        {[...row.reasons, ...row.warnings].map((reason, i) => (
                          <li key={`${reason.code}-${i}`}>{reason.message}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <span className="flex flex-wrap gap-3 text-secondary">
                    {row.customer_id ? (
                      <Link to={paths.company(row.customer_id)} className="font-semibold text-accent underline-offset-2 hover:underline">
                        Open
                      </Link>
                    ) : (
                      row.candidates.map((id, i) => (
                        <Link key={id} to={paths.company(id)} className="font-semibold text-accent underline-offset-2 hover:underline">
                          Candidate {i + 1}
                        </Link>
                      ))
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

export function CompanyImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const mutation = useImportCompanies();
  const preview = useCompanyImportPreview(file);

  const choose = (next: File | null) => {
    setFile(next);
    mutation.reset();
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) choose(dropped);
  };

  const ready = file !== null && preview.data?.ready === true;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Import companies"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="subtle" onClick={() => void downloadTemplate('csv')}>
              CSV template
            </Button>
            <Button onClick={() => void downloadTemplate('xlsx')}>
              <Icon.download size={16} aria-hidden />
              Download template
            </Button>
          </div>
        }
      />

      <form
        className="space-y-4 rounded border border-line bg-surface p-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!file || !ready) return;
          mutation.mutate(file, {
            onSuccess: (report) =>
              toast.success(`Import finished: ${report.created} created, ${report.matched} matched`),
            onError: (error) => toast.error(`File not accepted: ${error.message}`),
          });
        }}
      >
        <label
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            'flex cursor-pointer flex-col items-start gap-1 rounded border border-dashed px-5 py-6 transition-colors duration-quick',
            dragging ? 'border-accent bg-accent-tint' : 'border-line-strong hover:border-ink-3',
          )}
        >
          <span className="flex items-center gap-2.5 text-body font-semibold text-ink">
            <Icon.upload size={20} className="text-ink-3" aria-hidden />
            {file ? file.name : 'Drop an Excel or CSV file here, or choose one'}
          </span>
          <span className="text-secondary text-ink-3">
            {file
              ? `${Math.max(1, Math.round(file.size / 1024))} KB — choose another to replace it`
              : 'Use the template: its Instructions sheet explains every column.'}
          </span>
          <input
            type="file"
            accept=".xlsx,.csv,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            aria-label="Import file"
            className="sr-only"
            onChange={(e) => choose(e.target.files?.[0] ?? null)}
          />
        </label>

        {file && preview.isPending && <p className="text-secondary text-ink-3">Reading the file…</p>}
        {file && preview.isError && (
          <p role="alert" className="rounded border border-negative bg-negative-tint px-3 py-2 text-secondary text-ink">
            <span className="font-semibold">File not accepted:</span> {preview.error.message}
          </p>
        )}
        {file && preview.data && <Preview preview={preview.data} />}

        <div className="flex justify-end">
          <Button type="submit" variant="primary" disabled={!ready} loading={mutation.isPending}>
            Import
          </Button>
        </div>
      </form>

      {mutation.isError && (
        <p role="alert" className="rounded border border-negative bg-negative-tint px-4 py-3 text-secondary text-ink">
          <span className="font-semibold">File not accepted:</span> {mutation.error.message}
        </p>
      )}
      {mutation.data && <Report report={mutation.data} />}
    </div>
  );
}
