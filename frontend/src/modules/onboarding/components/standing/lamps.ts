/**
 * The lamp grammar (frontend-plan §6.1, §18.2): every gauge value as a **shape** and
 * a **meaning**, so a state never depends on colour alone. One table, read by the
 * Standing, the gauge track, the check runway and the ledger.
 *
 * The meanings are the tokens' (§5.2); the shapes are drawn by `Lamp.tsx`. Labels
 * are the screen's words for each value — the same ones the chips used.
 */

import type {
  BackgroundCheckState,
  ExporterConversation,
  ExporterMarker,
  QualificationState,
} from '../../types';

export type Meaning = 'idle' | 'progress' | 'attention' | 'positive' | 'negative';

export type LampShape =
  | 'empty' // ◌ nothing yet
  | 'quarter' // ◔
  | 'half' // ◑
  | 'three' // ◕
  | 'full' // ●
  | 'check' // ✓
  | 'cross' // ✕
  | 'pause' // ‖
  | 'question' // ?
  | 'triangle' // ▲
  | 'square' // ■
  | 'dash'; // —

export interface LampLook {
  shape: LampShape;
  meaning: Meaning;
  label: string;
}

export const QUALIFICATION_LAMP: Record<QualificationState, LampLook> = {
  NOT_YET_REVIEWED: { shape: 'empty', meaning: 'idle', label: 'Not yet reviewed' },
  QUALIFIED: { shape: 'check', meaning: 'positive', label: 'Qualified' },
  NOT_QUALIFIED: { shape: 'cross', meaning: 'negative', label: 'Not qualified' },
};

/** The quarter-fill is the warmth of the conversation (§6.1). */
export const CONVERSATION_LAMP: Record<ExporterConversation, LampLook> = {
  NOT_CONTACTED: { shape: 'empty', meaning: 'idle', label: 'Not contacted' },
  REACHING_OUT: { shape: 'quarter', meaning: 'progress', label: 'Reaching out' },
  SPOKE_TO_THEM: { shape: 'half', meaning: 'progress', label: 'Spoke to them' },
  INTERESTED: { shape: 'three', meaning: 'progress', label: 'Interested' },
  NOT_NOW: { shape: 'pause', meaning: 'attention', label: 'Not now' },
  READY_NOW: { shape: 'full', meaning: 'positive', label: 'Ready now' },
};

/** The order the conversation track draws its nodes in (§6.2). Not now branches off. */
export const CONVERSATION_TRACK: readonly ExporterConversation[] = [
  'NOT_CONTACTED',
  'REACHING_OUT',
  'SPOKE_TO_THEM',
  'INTERESTED',
  'READY_NOW',
];

export const BACKGROUND_CHECK_LAMP: Record<BackgroundCheckState, LampLook> = {
  NOT_STARTED: { shape: 'empty', meaning: 'idle', label: 'Not started' },
  IN_REVIEW: { shape: 'quarter', meaning: 'progress', label: 'In review' },
  MORE_INFO: { shape: 'question', meaning: 'attention', label: 'More information needed' },
  CLEAR: { shape: 'full', meaning: 'positive', label: 'Clear' },
  FLAGGED: { shape: 'triangle', meaning: 'negative', label: 'Flagged' },
  ON_HOLD: { shape: 'square', meaning: 'negative', label: 'On hold' },
};

/** NONE has no lamp: an unmarked relationship needs no mark. */
export const MARKER_LAMP: Partial<Record<ExporterMarker, LampLook>> = {
  PAUSED: { shape: 'pause', meaning: 'attention', label: 'Paused' },
  ENDED: { shape: 'dash', meaning: 'idle', label: 'Ended' },
};

/** Text colour for a meaning (AA on surfaces). */
export const MEANING_TEXT: Record<Meaning, string> = {
  idle: 'text-ink-2',
  progress: 'text-progress',
  attention: 'text-attention',
  positive: 'text-positive',
  negative: 'text-negative',
};

/** The solid colour a lamp is drawn in. */
export const MEANING_SOLID: Record<Meaning, string> = {
  idle: 'text-idle-solid',
  progress: 'text-progress-solid',
  attention: 'text-attention-solid',
  positive: 'text-positive-solid',
  negative: 'text-negative-solid',
};
