// platform/access — who may use what (frontend plan §4, R-33 Phase 0).
// The only place a role is turned into a decision; everything else asks `useCan`.
export { can, capabilitiesFor, type Capability } from './capabilities';
export { Gate, type GateProps } from './Gate';
export { NoWorkspace, NoWorkspaceFrame } from './NoWorkspace';
export { useCan } from './useCan';
