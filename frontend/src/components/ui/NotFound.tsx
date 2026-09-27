import { Compass } from 'lucide-react';
import { Link } from 'react-router-dom';

import { buttonClasses } from './styles';

/** Any address the app does not know — never a blank page. */
export function NotFound({
  title = 'Page not found',
  children = 'The address may be mistyped, or the page may have moved.',
}: {
  title?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center py-20 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-sunken text-ink-muted">
        <Compass size={22} />
      </div>
      <h1 className="mt-4 text-lg font-semibold text-ink">{title}</h1>
      <p className="mt-1 text-sm text-ink-muted">{children}</p>
      <Link to="/" className={buttonClasses({ variant: 'primary', className: 'mt-6' })}>
        Go to Home
      </Link>
    </div>
  );
}
