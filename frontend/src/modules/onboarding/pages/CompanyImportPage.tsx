/**
 * Bulk company import — **owner: Developer 2** (L2-13, L2-14).
 *
 * Download the server's template, upload a CSV, read the per-row report. Every
 * check and every match is the server's — the same rules as adding a company
 * by hand — and each row comes back accepted (created or matched), rejected
 * or possible_duplicate with the server's codes and messages. A possible
 * duplicate is never merged: it is left for a person to settle.
 */

import { ArrowLeft } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { humanize } from '@/lib/format';

import { getCompanyImportTemplate } from '../api';
import { useImportCompanies } from '../hooks';
import type { ImportReport } from '../types';

const STATUS_CLASSES: Record<string, string> = {
  accepted: 'text-status-passed',
  rejected: 'text-status-failed',
  possible_duplicate: 'text-status-pending',
};

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

function ReportTable({ report }: { report: ImportReport }) {
  return (
    <section aria-label="Import report" className="rounded-lg border border-border bg-surface p-5 shadow-card">
      <h2 className="font-semibold text-ink">Report</h2>
      <p className="mt-1 text-sm text-ink-muted" data-testid="import-summary">
        {report.total_rows} rows · {report.created} created · {report.matched} matched ·{' '}
        {report.rejected} rejected · {report.possible_duplicates} possible duplicates
      </p>
      {report.rows.length > 0 && (
        <table className="mt-3 w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-faint">
              <th className="py-2 font-medium">Line</th>
              <th className="py-2 font-medium">Status</th>
              <th className="py-2 font-medium">Company</th>
              <th className="py-2 font-medium">Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {report.rows.map((row) => (
              <tr key={row.line}>
                <td className="py-2 text-ink-muted">{row.line}</td>
                <td className={`py-2 font-medium ${STATUS_CLASSES[row.status] ?? 'text-ink'}`}>
                  {humanize(row.status)}
                  {row.action && <span className="font-normal text-ink-muted"> ({row.action})</span>}
                </td>
                <td className="py-2">
                  {row.customer_id ? (
                    <Link to={`/exporters/${row.customer_id}`} className="text-brand-600 underline">
                      Open
                    </Link>
                  ) : row.candidates.length > 0 ? (
                    <span className="flex flex-wrap gap-2">
                      {row.candidates.map((id, i) => (
                        <Link key={id} to={`/exporters/${id}`} className="text-brand-600 underline">
                          Candidate {i + 1}
                        </Link>
                      ))}
                    </span>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="py-2 text-ink-muted">
                  <ul>
                    {[...row.reasons, ...row.warnings].map((reason, i) => (
                      <li key={`${reason.code}-${i}`}>{reason.message}</li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function CompanyImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const mutation = useImportCompanies();

  return (
    <div className="space-y-5">
      <div>
        <Link
          to="/exporters"
          className="mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
        >
          <ArrowLeft size={15} />
          Exporters
        </Link>
        <h1 className="text-lg font-semibold text-ink">Import companies</h1>
        <p className="text-sm text-ink-muted">
          Each row is checked and matched like a company added by hand. New companies start as
          leads; possible duplicates are reported, never merged.
        </p>
      </div>

      <form
        className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface p-5 shadow-card"
        onSubmit={(e) => {
          e.preventDefault();
          if (!file) return;
          mutation.mutate(file, { onError: (error) => toast.error(error.message) });
        }}
      >
        <button
          type="button"
          onClick={() => void downloadTemplate()}
          className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-subtle"
        >
          Download template
        </button>
        <input
          type="file"
          accept=".csv,text/csv"
          aria-label="CSV file"
          className="text-sm"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button
          type="submit"
          disabled={!file || mutation.isPending}
          className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {mutation.isPending ? 'Importing…' : 'Import'}
        </button>
      </form>

      {mutation.data && <ReportTable report={mutation.data} />}
    </div>
  );
}
