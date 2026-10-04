import { Link } from 'react-router-dom';

import { paths } from '../paths';

/**
 * "This PAN is already held by another company — open it."
 *
 * Says no more than the refusal did: the holder's id, as a link, not its name. BQ-2
 * (plan §19.0) lets a masked role be told the holder when refusing a duplicate
 * (`docs/remaining-work.md` D-07).
 */
export function DuplicatePanMessage({ holderId }: { holderId: string }) {
  return (
    <span>
      This PAN is already held by another company —{' '}
      <Link to={paths.company(holderId)} className="font-medium underline">
        open it
      </Link>
      . A PAN belongs to one company only.
    </span>
  );
}
