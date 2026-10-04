/**
 * The domain half of the style guide (frontend-plan §12.4): the signature
 * components of §6 in their states, as each role sees them. Reached only through
 * `src/design/styleguide` (dev only), so production never contains it — the build
 * check looks for it in `dist/`.
 *
 * Fixtures only. Nothing here should be clicked through to the server: the track's
 * and runway's moves open their forms, and the smart entry has no country, so it
 * never asks.
 */

import { useState, type ReactNode } from 'react';

import { Segmented } from '@/components';
import type { User, UserRole } from '@/lib/api/types';
import { StaticAuthProvider } from '@/platform/auth';
import { Identifier } from '@/platform/mask';

import { RiskChip } from '../components/RiskChip';
import {
  BACKGROUND_CHECK_LAMP,
  CheckRunway,
  CONVERSATION_LAMP,
  GaugeTrack,
  Lamp,
  MARKER_LAMP,
  MEANING_TEXT,
  PartyCard,
  Preflight,
  QUALIFICATION_LAMP,
  Shelf,
  SmartEntry,
  Standing,
  type LampLook,
} from '../components/standing';
import type { BackgroundCheckProposal, CrmDocument } from '../types';

const ROLES: { value: UserRole; label: string }[] = [
  { value: 'OPERATIONS', label: 'RM' },
  { value: 'COMPLIANCE', label: 'Compliance' },
  { value: 'DEVELOPER', label: 'Developer' },
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line pt-4">
      <h2 className="text-lead font-semibold text-ink">{title}</h2>
      <div className="mt-4 space-y-5">{children}</div>
    </section>
  );
}

function GrammarRow({ title, looks }: { title: string; looks: LampLook[] }) {
  return (
    <div className="grid gap-2 sm:grid-cols-[9rem_1fr]">
      <span className="text-caption text-ink-3">{title}</span>
      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {looks.map((look) => (
          <span key={look.label} className={`inline-flex items-center gap-1.5 text-secondary ${MEANING_TEXT[look.meaning]}`}>
            <Lamp shape={look.shape} meaning={look.meaning} />
            {look.label}
          </span>
        ))}
      </div>
    </div>
  );
}

const PROPOSAL = {
  to_value: 'CLEAR',
  proposed_by: 'u1',
  proposed_by_name: 'R. Mehta',
  proposed_at: '2026-10-03T11:02:00Z',
} as BackgroundCheckProposal;

const FILES = [
  { id: 'f1', category: 'KYC', document_type: 'pan_card', file_name: 'pan-card.pdf', size_bytes: 182_000, scan_status: 'AVAILABLE', is_downloadable: true },
  { id: 'f2', category: 'KYC', document_type: 'gst_certificate', file_name: 'gst-certificate.pdf', size_bytes: 96_000, scan_status: 'PENDING_SCAN', is_downloadable: false },
  { id: 'f3', category: 'PRE_SHIPMENT', document_type: 'commercial_invoice', file_name: 'invoice-0041.pdf', size_bytes: 240_000, scan_status: 'QUARANTINED', is_downloadable: false },
].map((file) => ({
  company_id: 'c1',
  deal_id: null,
  source: 'EXPORTER_UPLOAD',
  content_type: 'application/pdf',
  uploaded_by: 'u1',
  uploaded_at: '2026-10-01T10:00:00Z',
  scanner_name: 'pass-through',
  ...file,
})) as CrmDocument[];

