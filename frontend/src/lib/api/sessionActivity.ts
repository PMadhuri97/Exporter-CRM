// When the person last used the CRM, and how long they may stop before the session
// ends — shared by every tab through localStorage, so working in one tab keeps the
// others signed in and walking away ends them all together.
//
// Only real use counts (`recordActivity`, called for mouse, keyboard, scroll and
// touch). A query refetching in the background is not someone at the desk, and an
// open dashboard that polled would otherwise never time out.
//
// The server holds the same line: a refresh token lives one inactivity timeout, and
// `client.ts` refreshes only while this says the person is still here. So a session
// ends even when this tab is closed or its timer never runs.

const LAST_ACTIVITY_KEY = 'aner.lastActivity';
const IDLE_TIMEOUT_KEY = 'aner.sessionIdleTimeoutMs';
const RENEWED_AT_KEY = 'aner.sessionRenewedAt';

/** Used until the server has said (its own default outside production). */
const DEFAULT_IDLE_TIMEOUT_MS = 30 * 60_000;

/** Writes are throttled: a mouse move fires many times a second. */
const WRITE_EVERY_MS = 5_000;

let lastWritten = 0;

export function recordActivity(now: number = Date.now()): void {
  if (now - lastWritten < WRITE_EVERY_MS) return;
  lastWritten = now;
  localStorage.setItem(LAST_ACTIVITY_KEY, String(now));
}

/** Recorded unthrottled: signing in, or "Stay signed in", must count at once. */
export function recordActivityNow(): void {
  lastWritten = 0;
  recordActivity();
}

/** When anyone last used the CRM in this browser, or `null` if never recorded. */
export function lastActivityAt(): number | null {
  const stored = Number(localStorage.getItem(LAST_ACTIVITY_KEY));
  return Number.isFinite(stored) && stored > 0 ? stored : null;
}

export function sessionIdleTimeoutMs(): number {
  const stored = Number(localStorage.getItem(IDLE_TIMEOUT_KEY));
  return Number.isFinite(stored) && stored > 0 ? stored : DEFAULT_IDLE_TIMEOUT_MS;
}

/** Kept from every token response, so a tab loading cold knows it before asking. */
export function setSessionIdleTimeout(seconds: number): void {
  localStorage.setItem(IDLE_TIMEOUT_KEY, String(seconds * 1000));
}

/**
 * How long until the session times out, in ms; zero or less once it has. A session
 * with no recorded activity — one from before this existed — counts as timed out.
 */
export function msUntilIdleTimeout(now: number = Date.now()): number {
  const last = lastActivityAt();
  if (last === null) return 0;
  return last + sessionIdleTimeoutMs() - now;
}

export function hasTimedOut(now: number = Date.now()): boolean {
  return msUntilIdleTimeout(now) <= 0;
}

/**
 * When the session was last renewed on the server — by any tab. The server's own
 * window runs one timeout from that moment, not from the last mouse move, so this is
 * what tells the keep-alive the server needs renewing before it closes.
 */
export function recordRenewal(now: number = Date.now()): void {
  localStorage.setItem(RENEWED_AT_KEY, String(now));
}

export function lastRenewalAt(): number | null {
  const stored = Number(localStorage.getItem(RENEWED_AT_KEY));
  return Number.isFinite(stored) && stored > 0 ? stored : null;
}

/**
 * How stale a renewal may get while someone is active. Kept to a minute so the
 * server's window — which the server pads by two minutes for exactly this — always
 * ends after the countdown on screen, and "Stay signed in" in its last second works.
 */
const RENEW_EVERY_MS = 60_000;

/** Whether the server's window should be renewed now, for someone still here. */
export function renewalDue(now: number = Date.now()): boolean {
  const renewed = lastRenewalAt();
  return renewed === null || now - renewed >= Math.min(RENEW_EVERY_MS, sessionIdleTimeoutMs() / 2);
}

export function clearActivity(): void {
  lastWritten = 0;
  localStorage.removeItem(LAST_ACTIVITY_KEY);
}

export { LAST_ACTIVITY_KEY };
