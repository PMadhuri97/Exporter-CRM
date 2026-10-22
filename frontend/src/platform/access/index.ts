// platform/access — who may use what.
// The only place a role is turned into a decision; everything else asks `useCan`.
export { can, capabilitiesFor, type Capability } from './capabilities';
export { Gate, type GateProps } from './Gate';
export { NoWorkspace, NoWorkspaceFrame } from './NoWorkspace';
export { useCan } from './useCan';
export {
  useCanRevealIdentifiers,
  useCanRevealIdentifiersOnce,
  useHasPermission,
  type AssignmentPermission,
} from './usePermissions';
