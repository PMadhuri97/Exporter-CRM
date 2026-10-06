/**
 * The domain half of the style guide (frontend-plan §12.4): the CRM's own parts in
 * their states, as each role sees them — every badge for every gauge (§18.2), the
 * path in its three uses (§6.5), a record header (§6.3), record list items (§6.7),
 * related-list cards (§6.6), the background check's status card (§8.5.1) and the
 * handover checklist (§6.11). Reached only through `src/design/styleguide` (dev
 * only), so production never contains it — the build check looks for it in `dist/`.
 *
 * Fixtures only: nothing here makes a request. The "Seen as" switch re-renders the
 * same fixtures under another role, so what a role does not get is visibly absent.
 */

import { useState, type ReactNode } from 'react';

import {
  Badge,
  Button,
  Card,
  Path,
  RecordHeader,
  RecordListItem,
  Segmented,
  type PathStep,
  type RecordAction,
  type RecordField,
} from '@/components';
import { Icon } from '@/design/icons';
import type { User, UserRole } from '@/lib/api/types';
import { useCan } from '@/platform/access';
import { StaticAuthProvider } from '@/platform/auth';
import { Identifier } from '@/platform/mask';

import { DealStageChip } from '../components/DealStageChip';
import { ScanStatusBadge } from '../components/ScanStatusBadge';
import { CheckStatus, HandoverChecklist } from '../components/record';
import {
  BackgroundCheckBadge,
  ConversationBadge,
  JourneyBadge,
  MarkerStatusBadge,
  OutsidePipelineBadge,
  QualificationBadge,
  RiskBadge,
} from '../components/StatusBadge';
import { NoOutcomeChip, TradeOutcomeChip } from '../components/TradeOutcomeChip';
import type {
  BackgroundCheckProposal,
  BackgroundCheckState,
  DealStage,
  ExporterConversation,
  ExporterJourney,
  QualificationState,
} from '../types';

const ROLES: { value: UserRole; label: string }[] = [
  { value: 'OPERATIONS', label: 'RM' },
  { value: 'COMPLIANCE', label: 'Compliance' },
  { value: 'ADMIN', label: 'Admin' },
  { value: 'DEVELOPER', label: 'Developer' },
];

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card title={title} description={description}>
      <div className="space-y-4">{children}</div>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 sm:grid-cols-[10rem_1fr] sm:items-center">
      <span className="text-caption text-ink-3">{label}</span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

const QUALIFICATIONS: QualificationState[] = ['NOT_YET_REVIEWED', 'QUALIFIED', 'NOT_QUALIFIED'];
const CONVERSATIONS: ExporterConversation[] = [
  'NOT_CONTACTED',
  'REACHING_OUT',
  'SPOKE_TO_THEM',
  'INTERESTED',
  'NOT_NOW',
  'READY_NOW',
];
const CHECKS: BackgroundCheckState[] = ['NOT_STARTED', 'IN_REVIEW', 'MORE_INFO', 'CLEAR', 'FLAGGED', 'ON_HOLD'];
const JOURNEYS: ExporterJourney[] = ['LEAD', 'PROSPECT', 'CUSTOMER'];
const STAGES: DealStage[] = ['OPEN', 'GATHERING_PAPERWORK', 'HANDED_OVER', 'WITHDRAWN'];

