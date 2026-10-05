// platform/shell — what a page tells the shell (its breadcrumbs), the keyboard
// helpers, and the viewer's recent companies (frontend-plan §7).
export { useCrumbs, useShellState, type Crumb } from './context';
export { ShellProvider } from './ShellProvider';
export { commandKeyLabel, hasModifier, isTypingTarget } from './keys';
export {
  clearRecentCompanies,
  readRecentCompanies,
  rememberCompany,
  type RecentCompany,
} from './recent';
