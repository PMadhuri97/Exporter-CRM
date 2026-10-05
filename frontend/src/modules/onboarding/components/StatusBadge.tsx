/**
 * The company's gauges as worded status badges (frontend-plan §6.4, §18.2): one
 * badge per gauge, side by side, never merged into one label. The words are the
 * label maps' (`record/status.ts`, `constants.ts`), so every screen and test reads
 * the same strings; the tone repeats the meaning and never replaces the words.
 *
 * Role-aware where it matters: `BackgroundCheckBadge` and its two extra badges are
 * drawn only for a role that may read the check (`compliance.read`) — absent for
 * Developer, not greyed.
 */

import { Badge, type BadgeTone } from '@/components';
import { formatDate } from '@/lib/format';
import { useCan } from '@/platform/access';

import { JOURNEY_LABEL } from '../constants';
import type {
  BackgroundCheckRisk,
  BackgroundCheckState,
  ExporterConversation,
  ExporterJourney,
  ExporterMarker,
  QualificationState,
} from '../types';

import {
  BACKGROUND_CHECK_STATUS,
  CONVERSATION_STATUS,
  MARKER_STATUS,
  MEANING_TONE,
  QUALIFICATION_STATUS,
} from './record/status';

/** The journey in a list or on a card. On a record it is the path instead (§6.5). */
export function JourneyBadge({ journey }: { journey: ExporterJourney }) {
  return (
    <Badge tone="neutral" dot={false} className="text-ink-2" data-testid="journey-chip">
      {JOURNEY_LABEL[journey]}
    </Badge>
  );
}

/** A buyer-only company: its journey and gauges do not apply. */
export function OutsidePipelineBadge() {
  return (
    <Badge tone="neutral" variant="outline">
      Outside pipeline
    </Badge>
  );
}

export function QualificationBadge({ state }: { state: QualificationState }) {
  const look = QUALIFICATION_STATUS[state];
  return <Badge tone={MEANING_TONE[look.meaning]}>{look.label}</Badge>;
}

export function ConversationBadge({
  value,
  checkBackOn,
}: {
  value: ExporterConversation;
  /** Shown with *Not now*: "Not now · check back 12 Nov 2026". */
  checkBackOn?: string | null;
}) {
  const look = CONVERSATION_STATUS[value];
  return (
    <Badge tone={MEANING_TONE[look.meaning]}>
      {look.label}
      {value === 'NOT_NOW' && checkBackOn ? ` · check back ${formatDate(checkBackOn)}` : ''}
    </Badge>
  );
}

/** Nothing for `NONE`: an unmarked relationship needs no badge. */
export function MarkerStatusBadge({ marker, reason }: { marker: ExporterMarker; reason?: string | null }) {
  const look = MARKER_STATUS[marker];
  if (!look) return null;
  return (
    <Badge tone={MEANING_TONE[look.meaning]} title={reason ?? undefined}>
      {look.label}
    </Badge>
  );
}

const RISK_LABEL: Record<BackgroundCheckRisk, string> = {
  LOW: 'Low risk',
  MEDIUM: 'Medium risk',
  HIGH: 'High risk',
  CRITICAL: 'Critical risk',
};

/**
 * The risk rating (§5.2). Never colour alone: the words say the level, High adds a
 * negative outline, and Critical is the only solid badge on the screen, with a
 * warning icon (PDF §3.3).
 */
export function RiskBadge({ risk, ...rest }: { risk: BackgroundCheckRisk; 'data-testid'?: string }) {
  if (risk === 'CRITICAL') {
    return (
      <Badge variant="solid" data-risk={risk} {...rest}>
        {RISK_LABEL[risk]}
      </Badge>
    );
  }
  const tone: BadgeTone = risk === 'LOW' ? 'positive' : risk === 'MEDIUM' ? 'attention' : 'negative';
  return (
    <Badge
      tone={tone}
      className={risk === 'HIGH' ? 'ring-1 ring-inset ring-negative/60' : undefined}
      data-risk={risk}
      {...rest}
    >
      {RISK_LABEL[risk]}
    </Badge>
  );
}

/**
 * The background check, with what goes with it: the risk beside a Clear and the
 * date it lasts until, "Awaiting approval" (outline: nothing has happened yet) and
 * "Re-KYC due" (its own attention badge, not a different value).
 */
export function BackgroundCheckBadge({
  state,
  risk,
  clearUntil,
  awaitingApproval = false,
  rekycDue = false,
}: {
  state: BackgroundCheckState;
  risk?: BackgroundCheckRisk | null;
  clearUntil?: string | null;
  awaitingApproval?: boolean;
  rekycDue?: boolean;
}) {
  const mayRead = useCan('compliance.read');
  if (!mayRead) return null;
  const look = BACKGROUND_CHECK_STATUS[state];
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Badge tone={MEANING_TONE[look.meaning]}>
        {look.label}
        {state === 'CLEAR' && clearUntil ? ` · until ${formatDate(clearUntil)}` : ''}
      </Badge>
      {state === 'CLEAR' && risk && <RiskBadge risk={risk} />}
      {awaitingApproval && (
        <Badge tone="neutral" variant="outline">
          Awaiting approval
        </Badge>
      )}
      {rekycDue && <Badge tone="attention">Re-KYC due</Badge>}
    </span>
  );
}
