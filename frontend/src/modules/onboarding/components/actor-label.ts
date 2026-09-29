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
  if (!id) return 'the platform';
  return formatReviewer(id);
}
