/**
 * Who acted, for a person to read.
 *
 * The server stores an actor as a user id and serves the name beside it
 * (`actor_name`, `decided_by_name`, `reviewed_by_name` — `api/actor_names.py`): the
 * account's full name, or its email for staff when it has none. Without a name, the
 * id is shortened as before; no id at all means the platform acted.
 *
 * Kept apart from the components that use it (react-refresh's rule).
 */

import { formatReviewer } from './verification-labels';

export function actorLabel(name: string | null | undefined, id: string | null | undefined): string {
  if (name) return name;
  // "None" is what a platform action stored before 14 October 2026 (the server wrote
  // `str(None)`); the history log keeps those rows, so read them as the platform too.
  if (!id || id === 'None') return 'the platform';
  return formatReviewer(id);
}
