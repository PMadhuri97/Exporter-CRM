/**
 * The last companies a viewer opened, for search's "Recent" (frontend-plan §7.5):
 * id and name only, at most eight, kept per viewer in this browser and keyed by
 * the user, so a second person signing in on the same machine never sees the
 * first one's list. Cleared on sign-out. Every storage access is guarded — a
 * private window or blocked storage just means no recent list.
 */

export interface RecentCompany {
  id: string;
  name: string;
}

const LIMIT = 8;
const key = (userId: string) => `aner.recent.${userId}`;

export function readRecentCompanies(userId: string): RecentCompany[] {
  try {
    const raw = window.localStorage.getItem(key(userId));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (entry): entry is RecentCompany =>
          typeof entry === 'object' &&
          entry !== null &&
          typeof (entry as RecentCompany).id === 'string' &&
          typeof (entry as RecentCompany).name === 'string',
      )
      .slice(0, LIMIT);
  } catch {
    return [];
  }
}

export function rememberCompany(userId: string, company: RecentCompany): void {
  try {
    const next = [company, ...readRecentCompanies(userId).filter((entry) => entry.id !== company.id)];
    window.localStorage.setItem(key(userId), JSON.stringify(next.slice(0, LIMIT)));
  } catch {
    // Storage unavailable: nothing to remember.
  }
}

export function clearRecentCompanies(userId: string): void {
  try {
    window.localStorage.removeItem(key(userId));
  } catch {
    // Nothing stored.
  }
}
