/**
 * RXIL company intake.
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
 * only the role trusted to vouch that it came from RXIL may submit one. Guarded at
 * the route (`company.rxilIntake`): every other role gets the generic
 * NotFound there, and neither this page nor an explanation of it.
 */

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { Button, Card, PageHeader, Tag, Textarea } from '@/components';
import { Icon } from '@/design/icons';

import { useSubmitRxilPackage } from '../hooks';
import { paths } from '../paths';

/** A few facts read from the pasted package, so the person can see it is the right one. */
function readPackage(text: string): { ok: true; facts: [string, string][] } | { ok: false } | null {
  if (!text.trim()) return null;
  try {
    const pkg = JSON.parse(text) as Record<string, unknown>;
    const company = (pkg.company ?? {}) as Record<string, unknown>;
    const facts: [string, string][] = [];
    if (typeof pkg.package_id === 'string') facts.push(['Package', pkg.package_id]);
    if (typeof company.name === 'string') facts.push(['Company', company.name]);
    if (typeof company.country === 'string') facts.push(['Country', company.country]);
    return { ok: true, facts };
  } catch {
    return { ok: false };
  }
}

export function RxilIntakePage() {
  const [text, setText] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);
  const mutation = useSubmitRxilPackage();
  const result = mutation.data;
  const preview = useMemo(() => readPackage(text), [text]);

  return (
    <div className="max-w-3xl space-y-4">
      <PageHeader
        title="RXIL intake"
        meta={<Tag tone="attention">Prototype: provisional format</Tag>}
      />

      <form
        className="space-y-3 rounded border border-line bg-surface p-4"
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
        <Textarea
          aria-label="RXIL package"
          className="min-h-[14rem] text-secondary"
          placeholder='Paste the package: {"package_id": "…", …}'
          spellCheck={false}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        {preview && (
          <p className="rounded bg-sunken px-3 py-2 text-secondary text-ink-2" data-testid="package-preview">
            {preview.ok
              ? preview.facts.length > 0
                ? preview.facts.map(([label, value]) => `${label} ${value}`).join(' · ')
                : 'Valid JSON — no package id or company name found in it.'
              : 'Not valid JSON yet.'}
          </p>
        )}
        {(parseError ?? mutation.error) && (
          <p role="alert" className="text-secondary text-negative">
            {parseError ?? mutation.error?.message}
          </p>
        )}
        <div className="flex justify-end">
          <Button type="submit" variant="primary" disabled={!text.trim()} loading={mutation.isPending}>
            Take in
          </Button>
        </div>
      </form>

      {result && (
        <Card aria-label="Intake result" role="group">
          <div className="space-y-2">
            <p className="flex items-center gap-2 text-heading font-semibold text-ink">
              <Icon.passed size={20} className="text-positive" aria-hidden />
              {result.replayed ? 'Already taken in — nothing changed' : 'Taken in'}
            </p>
            <p className="text-secondary text-ink-2">
              Company {result.company} · qualification {result.qualification}
            </p>
            {result.warnings.length > 0 && (
              <ul className="list-disc pl-5 text-secondary text-attention">
                {result.warnings.map((warning, i) => (
                  <li key={`${warning.code}-${i}`}>{warning.message}</li>
                ))}
              </ul>
            )}
            <Link to={paths.company(result.customer_id)} className="inline-block text-body font-semibold text-accent underline-offset-2 hover:underline">
              Open company
            </Link>
          </div>
        </Card>
      )}
    </div>
  );
}
