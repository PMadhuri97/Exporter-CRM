/**
 * Smart entry (frontend-plan §6.9): one field that understands what was typed — a
 * PAN, a GSTIN (with the PAN inside it), an IEC, a CIN, or a name — shows the kind it
 * detected, and asks the server whether that company is already in Aner.
 *
 * The answer is the server's (`POST /companies/match`, read-only and audited): MATCHED
 * names the holder, POSSIBLE_DUPLICATE lists candidates for a person to choose, CONFLICT
 * gives the server's reason, NEW says it is not here yet. The match needs a name and a
 * country besides the identifier (the server's rule: a MATCHED answer naming a company
 * that looks nothing like the name typed is how a mistake shows), so it runs once those
 * are known. A masked role may still have a company **named** by its exact identifier
 * (BQ-2); identifiers in the answer stay masked — the response carries none.
 *
 * Matching runs only where the page allows it (`live`) — pages that may create
 * (Add company, Choose buyer) are already gated on that capability — and only once
 * something is typed here. The detection alone is harmless.
 */

import { useMutation } from '@tanstack/react-query';
import { useEffect, useId, useRef, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { Tag } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { matchCompany } from '../../api';
import { paths } from '../../paths';
import type { CompanyMatch } from '../../types';

import { detectEntry } from './entry';

function Answer({ match, onPick }: { match: CompanyMatch; onPick?: (id: string) => void }) {
  if (match.kind === 'NEW') {
    return (
      <p className="flex items-center gap-2 text-secondary text-positive" data-match="NEW">
        <Icon.passed size={15} aria-hidden /> Not in Aner yet.
      </p>
    );
  }
  if (match.kind === 'MATCHED' && match.company_id) {
    const name = match.candidates?.[0]?.name ?? 'this company';
    return (
      <p className="flex flex-wrap items-center gap-2 text-secondary text-ink" data-match="MATCHED">
        <Icon.info size={15} className="text-progress" aria-hidden />
        Already in Aner: <span className="font-display text-lead">{name}</span>
        {onPick ? (
          <button type="button" className="font-medium underline underline-offset-[3px]" onClick={() => onPick(match.company_id!)}>
            Use it
          </button>
        ) : (
          <Link to={paths.company(match.company_id)} className="font-medium underline underline-offset-[3px]">
            Open
          </Link>
        )}
      </p>
    );
  }
  if (match.kind === 'POSSIBLE_DUPLICATE') {
    return (
      <div className="space-y-1.5" data-match="POSSIBLE_DUPLICATE">
        <p className="flex items-center gap-2 text-secondary text-attention">
          <Icon.warning size={15} aria-hidden /> Possibly already in Aner — a person should choose:
        </p>
        <ul className="space-y-1 pl-6">
          {(match.candidates ?? []).map((candidate) => (
            <li key={candidate.company_id} className="flex items-center gap-2 text-secondary">
              <span className="text-ink">{candidate.name}</span>
              <span className="text-ink-3">{candidate.country}</span>
              {onPick ? (
                <button type="button" className="font-medium underline underline-offset-[3px]" onClick={() => onPick(candidate.company_id)}>
                  Use it
                </button>
              ) : (
                <Link to={paths.company(candidate.company_id)} className="font-medium underline underline-offset-[3px]">
                  Open
                </Link>
              )}
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <p className="flex items-center gap-2 text-secondary text-negative" data-match={match.kind}>
      <Icon.error size={15} aria-hidden /> {match.reason ?? 'The server could not match this.'}
    </p>
  );
}

export function SmartEntry({
  value,
  onChange,
  name,
  country,
  label = 'PAN, GSTIN, IEC, CIN or company name',
  onMatch,
  onPick,
  hint,
  live = true,
}: {
  value: string;
  onChange: (value: string) => void;
  /** The company's name, when it is typed elsewhere (an identifier was entered here). */
  name?: string;
  country?: string;
  label?: string;
  onMatch?: (match: CompanyMatch | null) => void;
  /** Choose a matched company instead of opening it (Choose buyer). */
  onPick?: (companyId: string) => void;
  hint?: ReactNode;
  /** Ask the server as you type. Off where matching is not the page's job. */
  live?: boolean;
}) {
  const id = useId();
  const detected = detectEntry(value);
  const match = useMutation({ mutationFn: matchCompany });
  const lastAsked = useRef('');

  const matchName = detected.kind === 'name' ? detected.value : (name ?? '').trim();
  const identifier =
    detected.kind === 'PAN' ? { pan: detected.value } : detected.kind === 'GSTIN' ? { gstin: detected.value } : {};
  const ready = live && value.trim().length > 0 && Boolean(country) && matchName.length >= 2;
  const request = ready ? JSON.stringify({ name: matchName, country, ...identifier }) : '';

  useEffect(() => {
    if (!request || request === lastAsked.current) return;
    const timer = window.setTimeout(() => {
      lastAsked.current = request;
      match.mutate(JSON.parse(request), { onSuccess: (answer) => onMatch?.(answer) });
    }, 400);
    return () => window.clearTimeout(timer);
    // `match` is stable enough; only the request text decides.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);

  useEffect(() => {
    if (!request) onMatch?.(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);

  return (
    <div className="space-y-2" data-testid="smart-entry">
      <label htmlFor={id} className="block text-caption font-medium text-ink-2">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          className={cn('input h-11 pr-24 text-lead', detected.kind !== 'name' && 'font-mono uppercase')}
        />
        {value.trim() && (
          <Tag tone="ink" className="absolute right-2 top-1/2 -translate-y-1/2" data-testid="entry-kind">
            {detected.kind === 'name' ? 'Name' : detected.kind}
          </Tag>
        )}
      </div>
      {detected.kind === 'GSTIN' && detected.pan && (
        <p className="text-secondary text-ink-3">
          PAN <span className="data text-ink-2">{detected.pan}</span> will be taken from this GSTIN.
        </p>
      )}
      {hint && <p className="text-secondary text-ink-3">{hint}</p>}
      {match.isPending && <p className="text-secondary text-ink-3">Checking Aner…</p>}
      {match.isError && (
        <p role="alert" className="text-secondary text-negative">
          {match.error instanceof Error ? match.error.message : 'Could not check.'}
        </p>
      )}
      {ready && match.data && !match.isPending && <Answer match={match.data} onPick={onPick} />}
    </div>
  );
}
