/**
 * RXIL company intake — **owner: Developer 2** (L2-12, L2-14).
 *
 * Paste an RXIL package as RXIL sent it and submit it. The package format is
 * provisional until RXIL publishes its specification, so this page does not
 * model it: it checks only that the text is JSON and hands it to the server,
 * which parses it, matches the company, records RXIL's qualification as
 * supplied and refuses anything ambiguous (409) or unreadable (422) in its
 * own words.
 *
 * ADMIN only, as on the server: a package records a qualification decision as
 * RXIL's (source, method and confidence a person may never set by hand), so
 * only the role trusted to vouch that it came from RXIL may submit one. Every
 * other role sees why instead of a form the server would refuse.
 */

import { ArrowLeft } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { useCurrentUser } from '@/platform/auth';

import { useSubmitRxilPackage } from '../hooks';

export function RxilIntakePage() {
  const { role } = useCurrentUser();
  const [text, setText] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);
  const mutation = useSubmitRxilPackage();
  const result = mutation.data;

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
        <h1 className="text-lg font-semibold text-ink">RXIL intake</h1>
        <p className="text-sm text-ink-muted">
          Take in a company RXIL has qualified. The package format is provisional.
        </p>
      </div>

      {role !== 'ADMIN' ? (
        <p
          role="note"
          className="rounded-lg border border-border bg-surface p-5 text-sm text-ink-muted shadow-card"
        >
          Only an administrator can take in an RXIL package: it records RXIL's
          qualification decision, which no one may record by hand as RXIL's.
        </p>
      ) : (
        <form
          className="space-y-3 rounded-lg border border-border bg-surface p-5 shadow-card"
          onSubmit={(e) => {
            e.preventDefault();
            let pkg: unknown;
            try {
              pkg = JSON.parse(text);
            } catch {
              setParseError('The package is not valid JSON.');
              return;
            }
            setParseError(null);
            mutation.mutate(pkg);
          }}
        >
          <textarea
            aria-label="RXIL package"
            className="input min-h-[14rem] w-full font-mono text-xs"
            placeholder='{"package_id": "…", …}'
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {(parseError ?? mutation.error) && (
            <p role="alert" className="text-sm text-status-failed">
              {parseError ?? mutation.error?.message}
            </p>
          )}
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!text.trim() || mutation.isPending}
              className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              {mutation.isPending ? 'Submitting…' : 'Submit package'}
            </button>
          </div>
        </form>
      )}

      {result && (
        <section
          aria-label="Intake result"
          className="rounded-lg border border-border bg-surface p-5 shadow-card text-sm"
        >
          <h2 className="font-semibold text-ink">
            {result.replayed ? 'Already taken in — nothing changed' : 'Taken in'}
          </h2>
          <p className="mt-1 text-ink-muted">
            Company {result.company} · qualification {result.qualification}
          </p>
          {result.warnings.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-status-pending">
              {result.warnings.map((warning, i) => (
                <li key={`${warning.code}-${i}`}>{warning.message}</li>
              ))}
            </ul>
          )}
          <Link
            to={`/exporters/${result.customer_id}`}
            className="mt-3 inline-block font-medium text-brand-600 underline"
          >
            Open company
          </Link>
        </section>
      )}
    </div>
  );
}
