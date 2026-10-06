import { Link } from 'react-router-dom';

import { buttonClasses } from './styles';

/** The heading every unknown — or forbidden — address shows; tests read it from here. */
export const NOT_FOUND_TITLE = 'Page not found';

/**
 * Any address the app does not know, and any module a role may not use: the same
 * component, copy and title for both (§4.3), so a forbidden URL reads exactly like
 * one that does not exist. Never a blank page, never "you don't have access".
 */
export function NotFound({
  title = NOT_FOUND_TITLE,
  children = "The page you asked for doesn't exist.",
}: {
  title?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-lg rounded border border-line bg-surface px-6 py-10 text-center">
      <h1 className="text-title font-semibold text-ink">{title}</h1>
      <p className="mt-2 text-body text-ink-2">{children}</p>
      <Link to="/" className={buttonClasses({ variant: 'primary', className: 'mt-6' })}>
        Go to Home
      </Link>
    </div>
  );
}
