export { JourneyChip, MarkerBadge, QualificationChip } from './CompanyChips';
export { MarkerControl } from './MarkerControl';
export { DuplicatePanMessage } from './DuplicatePanMessage';
export { duplicatePanHolder } from './duplicate-pan';
export { VerificationSection } from './VerificationSection';
// Developer 4B: checks on a deal's buyer, mounted on the deal page.
export { BuyerChecks } from './BuyerChecks';
// Developer 3A: the conversation gauge's move control, and the READY_NOW prompt
// (seam S2), which opens a deal through Developer 3B's `OpenDealForm`.
export { ConversationGaugeControl } from './ConversationGaugeControl';
export { OpenDealPrompt } from './OpenDealPrompt';
// Developer 3B: deals and documents. `DocumentUpload` and `DocumentList` are
// shared by the company page's Documents tab and the deal page, because a
// document row and an upload form read the same wherever they hang;
// `ScanStatusBadge` says which "scanner" reached a verdict.
export { DealStageChip } from './DealStageChip';
export { OpenDealForm } from './OpenDealForm';
export { DocumentList } from './DocumentList';
export { DocumentUpload } from './DocumentUpload';
export { ScanStatusBadge } from './ScanStatusBadge';
// Developer 1: the shared history log, and who acted, by name.
export { CompanyHistory, DealHistory } from './HistoryTimeline';
export { actorLabel } from './actor-label';

// ── Background check — owner: Developer 4A ──
export { BackgroundCheckGauge } from './BackgroundCheckGauge';
export { RiskChip } from './RiskChip';
export { BackgroundCheckMoveDialog } from './BackgroundCheckMoveDialog';
export { DecisionHistory } from './DecisionHistory';

// ── Compliance engine — owner: Developer 1 ──
// Mounted by other lanes: Developer 2 on the deal page (seller and buyer company).
export { CompanyComplianceSummary } from './CompanyComplianceSummary';
