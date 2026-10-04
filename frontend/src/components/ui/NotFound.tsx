import { Link } from 'react-router-dom';

import { LINK_CLASSES } from './styles';

/** The heading every unknown — or forbidden — address shows; tests read it from here. */
export const NOT_FOUND_TITLE = 'Nothing here.';

/**
 * Any address the app does not know, and any module a role may not use: the same
 * component, copy and title for both (§4.3), so a forbidden URL reads exactly like
 * one that does not exist. Never a blank page, never "you don't have access".
 */
export function NotFound({
  title = NOT_FOUND_TITLE,
  children = 'The address may be mistyped, or the page may have moved.',
}: {
  title?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="max-w-xl py-16 sm:py-24">
      <h1 className="font-display text-display-xl text-ink">{title}</h1>
      <p className="mt-3 text-lead text-ink-2">{children}</p>
      <Link to="/" className={`mt-6 inline-block text-body ${LINK_CLASSES}`}>
        Back to your desk
      </Link>
    </div>
  );
}
