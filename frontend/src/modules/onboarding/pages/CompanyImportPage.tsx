/**
 * Import companies (frontend-plan §8.4): a drop zone, a local preview of what will be
 * sent, then the server's report as lines grouped by outcome — refused, possible
 * duplicates, created or matched — each in the server's words. The client re-checks
 * nothing.
 *
 * Bulk company import.
 *
 * Download the server's template, upload a CSV, read the per-row report. Every
 * check and every match is the server's — the same rules as adding a company
 * by hand — and each row comes back accepted (created or matched), rejected
 * or possible_duplicate with the server's codes and messages. A possible
 * duplicate is never merged: it is left for a person to settle.
 */

import { useEffect, useState, type DragEvent } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { Button, Count, PageHeader, Tag, type TagTone } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';
import { humanize } from '@/lib/format';

import { getCompanyImportTemplate } from '../api';
import { useImportCompanies } from '../hooks';
import { paths } from '../paths';
import type { ImportReport } from '../types';

const STATUS_TONE: Record<string, TagTone> = {
  accepted: 'positive',
  rejected: 'negative',
  possible_duplicate: 'attention',
};

/** How the report groups its lines (frontend-plan §8.4): refusals first, they need a person. */
const GROUPS: { status: string; title: string; glyph: 'error' | 'warning' | 'passed' }[] = [
  { status: 'rejected', title: 'Refused', glyph: 'error' },
  { status: 'possible_duplicate', title: 'Possible duplicates — a person should choose', glyph: 'warning' },
  { status: 'accepted', title: 'Created or matched', glyph: 'passed' },
];

async function downloadTemplate() {
  try {
    const csv = await getCompanyImportTemplate();
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'company-import-template.csv';
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    toast.error(error instanceof Error ? error.message : "Couldn't download the template.");
  }
}

/**
 * What is about to be sent, so the person can see it is the right file: the header
 * and the first five lines, read locally. Nothing here checks a value — every check
 * is the server's, in the report that comes back (a server-side dry run would make this
 * preview the server's own).
 */
function usePreview(file: File | null) {
  const [preview, setPreview] = useState<{ file: File; rows: string[][] } | null>(null);
  useEffect(() => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const rows = String(reader.result ?? '')
        .split(/\r?\n/)
        .filter((line) => line.trim() !== '')
        .slice(0, 6)
        .map((line) => line.split(','));
      setPreview({ file, rows });
    };
    reader.readAsText(file.slice(0, 64 * 1024));
    return () => reader.abort();
  }, [file]);
  return file && preview?.file === file ? preview : null;
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
          <p className="text-caption text-ink-3">refused</p>
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
          {report.rejected} rejected · {report.possible_duplicates} possible duplicates
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
                  <span className="text-secondary tabular-nums text-ink-3">Line {row.line}</span>
                  <div className="min-w-0">
                    <span className="flex flex-wrap items-center gap-2">
                      <Tag tone={STATUS_TONE[row.status] ?? 'idle'}>{humanize(row.status)}</Tag>
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
  const preview = usePreview(file);

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) setFile(dropped);
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Import companies"
        actions={
          <Button onClick={() => void downloadTemplate()}>
            <Icon.download size={16} aria-hidden />
            Download template
          </Button>
        }
      />

      <form
        className="space-y-4 rounded border border-line bg-surface p-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!file) return;
          mutation.mutate(file, {
            onSuccess: (report) =>
              toast.success(`Import finished: ${report.created} created, ${report.matched} matched`),
            onError: (error) => toast.error(error.message),
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
            {file ? file.name : 'Drop a CSV here, or choose one'}
          </span>
          <span className="text-secondary text-ink-3">
            {file ? `${Math.max(1, Math.round(file.size / 1024))} KB — choose another to replace it` : 'Use the template’s columns.'}
          </span>
          <input
            type="file"
            accept=".csv,text/csv"
            aria-label="CSV file"
            className="sr-only"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </label>

        {preview && preview.rows.length > 0 && (
          <div role="group" aria-label="What will be sent">
            <p className="text-caption text-ink-3">
              What will be sent — the header and the first lines, as read here. The server checks every row.
            </p>
            <ul className="mt-1 divide-y divide-line rounded border border-line">
              {preview.rows.map((cells, index) => (
                <li key={index} className="flex gap-3 px-3 py-2 text-secondary">
                  <span className="w-16 shrink-0 text-ink-3">{index === 0 ? 'Header' : `Row ${index + 1}`}</span>
                  <span className={index === 0 ? 'min-w-0 truncate font-semibold text-ink' : 'min-w-0 truncate text-ink-2'}>
                    {cells.map((cell) => cell.trim()).filter(Boolean).join(' · ')}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex justify-end">
          <Button type="submit" variant="primary" disabled={!file} loading={mutation.isPending}>
            Import
          </Button>
        </div>
      </form>

      {mutation.data && <Report report={mutation.data} />}
    </div>
  );
}