function Sections() {
  const [entry, setEntry] = useState('27AAAPL1234C1ZV');
  return (
    <>
      <Section title="Lamp grammar (§18.2)">
        <GrammarRow title="Qualification" looks={Object.values(QUALIFICATION_LAMP)} />
        <GrammarRow title="Conversation" looks={Object.values(CONVERSATION_LAMP)} />
        <GrammarRow title="Background check" looks={Object.values(BACKGROUND_CHECK_LAMP)} />
        <GrammarRow title="Marker" looks={Object.values(MARKER_LAMP).filter(Boolean) as LampLook[]} />
        <div className="flex flex-wrap items-center gap-3">
          <RiskChip risk="LOW" />
          <RiskChip risk="MEDIUM" />
          <RiskChip risk="HIGH" />
          <RiskChip risk="CRITICAL" />
        </div>
      </Section>

      <Section title="Standing — the same dashboard, three companies (§6.1)">
        <div className="space-y-2">
          <div><Standing journey="LEAD" qualification="NOT_YET_REVIEWED" conversation="REACHING_OUT" backgroundCheck="NOT_STARTED" /></div>
          <div><Standing journey="PROSPECT" qualification="QUALIFIED" conversation="INTERESTED" backgroundCheck="IN_REVIEW" awaitingApproval /></div>
          <div><Standing journey="CUSTOMER" qualification="QUALIFIED" conversation="READY_NOW" backgroundCheck="CLEAR" risk="LOW" /></div>
          <div><Standing outsidePipeline marker="PAUSED" /></div>
        </div>
        <div className="flex flex-wrap gap-6">
          <Standing size="card" journey="PROSPECT" qualification="QUALIFIED" conversation="NOT_NOW" backgroundCheck="FLAGGED" />
          <Standing size="card" journey="CUSTOMER" qualification="QUALIFIED" conversation="READY_NOW" backgroundCheck="CLEAR" rekycDue />
        </div>
        <Standing
          size="hero"
          journey="CUSTOMER"
          qualification="QUALIFIED"
          conversation="READY_NOW"
          backgroundCheck="CLEAR"
          risk="LOW"
          details={{ journey: 'since 3 Oct', qualification: '12 Sep · R. Mehta', conversation: 'open a deal', 'background-check': 'cycle 2 · until 3 Oct 2027' }}
          onOpen={() => undefined}
        />
      </Section>

      <Section title="Gauge track (§6.2)">
        <GaugeTrack
          customerId="c1"
          value="SPOKE_TO_THEM"
          moves={[
            { to: 'INTERESTED', reason_required: false, check_back_required: false },
            { to: 'NOT_NOW', reason_required: true, check_back_required: true },
          ]}
        />
        <GaugeTrack customerId="c1" value="NOT_NOW" checkBackOn="2026-11-12" moves={[]} />
      </Section>

      <Section title="Check runway (§6.3)">
        <CheckRunway
          value="IN_REVIEW"
          moves={[
            { to_value: 'CLEAR', reason_required: true, risk_required: true, approval_required: true },
            { to_value: 'MORE_INFO', reason_required: true, risk_required: false, approval_required: false },
            { to_value: 'FLAGGED', reason_required: true, risk_required: true, approval_required: true },
          ]}
          onChoose={() => undefined}
        />
        <CheckRunway value="IN_REVIEW" moves={[]} openProposal={PROPOSAL} />
      </Section>

      <Section title="Pre-flight (§6.4)">
        <Preflight blockedReason="the seller's background check is not clear; no AVAILABLE PRE_SHIPMENT document" />
        <Preflight
          blockedReason="x"
          conditions={[
            { key: 'customer', met: true, message: 'Seller is a customer' },
            { key: 'clear', met: true, message: "Seller's background check is clear and current (until 3 Oct 2027)" },
            { key: 'buyer', met: true, message: 'A buyer is recorded' },
            { key: 'aml', met: false, message: "Buyer's AML is not passed", fixAt: { to: '/companies', label: 'Record on buyer' } },
            { key: 'docs', met: false, message: 'Pre-shipment document missing' },
          ]}
        />
      </Section>

      <Section title="Shelf (§6.8)">
        <Shelf
          documents={FILES}
          isLoading={false}
          emptyMessage="No documents yet."
          required={[
            { category: 'PRE_SHIPMENT', label: 'Pre-shipment' },
            { category: 'INSURANCE', label: 'Insurance' },
          ]}
        />
      </Section>

      <Section title="Party cards (§6.7)">
        <div className="grid gap-4 lg:grid-cols-2">
          <PartyCard role="Seller" companyId="s1" name="Bharat Precision Metals" country="IN" journey="CUSTOMER" qualification="QUALIFIED" showCompliance={false} />
          <PartyCard role="Buyer" companyId="b1" name="Rotterdam Trading BV" country="NL" outsidePipeline showCompliance={false} />
        </div>
      </Section>

      <Section title="Smart entry and identifiers (§6.6, §6.9)">
        <div className="max-w-md">
          <SmartEntry value={entry} onChange={setEntry} />
        </div>
        <p className="flex flex-wrap items-center gap-4 text-secondary text-ink-2">
          PAN <Identifier kind="PAN" value="AAAPL1234C" /> · GSTIN <Identifier kind="GSTIN" value="27AAAPL1234C1ZV" />
        </p>
      </Section>
    </>
  );
}

export function OnboardingStyleGuide() {
  const [role, setRole] = useState<UserRole>('OPERATIONS');
  const user = { id: 'styleguide', email: 'style@example.com', full_name: 'Style Guide', role, is_active: true } as User;
  return (
    <StaticAuthProvider user={user}>
      <div className="space-y-8">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-caption text-ink-3">Seen as</span>
          <Segmented label="Seen as" value={role} onValueChange={setRole} options={ROLES} size="sm" />
        </div>
        <Sections />
      </div>
    </StaticAuthProvider>
  );
}
