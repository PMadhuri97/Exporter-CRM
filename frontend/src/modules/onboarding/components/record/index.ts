// The CRM's own parts (frontend-plan §6): how a company, its gauges, its paperwork
// and its history are drawn wherever they appear.
export { categoryLabel } from './categoryLabel';
export { CheckStatus } from './CheckStatus';
export { ConversationPath } from './ConversationPath';
export {
  BACKGROUND_CHECK_STATUS,
  CONVERSATION_STATUS,
  MARKER_STATUS,
  MEANING_TONE,
  QUALIFICATION_STATUS,
  type Meaning,
  type StatusLook,
} from './status';
export { PartyCard } from './PartyCard';
export { HandoverChecklist, type HandoverCondition } from './HandoverChecklist';
export { DocumentsByCategory, type RequiredCategory } from './DocumentsByCategory';
export { detectEntry, type EntryKind } from './entry';
export { IdentifierLookup } from './IdentifierLookup';
export { DealStagePath } from './DealStagePath';
export { CompanyBadges, type CompanyBadgesProps } from './CompanyBadges';
