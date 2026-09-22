import { useCurrentUser } from '@/platform/auth';

// Stands in for a real landing page until a Dashboard ticket exists in the
// build sequence (it currently doesn't — see "Build sequence" in
// docs/exporter-crm-frontend-tickets.md). This page's only job right now is
// proving the authenticated shell renders end to end.
export function DashboardPlaceholder() {
  const user = useCurrentUser();

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-lg font-semibold text-ink">
        Good morning, {user.full_name ?? user.email}
      </h1>
      <p className="mt-1 text-sm text-ink-muted">
        You're signed in as{' '}
        <span className="font-medium capitalize">
          {user.role.toLowerCase()}
        </span>
        . The Exporters list, Follow-ups and Pipeline screens are next in the
        build sequence.
      </p>
    </div>
  );
}
