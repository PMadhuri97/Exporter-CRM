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
 * only the role trusted to vouch that it came from RXIL may submit one. Guarded at
 * the route (`company.rxilIntake`, R-33 G5): every other role gets the generic
 * NotFound there, and neither this page nor an explanation of it.
 */

import { CheckCircle2 } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Button, Card, Chip, PageHeader, Panel, Textarea } from '@/components';

import { useSubmitRxilPackage } from '../hooks';
import { paths } from '../paths';

export function RxilIntakePage() {
  const [text, setText] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);
  const mutation = useSubmitRxilPackage();
  const result = mutation.data;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader
        back={{ to: paths.companies, label: 'Companies' }}
        title="RXIL intake"
        meta={<Chip tone="warning">Provisional format</Chip>}
        description="Take in a company RXIL has qualified. It arrives as a prospect, qualified by RXIL."
      />

      <Card className="p-5">
        <form
          className="space-y-3"
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
            className="min-h-[16rem] font-mono text-xs"
            placeholder='{"package_id": "…", …}'
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {(parseError ?? mutation.error) && (
            <p role="alert" className="text-sm text-status-failed">
              {parseError ?? mutation.error?.message}
            </p>
          )}
          <div className="flex justify-end">
            <Button
              type="submit"
              variant="primary"
              disabled={!text.trim()}
              loading={mutation.isPending}
            >
              Submit package
            </Button>
          </div>
        </form>
      </Card>

      {result && (
        <Panel
          aria-label="Intake result"
          title={
            <span className="inline-flex items-center gap-2">
              <CheckCircle2 size={17} className="text-status-passed" />
              {result.replayed ? 'Already taken in — nothing changed' : 'Taken in'}
            </span>
          }
          description={`Company ${result.company} · qualification ${result.qualification}`}
        >
          {result.warnings.length > 0 && (
            <ul className="mb-3 list-disc pl-5 text-sm text-status-review">
              {result.warnings.map((warning, i) => (
                <li key={`${warning.code}-${i}`}>{warning.message}</li>
              ))}
            </ul>
          )}
          <Link to={paths.company(result.customer_id)} className="text-sm font-medium text-brand-600 underline">
            Open company
          </Link>
        </Panel>
      )}
    </div>
  );
}
