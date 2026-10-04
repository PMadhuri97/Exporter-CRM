// platform/shell — what a page tells the shell (crumbs, ⌘K actions, page keys), and the
// viewer's recent companies (frontend-plan §7, R-33 Phase 2).
export {
  useCommandActions,
  useCrumbs,
  usePageShortcuts,
  useShellState,
  type CommandAction,
  type Crumb,
  type PageShortcut,
} from './context';
export { ShellProvider } from './ShellProvider';
export { commandKeyLabel, hasModifier, isTypingTarget } from './keys';
export {
  clearRecentCompanies,
  readRecentCompanies,
  rememberCompany,
  type RecentCompany,
} from './recent';