function Badges() {
  const mayReadCheck = useCan('compliance.read');
  return (
    <Section title="Status badges" description="Every value of every gauge, in words (§18.2). One badge per gauge, never merged.">
      <Row label="Journey (lists)">
        {JOURNEYS.map((journey) => (
          <JourneyBadge key={journey} journey={journey} />
        ))}
        <OutsidePipelineBadge />
      </Row>
      <Row label="Qualification">
        {QUALIFICATIONS.map((state) => (
          <QualificationBadge key={state} state={state} />
        ))}
      </Row>
      <Row label="Conversation">
        {CONVERSATIONS.map((value) => (
          <ConversationBadge key={value} value={value} checkBackOn="2026-11-12" />
        ))}
      </Row>
      <Row label="Background check">
        {mayReadCheck ? (
          CHECKS.map((state) => (
            <BackgroundCheckBadge key={state} state={state} risk="LOW" clearUntil="2027-10-03" />
          ))
        ) : (
          <span className="text-secondary text-ink-3">Absent for this role.</span>
        )}
      </Row>
      {mayReadCheck && (
        <Row label="Background check, extra">
          <BackgroundCheckBadge state="IN_REVIEW" awaitingApproval />
          <BackgroundCheckBadge state="CLEAR" clearUntil="2026-10-12" risk="MEDIUM" rekycDue />
        </Row>
      )}
      <Row label="Risk">
        <RiskBadge risk="LOW" />
        <RiskBadge risk="MEDIUM" />
        <RiskBadge risk="HIGH" />
        <RiskBadge risk="CRITICAL" />
      </Row>
      <Row label="Marker">
        <MarkerStatusBadge marker="PAUSED" />
        <MarkerStatusBadge marker="ENDED" />
      </Row>
      <Row label="Deal stage">
        {STAGES.map((stage) => (
          <DealStageChip key={stage} stage={stage} />
        ))}
      </Row>
      <Row label="Document scan">
        <ScanStatusBadge status="PENDING_SCAN" />
        <ScanStatusBadge status="AVAILABLE" scannerName="pass-through" />
        <ScanStatusBadge status="QUARANTINED" scannerName="pass-through" />
        <ScanStatusBadge status="SCAN_FAILED" />
      </Row>
      <Row label="Trade outcome">
        <TradeOutcomeChip paymentStatus="PAID" proofStatus="PROVEN" />
        <TradeOutcomeChip paymentStatus="PARTIAL" proofStatus="PROVEN" />
        <TradeOutcomeChip paymentStatus="UNPAID" proofStatus="CLAIMED" />
        <TradeOutcomeChip paymentStatus="DISPUTED" proofStatus="PROVEN" />
        <TradeOutcomeChip paymentStatus="UNKNOWN" proofStatus="PROVEN" />
        <NoOutcomeChip />
      </Row>
    </Section>
  );
}

const JOURNEY_STEPS: PathStep<ExporterJourney>[] = [
  { key: 'LEAD', label: 'Lead' },
  { key: 'PROSPECT', label: 'Prospect' },
  { key: 'CUSTOMER', label: 'Customer' },
];

const CONVERSATION_STEPS: PathStep<ExporterConversation>[] = [
  { key: 'NOT_CONTACTED', label: 'Not contacted' },
  { key: 'REACHING_OUT', label: 'Reaching out' },
  { key: 'SPOKE_TO_THEM', label: 'Spoke to them' },
  { key: 'INTERESTED', label: 'Interested' },
  { key: 'READY_NOW', label: 'Ready now' },
];

const DEAL_STEPS: PathStep<Exclude<DealStage, 'WITHDRAWN'>>[] = [
  { key: 'OPEN', label: 'Open' },
  { key: 'GATHERING_PAPERWORK', label: 'Gathering paperwork' },
  { key: 'HANDED_OVER', label: 'Handed over' },
];

function Paths() {
  const mayAct = useCan('crm.write');
  const [chosen, setChosen] = useState<ExporterConversation | null>(null);
  return (
    <Section
      title="Path"
      description="The journey and the deal stage are never moved by hand. On the conversation, only the moves the server lists are clickable."
    >
      <Row label="Journey">
        <Path
          label="Journey"
          steps={JOURNEY_STEPS}
          current="PROSPECT"
          guidance="Becomes a customer once the background check is clear."
          className="w-full"
        />
      </Row>
      <Row label="Conversation">
        <div className="w-full space-y-2">
          <Path
            label="Conversation"
            steps={CONVERSATION_STEPS}
            current="SPOKE_TO_THEM"
            // The served moves: Interested on the path, Not now beside it.
            selectable={mayAct ? ['INTERESTED'] : []}
            selected={chosen}
            onSelect={setChosen}
          />
          {mayAct && (
            <div className="flex flex-wrap items-center gap-2">
              {chosen && (
                <Button size="sm" variant="primary" onClick={() => setChosen(null)}>
                  Mark as current
                </Button>
              )}
              <Button size="sm">Not now</Button>
              <span className="text-secondary text-ink-3">
                {chosen ? 'Interested is selected.' : 'Click Interested, the one served move.'}
              </span>
            </div>
          )}
        </div>
      </Row>
      <Row label="Deal stage">
        <Path
          label="Deal stage"
          steps={DEAL_STEPS}
          current="GATHERING_PAPERWORK"
          guidance="Hand over once every condition on the checklist is met."
          className="w-full"
        />
      </Row>
    </Section>
  );
}

