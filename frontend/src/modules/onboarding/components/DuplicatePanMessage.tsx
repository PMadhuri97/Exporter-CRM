import { Link } from 'react-router-dom';

import { paths } from '../paths';

/**
 * "This PAN is already held by another company — open it."
 *
 * Says no more than the refusal did: the holder's id, as a link, not its name. Whether
 * roles that may not reveal identifiers should learn even that is an open decision
 * (`docs/open-items.md` §1.2, identifier disclosure).
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
