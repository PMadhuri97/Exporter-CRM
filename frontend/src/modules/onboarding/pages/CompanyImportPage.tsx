/**
 * Bulk company import — **owner: Developer 2** (L2-13, L2-14).
 *
 * Download the server's template, upload a CSV, read the per-row report. Every
 * check and every match is the server's — the same rules as adding a company
 * by hand — and each row comes back accepted (created or matched), rejected
 * or possible_duplicate with the server's codes and messages. A possible
 * duplicate is never merged: it is left for a person to settle.
 */

import { Download, FileSpreadsheet } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import {
  Button,
  Card,
  Chip,
  PageHeader,
  Panel,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
  type ChipTone,
} from '@/components';
import { humanize } from '@/lib/format';

import { getCompanyImportTemplate } from '../api';
import { useImportCompanies } from '../hooks';
import { paths } from '../paths';
import type { ImportReport } from '../types';

const STATUS_TONE: Record<string, ChipTone> = {
  accepted: 'success',
  rejected: 'danger',
  possible_duplicate: 'warning',
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

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="rounded-lg border border-border px-4 py-3">
      <div className={`text-xl font-semibold tabular-nums ${tone ?? 'text-ink'}`}>{value}</div>
      <div className="text-xs text-ink-muted">{label}</div>
    </div>
  );
}

function ReportTable({ report }: { report: ImportReport }) {
  return (
    <Panel
      title="Report"
      aria-label="Import report"
      description={
        <span data-testid="import-summary">
          {report.total_rows} rows · {report.created} created · {report.matched} matched ·{' '}
          {report.rejected} rejected · {report.possible_duplicates} possible duplicates
        </span>
      }
      flush
    >
      <div className="grid grid-cols-2 gap-3 px-5 pb-4 sm:grid-cols-4">
        <Stat label="Created" value={report.created} tone="text-status-passed" />
        <Stat label="Matched" value={report.matched} />
        <Stat label="Rejected" value={report.rejected} tone="text-status-failed" />
        <Stat label="Possible duplicates" value={report.possible_duplicates} tone="text-status-review" />
      </div>
      {report.rows.length > 0 && (
        <Table>
          <THead>
            <tr>
              <Th className="w-16">Line</Th>
              <Th>Status</Th>
              <Th>Company</Th>
              <Th>Details</Th>
            </tr>
          </THead>
          <TBody>
            {report.rows.map((row) => (
              <Tr key={row.line}>
                <Td className="text-ink-muted">{row.line}</Td>
                <Td>
                  <Chip tone={STATUS_TONE[row.status] ?? 'neutral'}>{humanize(row.status)}</Chip>
                  {row.action && <span className="ml-1.5 text-xs text-ink-muted">{row.action}</span>}
                </Td>
                <Td>
                  {row.customer_id ? (
                    <Link to={paths.company(row.customer_id)} className="text-brand-600 underline">
                      Open
                    </Link>
                  ) : row.candidates.length > 0 ? (
                    <span className="flex flex-wrap gap-2">
                      {row.candidates.map((id, i) => (
                        <Link key={id} to={paths.company(id)} className="text-brand-600 underline">
                          Candidate {i + 1}
                        </Link>
                      ))}
                    </span>
                  ) : (
                    '—'
                  )}
                </Td>
                <Td className="text-ink-muted">
                  <ul className="space-y-0.5">
                    {[...row.reasons, ...row.warnings].map((reason, i) => (
                      <li key={`${reason.code}-${i}`}>{reason.message}</li>
                    ))}
                  </ul>
                </Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      )}
    </Panel>
  );
}

export function CompanyImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const mutation = useImportCompanies();

  return (
    <div className="space-y-5">
      <PageHeader
        back={{ to: paths.companies, label: 'Companies' }}
        title="Import companies"
        description="Each row is checked and matched like a company added by hand. New companies start as leads; possible duplicates are reported, never merged. Up to 1,000 rows per file."
      />

      <Card className="p-5">
        <form
          className="flex flex-col gap-4 sm:flex-row sm:items-center"
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
          <Button onClick={() => void downloadTemplate()}>
            <Download size={15} />
            Download template
          </Button>
          <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-lg border border-dashed border-border-strong px-4 py-2.5 text-sm text-ink-muted hover:border-brand-500">
            <FileSpreadsheet size={18} className="shrink-0 text-ink-faint" />
            <span className="truncate">{file ? file.name : 'Choose a CSV file…'}</span>
            <input
              type="file"
              accept=".csv,text/csv"
              aria-label="CSV file"
              className="sr-only"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <Button type="submit" variant="primary" disabled={!file} loading={mutation.isPending}>
            Import
          </Button>
        </form>
      </Card>

      {mutation.data && <ReportTable report={mutation.data} />}
    </div>
  );
}
