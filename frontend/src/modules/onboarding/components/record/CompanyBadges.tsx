/**
 * A company's status badges (frontend-plan §6.4): the PDF's "same dashboard, three
 * companies", drawn the same wherever a company appears in a list, on a board card
 * or on a seller or buyer card. The journey, the qualification, the conversation and
 * the background check are separate worded badges side by side, never merged into
 * one label; the marker follows. On a record, the record header shows them as key
 * fields instead (§6.3).
 *
 * Role-aware: the background check is drawn only for a role that may read the check
 * (`compliance.read`) — **absent** for Developer, not greyed. A gauge the caller has
 * no value for is simply left out (company list rows carry no conversation or
 * background check yet). Every line of text here comes from served values; nothing
 * is worked out from rules held on the client.
 */

import { cn } from '@/lib/cn';
import { useCan } from '@/platform/access';

import type {
  BackgroundCheckRisk,
  BackgroundCheckState,
  ExporterConversation,
  ExporterJourney,
  ExporterMarker,
  QualificationState,
} from '../../types';
import {
  BackgroundCheckBadge,
  ConversationBadge,
  JourneyBadge,
  MarkerStatusBadge,
  OutsidePipelineBadge,
  QualificationBadge,
} from '../StatusBadge';

export interface CompanyBadgesProps {
  journey?: ExporterJourney | null;
  /** A buyer-only company is outside the pipeline: its journey and gauges do not apply. */
  outsidePipeline?: boolean;
  qualification?: QualificationState | null;
  conversation?: ExporterConversation | null;
  checkBackOn?: string | null;
  backgroundCheck?: BackgroundCheckState | null;
  risk?: BackgroundCheckRisk | null;
  awaitingApproval?: boolean;
  rekycDue?: boolean;
  marker?: ExporterMarker | null;
  /** `card` is the board's smaller set; the same badges either way. */
  size?: 'inline' | 'card';
  className?: string;
}

export function CompanyBadges({
  journey,
  outsidePipeline = false,
  qualification,
  conversation,
  checkBackOn,
  backgroundCheck,
  risk,
  awaitingApproval = false,
  rekycDue = false,
  marker,
  size = 'inline',
  className,
}: CompanyBadgesProps) {
  const mayReadCheck = useCan('compliance.read');
  const showCheck = mayReadCheck && Boolean(backgroundCheck);
  const showQualification = !outsidePipeline && Boolean(qualification);
  const showConversation = !outsidePipeline && Boolean(conversation);

  const journeyBadge = outsidePipeline ? (
    <OutsidePipelineBadge />
  ) : journey ? (
    <JourneyBadge journey={journey} />
  ) : null;
  const qualificationBadge = showQualification ? <QualificationBadge state={qualification!} /> : null;
  const conversationBadge = showConversation ? (
    <ConversationBadge value={conversation!} checkBackOn={checkBackOn} />
  ) : null;
  const checkBadge = showCheck ? (
    <BackgroundCheckBadge
      state={backgroundCheck!}
      risk={risk}
      awaitingApproval={awaitingApproval}
      rekycDue={rekycDue}
    />
  ) : null;
  const markerBadge = marker ? <MarkerStatusBadge marker={marker} /> : null;

  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1.5', className)} data-company-badges={size}>
      {journeyBadge}
      {qualificationBadge}
      {conversationBadge}
      {checkBadge}
      {markerBadge}
    </span>
  );
}