function CompanyHeader() {
  const mayAct = useCan('crm.write');
  const mayDecide = useCan('compliance.decide');
  const mayReadCheck = useCan('compliance.read');
  // The fixture's served fields: the record allows these moves; the role decides
  // which of them reach the screen, as the server would.
  const actions: RecordAction[] = mayAct
    ? [
        { label: 'Log a call', onSelect: () => undefined },
        { label: 'Open deal', onSelect: () => undefined },
        ...(mayDecide ? [{ label: 'Approve', onSelect: () => undefined }] : []),
        { label: 'Pause', onSelect: () => undefined },
        { label: 'End', onSelect: () => undefined, destructive: true },
      ]
    : [];
  const fields: RecordField[] = [
    { label: 'Qualification', value: <QualificationBadge state="QUALIFIED" /> },
    { label: 'Conversation', value: <ConversationBadge value="READY_NOW" /> },
    ...(mayReadCheck
      ? [
          {
            label: 'Background check',
            value: <BackgroundCheckBadge state="CLEAR" risk="LOW" clearUntil="2027-10-03" />,
          },
        ]
      : []),
    { label: 'PAN', value: <Identifier kind="PAN" value="AAAPL1234F" /> },
    { label: 'RM', value: 'R. Mehta' },
  ];
  return (
    <RecordHeader
      breadcrumbs={[{ label: 'Companies', to: '/__design' }, { label: 'Bharat Precision Metals' }]}
      objectType="Company"
      title="Bharat Precision Metals"
      meta="Precision engineering · Mumbai, India · Customer since 3 Oct 2026"
      fields={fields}
      actions={actions}
      path={<Path label="Journey" steps={JOURNEY_STEPS} current="CUSTOMER" guidance="Customer since 3 Oct 2026." />}
    />
  );
}

function DealHeader() {
  const mayMove = useCan('crm.write');
  return (
    <RecordHeader
      objectType="Deal · DL-2026-0041"
      title="Rotterdam shipment"
      meta="Bharat Precision Metals → Rotterdam Trading BV (NL)"
      fields={[
        { label: 'Stage', value: <DealStageChip stage="GATHERING_PAPERWORK" /> },
        { label: 'Invoicing branch', value: 'Maharashtra' },
        { label: 'Opened', value: '2 Oct 2026 by R. Mehta' },
      ]}
      actions={
        mayMove
          ? [
              { label: 'Hand over', onSelect: () => undefined },
              { label: 'Withdraw', onSelect: () => undefined },
            ]
          : []
      }
      path={
        <Path
          label="Deal stage"
          steps={DEAL_STEPS}
          current="GATHERING_PAPERWORK"
          guidance="Hand over once every condition on the checklist is met."
        />
      }
    />
  );
}

function Headers() {
  return (
    <div className="space-y-4">
      <p className="text-secondary text-ink-2">
        Record headers (§6.3). Actions come only from served fields; Developer gets none, and no
        background check.
      </p>
      <CompanyHeader />
      <DealHeader />
    </div>
  );
}

function ListItems() {
  const mayReadCheck = useCan('compliance.read');
  return (
    <Card title="Companies" count="3" flush description="Record list items (§6.7): no table, no column headers.">
      <ol className="divide-y divide-line border-t border-line">
        <RecordListItem
          to="/__design"
          title="Bharat Precision Metals"
          facts={
            <>
              Precision engineering · Mumbai · PAN <Identifier kind="PAN" value="AAAPL1234F" /> · RM R. Mehta
            </>
          }
          badges={
            <>
              <JourneyBadge journey="CUSTOMER" />
              <QualificationBadge state="QUALIFIED" />
              {mayReadCheck && <BackgroundCheckBadge state="CLEAR" risk="LOW" />}
            </>
          }
        />
        <RecordListItem
          to="/__design"
          title="Coastal Seafood Exports"
          facts="Seafood · Kochi · RM S. Rao"
          badges={
            <>
              <JourneyBadge journey="PROSPECT" />
              <QualificationBadge state="QUALIFIED" />
              <MarkerStatusBadge marker="PAUSED" />
            </>
          }
        />
        <RecordListItem
          to="/__design"
          title="Deccan Spices"
          facts="Spices · Hyderabad"
          muted
          badges={
            <>
              <JourneyBadge journey="LEAD" />
              <QualificationBadge state="NOT_YET_REVIEWED" />
              <MarkerStatusBadge marker="ENDED" />
            </>
          }
        />
      </ol>
    </Card>
  );
}

function RelatedItem({ title, detail, badge }: { title: string; detail: string; badge?: ReactNode }) {
  return (
    <li className="flex items-start justify-between gap-3 py-2">
      <div className="min-w-0">
        <p className="truncate text-body font-semibold text-accent">{title}</p>
        <p className="truncate text-secondary text-ink-2">{detail}</p>
      </div>
      {badge}
    </li>
  );
}

