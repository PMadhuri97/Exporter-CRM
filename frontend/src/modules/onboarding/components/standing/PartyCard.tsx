/**
 * A party card — the company mini-dossier for any place a second company appears
 * (frontend-plan §6.7): the deal room's seller and buyer, a trade relationship, a
 * match result. Name in the serif, its country, its Standing, and — for a role that
 * may read compliance — the compliance summary the server serves for it. The name
 * links to the dossier.
 *
 * A problem stays where it happened (architecture): each party carries its own
 * standing, so the seller's card never shows the buyer's checks or the reverse.
 */

import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { useCan } from '@/platform/access';

import { paths } from '../../paths';
import type { ExporterJourney, ExporterMarker, QualificationState } from '../../types';
import { CompanyComplianceSummary } from '../CompanyComplianceSummary';

import { Standing } from './Standing';

export function PartyCard({
  role,
  companyId,
  name,
  country,
  journey,
  qualification,
  marker,
  outsidePipeline = false,
  showCompliance = true,
  children,
}: {
  /** What the company is here: "Seller", "Buyer". */
  role: string;
  companyId: string;
  name: string;
  country?: string | null;
  journey?: ExporterJourney | null;
  qualification?: QualificationState | null;
  marker?: ExporterMarker | null;
  outsidePipeline?: boolean;
  /** Off where the page shows compliance elsewhere. */
  showCompliance?: boolean;
  /** Facts that belong to this party on this page (the invoicing branch, say). */
  children?: ReactNode;
}) {
  const mayReadCompliance = useCan('compliance.read');
  return (
    <div
      role="group"
      aria-label={`${role}: ${name}`}
      className="flex min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-4"
      data-testid={`party-${role.toLowerCase()}`}
    >
      <header>
        <p className="text-caption text-ink-3">{role}</p>
        <p className="mt-0.5 flex flex-wrap items-baseline gap-x-2">
          <Link
            to={paths.company(companyId)}
            className="font-display text-display-sm text-ink underline-offset-4 hover:underline"
          >
            {name}
          </Link>
          {country && <span className="text-secondary text-ink-3">{country}</span>}
        </p>
      </header>
      <Standing
        journey={journey}
        qualification={qualification}
        marker={marker}
        outsidePipeline={outsidePipeline}
        size="inline"
      />
      {showCompliance && mayReadCompliance && <CompanyComplianceSummary companyId={companyId} />}
      {children}
    </div>
  );
}
