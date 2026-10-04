/**
 * Standing — one company, several gauges (frontend-plan §6.1): the PDF's "same
 * dashboard, three companies" as one glyph, drawn the same wherever a company
 * appears. The journey, the qualification, the conversation and the background
 * check sit side by side, never merged into one label; the marker follows.
 *
 * - `inline` — words and lamps, for a row.
 * - `card` — lamps only (each named for assistive tech), for a board card.
 * - `hero` — four segments with a detail line each, for the dossier's head; each
 *   segment opens its chapter.
 *
 * Role-aware: the background-check lamp is drawn only for a role that may read the
 * check (`compliance.read`) — **absent** for Developer (D8), not greyed. A gauge
 * the caller has no value for is simply left out (company list rows carry no
 * conversation or background check until ask A1). Every line of text here comes
 * from served values; nothing is worked out from rules held on the client.
 */

import type { ReactNode } from 'react';

import { formatDate } from '@/lib/format';
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
import { JOURNEY_LABEL } from '../../constants';
import { JourneyDots } from '../CompanyChips';
import { RiskChip } from '../RiskChip';

import { Lamp } from './Lamp';
import {
  BACKGROUND_CHECK_LAMP,
  CONVERSATION_LAMP,
  MARKER_LAMP,
  MEANING_TEXT,
  QUALIFICATION_LAMP,
  type LampLook,
} from './lamps';

export type StandingSegment = 'journey' | 'qualification' | 'conversation' | 'background-check';

export interface StandingProps {
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
  size?: 'inline' | 'card' | 'hero';
  /** Hero only: a detail line under each segment (dates, "cycle 2", the next step). */
  details?: Partial<Record<StandingSegment, ReactNode>>;
  /** Hero only: makes each segment a button that opens its chapter. */
  onOpen?: (segment: StandingSegment) => void;
  className?: string;
}

function OutsidePipeline({ size }: { size: 'inline' | 'card' | 'hero' }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-ink-3">
      <span aria-hidden className="h-[9px] w-[9px] rounded-full border border-dashed border-ink-3" />
      {size !== 'card' && <span>Outside pipeline</span>}
      {size === 'card' && <span className="sr-only">Outside pipeline</span>}
    </span>
  );
}

function InlineLamp({ look, extra }: { look: LampLook; extra?: ReactNode }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 whitespace-nowrap', MEANING_TEXT[look.meaning])}>
      <Lamp shape={look.shape} meaning={look.meaning} size={12} />
      <span>{look.label}</span>
      {extra}
    </span>
  );
}

export function Standing({
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
  details,
  onOpen,
  className,
}: StandingProps) {
  const mayReadCheck = useCan('compliance.read');
  const check = mayReadCheck && backgroundCheck ? BACKGROUND_CHECK_LAMP[backgroundCheck] : null;
  const qual = !outsidePipeline && qualification ? QUALIFICATION_LAMP[qualification] : null;
  const conv = !outsidePipeline && conversation ? CONVERSATION_LAMP[conversation] : null;
  const mark = marker ? MARKER_LAMP[marker] : undefined;

  if (size === 'card') {
    return (
      <span className={cn('inline-flex items-center gap-2', className)} data-standing="card">
        {outsidePipeline ? (
          <OutsidePipeline size="card" />
        ) : (
          journey && (
            <span className="inline-flex" role="img" aria-label={JOURNEY_LABEL[journey]}>
              <JourneyDots journey={journey} />
            </span>
          )
        )}
        {qual && <Lamp {...qual} label={`Qualification: ${qual.label}`} />}
        {conv && <Lamp {...conv} label={`Conversation: ${conv.label}`} />}
        {check && (
          <Lamp
            {...check}
            label={`Background check: ${check.label}${awaitingApproval ? ', awaiting approval' : ''}${rekycDue ? ', Re-KYC due' : ''}`}
            awaitingApproval={awaitingApproval}
            attentionDot={rekycDue}
          />
        )}
        {mark && <Lamp {...mark} label={mark.label} />}
      </span>
    );
  }

  if (size === 'inline') {
    return (
      <span
        className={cn('inline-flex flex-wrap items-center gap-x-3 gap-y-1 text-secondary', className)}
        data-standing="inline"
      >
        {outsidePipeline ? (
          <OutsidePipeline size="inline" />
        ) : (
          journey && (
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-ink" data-testid="journey-chip">
              <JourneyDots journey={journey} />
              {JOURNEY_LABEL[journey]}
            </span>
          )
        )}
        {qual && <InlineLamp look={qual} />}
        {conv && <InlineLamp look={conv} />}
        {check && (
          <span className="inline-flex items-center gap-1.5">
            <InlineLamp look={check} />
            {check.label === 'Clear' && risk && <RiskChip risk={risk} />}
          </span>
        )}
        {mark && <InlineLamp look={mark} />}
      </span>
    );
  }

  // Hero: four segments, each a door into its chapter.
  const segments: { key: StandingSegment; title: string; body: ReactNode }[] = [
    {
      key: 'journey',
      title: 'Journey',
      body: outsidePipeline ? (
        <OutsidePipeline size="hero" />
      ) : journey ? (
        <span className="inline-flex items-center gap-2 text-ink" data-testid="journey-chip">
          <JourneyDots journey={journey} />
          {JOURNEY_LABEL[journey]}
        </span>
      ) : null,
    },
  ];
  if (!outsidePipeline && qual) {
    segments.push({ key: 'qualification', title: 'Qualification', body: <InlineLamp look={qual} /> });
  }
  if (!outsidePipeline && conv) {
    segments.push({
      key: 'conversation',
      title: 'Conversation',
      body: (
        <InlineLamp
          look={conv}
          extra={
            conversation === 'NOT_NOW' && checkBackOn ? (
              <span className="text-ink-3">until {formatDate(checkBackOn)}</span>
            ) : undefined
          }
        />
      ),
    });
  }
  if (check) {
    segments.push({
      key: 'background-check',
      title: 'Background check',
      body: (
        <span className="inline-flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5">
            <Lamp {...check} size={12} awaitingApproval={awaitingApproval} attentionDot={rekycDue} />
            <span className={MEANING_TEXT[check.meaning]}>{check.label}</span>
          </span>
          {risk && backgroundCheck === 'CLEAR' && <RiskChip risk={risk} />}
          {awaitingApproval && (
            <span className="rounded-sm border border-dashed border-ink px-1 text-caption text-ink">
              Awaiting approval
            </span>
          )}
          {rekycDue && (
            <span className="rounded-sm bg-attention-tint px-1 text-caption text-attention">Re-KYC due</span>
          )}
        </span>
      ),
    });
  }

  return (
    <div
      className={cn(
        'grid divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface sm:divide-x sm:divide-y-0',
        segments.length === 4 ? 'sm:grid-cols-4' : segments.length === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2',
        className,
      )}
      data-standing="hero"
    >
      {segments.map((segment) => {
        const inner = (
          <>
            <span className="block text-caption text-ink-3">{segment.title}</span>
            <span className="mt-1.5 block text-body font-medium">{segment.body}</span>
            {details?.[segment.key] && (
              <span className="mt-1 block text-secondary text-ink-3">{details[segment.key]}</span>
            )}
          </>
        );
        return onOpen ? (
          <button
            key={segment.key}
            type="button"
            onClick={() => onOpen(segment.key)}
            className="px-4 py-3 text-left transition-colors duration-quick hover:bg-sunken"
          >
            {inner}
          </button>
        ) : (
          <div key={segment.key} className="px-4 py-3">
            {inner}
          </div>
        );
      })}
    </div>
  );
}