function RelatedCards() {
  const mayAdd = useCan('crm.write');
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Card title="Open follow-ups" count={2} footer={{ label: 'View all', to: '/__design' }}>
        <ul className="-my-2 divide-y divide-line">
          <RelatedItem title="Call back about statements" detail="Due 3 Oct · R. Mehta" badge={<Badge tone="negative">Overdue 2d</Badge>} />
          <RelatedItem title="Send revised term sheet" detail="Due 8 Oct · R. Mehta" />
        </ul>
      </Card>
      <Card title="Deals" count={2} footer={{ label: 'View all', to: '/__design' }}>
        <ul className="-my-2 divide-y divide-line">
          <RelatedItem title="DL-2026-0041" detail="Rotterdam shipment" badge={<DealStageChip stage="GATHERING_PAPERWORK" />} />
          <RelatedItem title="DL-2026-0032" detail="Hamburg order" badge={<DealStageChip stage="HANDED_OVER" />} />
        </ul>
      </Card>
      <Card
        title="Contacts"
        count={3}
        actions={
          mayAdd ? (
            <Button size="sm" variant="subtle">
              <Icon.add size={16} aria-hidden />
              Add
            </Button>
          ) : undefined
        }
      >
        <ul className="-my-2 divide-y divide-line">
          <RelatedItem title="Anil Kulkarni" detail="Director · +91 98200 12345" badge={<Badge tone="neutral" variant="outline">Primary</Badge>} />
          <RelatedItem title="Meera Iyer" detail="Finance" />
          <RelatedItem title="Ravi Shah" detail="Logistics" />
        </ul>
      </Card>
      <Card title="Documents" count={5} footer={{ label: 'View all', to: '/__design' }}>
        <ul className="-my-2 divide-y divide-line">
          <RelatedItem title="pan-card.pdf" detail="KYC · 182 KB" badge={<ScanStatusBadge status="AVAILABLE" />} />
          <RelatedItem title="invoice-0041.pdf" detail="Pre-shipment · 240 KB" badge={<ScanStatusBadge status="QUARANTINED" />} />
        </ul>
      </Card>
    </div>
  );
}

const PROPOSAL = {
  to_value: 'CLEAR',
  proposed_by: 'u1',
  proposed_by_name: 'R. Mehta',
  proposed_at: '2026-10-03T11:02:00Z',
} as BackgroundCheckProposal;

function CheckStatusSection() {
  const mayDecide = useCan('compliance.decide');
  const mayRead = useCan('compliance.read');
  if (!mayRead) return null;
  return (
    <Section
      title="Background check status"
      description="The moves are buttons from the server's allowed moves; RM is served none of the decisions. Absent for Developer."
    >
      <CheckStatus
        value="IN_REVIEW"
        moves={
          mayDecide
            ? [
                { to_value: 'MORE_INFO', reason_required: true, risk_required: false, approval_required: false },
                { to_value: 'CLEAR', reason_required: true, risk_required: true, approval_required: true },
                { to_value: 'FLAGGED', reason_required: true, risk_required: true, approval_required: true },
              ]
            : []
        }
        onChoose={() => undefined}
      />
      <div className="border-t border-line pt-4">
        <CheckStatus value="IN_REVIEW" moves={[]} openProposal={PROPOSAL} />
      </div>
    </Section>
  );
}

function Checklist() {
  return (
    <Section
      title="Handover checklist"
      description="With structured conditions, one row per condition. Until then, the server's sentence in one message, never split. Developer is sent neither."
    >
      <HandoverChecklist
        blockedReason="x"
        conditions={[
          { key: 'customer', met: true, message: 'Seller is a customer' },
          { key: 'clear', met: true, message: "Seller's background check is clear (until 3 Oct 2027)" },
          { key: 'buyer', met: true, message: 'A buyer is recorded' },
          { key: 'aml', met: false, message: "Buyer's AML is not passed", fixAt: { to: '/__design', label: 'Go to buyer' } },
          { key: 'branch', met: true, message: 'Invoicing branch recorded: Maharashtra' },
          { key: 'docs', met: false, message: 'Pre-shipment document missing', fixAt: { to: '/__design', label: 'Upload' } },
        ]}
      />
      <div className="border-t border-line pt-4">
        <HandoverChecklist blockedReason="the seller's background check is not clear; no AVAILABLE PRE_SHIPMENT document" />
      </div>
    </Section>
  );
}

export function OnboardingStyleGuide() {
  const [role, setRole] = useState<UserRole>('OPERATIONS');
  const user = { id: 'styleguide', email: 'style@example.com', full_name: 'Style Guide', role, is_active: true } as User;
  return (
    <StaticAuthProvider user={user}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3 rounded border border-line bg-surface px-4 py-3">
          <span className="text-body font-semibold text-ink">CRM parts, seen as</span>
          <Segmented label="Seen as" value={role} onValueChange={setRole} options={ROLES} size="sm" />
        </div>
        <Badges />
        <Paths />
        <Headers />
        <ListItems />
        <RelatedCards />
        <CheckStatusSection />
        <Checklist />
      </div>
    </StaticAuthProvider>
  );
}
