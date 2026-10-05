/**
 * The status wording (frontend-plan §18.2): every gauge value as the screen's words
 * and a **meaning**. One table, read by the status badges, the record header, the
 * conversation path and the background check's status card, so every screen and
 * test reads the same strings. The meaning picks the badge's tone (§5.2, §6.4); the
 * words always say the state, never a colour or a glyph alone.
 */

import type { BadgeTone } from '@/components';

import type {
  BackgroundCheckState,
  ExporterConversation,
  ExporterMarker,
  QualificationState,
} from '../../types';

export type Meaning = 'idle' | 'progress' | 'attention' | 'positive' | 'negative';

export interface StatusLook {
  meaning: Meaning;
  label: string;
}

export const QUALIFICATION_STATUS: Record<QualificationState, StatusLook> = {
  NOT_YET_REVIEWED: { meaning: 'idle', label: 'Not yet reviewed' },
  QUALIFIED: { meaning: 'positive', label: 'Qualified' },
  NOT_QUALIFIED: { meaning: 'negative', label: 'Not qualified' },
};

export const CONVERSATION_STATUS: Record<ExporterConversation, StatusLook> = {
  NOT_CONTACTED: { meaning: 'idle', label: 'Not contacted' },
  REACHING_OUT: { meaning: 'progress', label: 'Reaching out' },
  SPOKE_TO_THEM: { meaning: 'progress', label: 'Spoke to them' },
  INTERESTED: { meaning: 'progress', label: 'Interested' },
  NOT_NOW: { meaning: 'attention', label: 'Not now' },
  READY_NOW: { meaning: 'positive', label: 'Ready now' },
};

/** The order the conversation path draws its steps in (§6.5). Not now branches off. */
export const CONVERSATION_TRACK: readonly ExporterConversation[] = [
  'NOT_CONTACTED',
  'REACHING_OUT',
  'SPOKE_TO_THEM',
  'INTERESTED',
  'READY_NOW',
];

export const BACKGROUND_CHECK_STATUS: Record<BackgroundCheckState, StatusLook> = {
  NOT_STARTED: { meaning: 'idle', label: 'Not started' },
  IN_REVIEW: { meaning: 'progress', label: 'In review' },
  MORE_INFO: { meaning: 'attention', label: 'More information needed' },
  CLEAR: { meaning: 'positive', label: 'Clear' },
  FLAGGED: { meaning: 'negative', label: 'Flagged' },
  ON_HOLD: { meaning: 'negative', label: 'On hold' },
};

/** NONE has no badge: an unmarked relationship needs no mark. */
export const MARKER_STATUS: Partial<Record<ExporterMarker, StatusLook>> = {
  PAUSED: { meaning: 'attention', label: 'Paused' },
  ENDED: { meaning: 'idle', label: 'Ended' },
};

/** A meaning as a status badge's tone (§6.4). */
export const MEANING_TONE: Record<Meaning, BadgeTone> = {
  idle: 'neutral',
  progress: 'progress',
  attention: 'attention',
  positive: 'positive',
  negative: 'negative',
};
