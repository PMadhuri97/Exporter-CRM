/**
 * The role matrix (`docs/frontend-plan.md` §4.1, §4.3, §4.4).
 *
 * Every role × every screen, through the real router, shell and rail: whether the rail
 * offers it, and whether its URL renders it or the generic `NotFound`. Each screen is a
 * `React.lazy` stub that records being rendered; a forbidden one must never be. A lazy
 * screen is only imported when rendered (`platform/access/Gate.test.tsx` proves that
 * with a fresh one), so a screen never rendered is never downloaded and sends no
 * request — §4.3's "data for a section the role lacks is never requested".
 *
 * The expected sets are written out by hand from §4.1 and the server's route table,
 * not derived from the manifest, so a wrong manifest fails here.
 *
 * The shell (§7): the rail, the command bar's "Go to" list, the `?` sheet and the `g`
 * shortcuts are all generated from the module table — each is checked here against
 * the same hand-written rows, so none can offer what another withholds.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { lazy } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { NOT_FOUND_TITLE } from '@/components';
import type { UserRole } from '@/lib/api/types';
import { useAuth, useCurrentUser } from '@/platform/auth';

import { AppRoutes } from './AppRouter';

const rendered = vi.hoisted(() => new Set<string>());

function Screen({ id }: { id: string }) {
  rendered.add(id);
  return <p data-testid="screen">{id}</p>;
}

/** A lazily loaded screen, as the real ones are. */
function stub(id: string) {
  return lazy(async () => ({ default: () => <Screen id={id} /> }));
}

vi.mock('@/modules/onboarding/lazyPages', () => ({
  AddExporterPage: stub('add-company'),
  CompanyImportPage: stub('import-companies'),
  DealDetailPage: stub('deal'),
  DealRequiredDocumentsPage: stub('required-documents'),
  ExporterDetailPage: stub('company'),
  ExportersListPage: stub('companies'),
  FollowUpsPage: stub('follow-ups'),
  IdentityCompletionPage: stub('identity-completion'),
  PipelinePage: stub('pipeline'),
  QualificationCriteriaPage: stub('criteria'),
  RxilIntakePage: stub('rxil-intake'),
  ReviewPage: stub('review'),
}));
// The module table wraps this one in `lazy` itself.
vi.mock('@/pages/HomePage', () => ({ HomePage: () => <Screen id="home" /> }));
vi.mock('@/modules/settings', () => ({ SettingsRoutes: stub('settings') }));
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useAuth: vi.fn(),
  useCurrentUser: vi.fn(),
}));

const ROLES: UserRole[] = ['OPERATIONS', 'COMPLIANCE', 'ADMIN', 'DEVELOPER', 'API_USER'];
const READERS: UserRole[] = ['OPERATIONS', 'COMPLIANCE', 'ADMIN', 'DEVELOPER'];
const STAFF: UserRole[] = ['OPERATIONS', 'COMPLIANCE', 'ADMIN'];
const ADMIN: UserRole[] = ['ADMIN'];

const ID = '11111111-1111-4111-8111-111111111111';

/** [url, the screen it renders, who may open it] — §4.1. */
const SCREENS: [string, string, UserRole[]][] = [
  ['/', 'home', READERS],
  ['/companies', 'companies', READERS],
  // The board is a view of Companies; `/pipeline` is its older address.
  ['/companies?view=board', 'pipeline', READERS],
  ['/companies/new', 'add-company', STAFF],
  ['/companies/import', 'import-companies', STAFF],
  ['/companies/rxil-intake', 'rxil-intake', ADMIN],
  ['/companies/identity-completion', 'identity-completion', READERS],
  [`/companies/${ID}`, 'company', READERS],
  ['/follow-ups', 'follow-ups', READERS],
  // The compliance queue: COMPLIANCE_OR_ADMIN, like the proposals route it reads.
  ['/review', 'review', ['COMPLIANCE', 'ADMIN']],
  ['/pipeline', 'pipeline', READERS],
  [`/deals/${ID}`, 'deal', READERS],
  // The old addresses redirect into the CRM, so they are the CRM's too.
  [`/exporters/${ID}`, 'company', READERS],
  ['/settings', 'settings', ROLES],
  ['/settings/qualification-criteria', 'criteria', ADMIN],
  ['/settings/deal-required-documents', 'required-documents', ADMIN],
];

/** [rail row, who sees it, its `g` key, where it goes] — §7.2. */
const RAIL: [string, UserRole[], string | null, string][] = [
  ['Desk', READERS, 'h', 'home'],
  ['Companies', READERS, 'c', 'companies'],
  ['Agenda', READERS, 'f', 'follow-ups'],
  ['Review', ['COMPLIANCE', 'ADMIN'], 'r', 'review'],
  ['Settings', READERS, 's', 'settings'],
  ['Qualification criteria', ADMIN, null, 'criteria'],
  ['Required documents', ADMIN, null, 'required-documents'],
];
/** Rows that existed before the redesign and must never come back. */
const RETIRED_ROWS = ['Home', 'Follow-ups', 'Pipeline'];

function signInAs(role: string) {
  const user = {
    id: 'user-1',
    email: 'someone@aner.example',
    full_name: 'Some One',
    role,
    is_active: true,
  } as unknown as ReturnType<typeof useCurrentUser>;
  vi.mocked(useCurrentUser).mockReturnValue(user);
  vi.mocked(useAuth).mockReturnValue({
    status: 'authenticated',
    user,
    login: vi.fn(),
    logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>);
}

function renderAt(url: string) {
  // The command bar's company search is a query, so the shell needs a client; it
  // stays idle until someone types, which is part of what is asserted below.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** What the page body renders, without the shell around it. */
function mainContent(): string {
  return document.querySelector('main')?.innerHTML ?? '';
}

beforeEach(() => {
  vi.clearAllMocks();
  rendered.clear();
});

describe('the route matrix: every role × every screen', () => {
  const cases = ROLES.flatMap((role) =>
    SCREENS.map(([url, id, allowed]) => [role, url, id, allowed.includes(role)] as const),
  );

  it.each(cases)('%s at %s', async (role, url, id, allowed) => {
    signInAs(role);
    if (allowed) {
      renderAt(url);
      expect(await screen.findByTestId('screen')).toHaveTextContent(id);
      expect([...rendered]).toEqual([id]);
      return;
    }

    // What an address that does not exist renders for this role, to compare against.
    const missing = renderAt('/no-such-address');
    await screen.findByRole('heading');
    const notFound = mainContent();
    missing.unmount();

    renderAt(url);
    await screen.findByRole('heading');
    if (url === '/') {
      // The root is where a user with no workspace lands.
      expect(screen.getByText(/doesn.t have access to a workspace/)).toBeInTheDocument();
    } else {
      // Indistinguishable from a page that does not exist (§4.3): same component,
      // same words. Never "Administrators only".
      expect(mainContent()).toBe(notFound);
      expect(screen.getByRole('heading', { name: NOT_FOUND_TITLE })).toBeInTheDocument();
      expect(screen.queryByText(/administrator/i)).not.toBeInTheDocument();
    }
    // Never rendered, so never imported, so nothing it would request was sent.
    expect([...rendered]).toEqual([]);
  });
});

describe('the rail', () => {
  it.each(READERS)('offers %s exactly the rows its role may follow', async (role) => {
    signInAs(role);
    renderAt('/settings');
    await screen.findByTestId('screen');
    const nav = screen.getByRole('navigation', { name: 'Main' });
    for (const [label, who] of RAIL) {
      const row = within(nav).queryByRole('link', { name: label });
      if (who.includes(role)) expect(row).toBeInTheDocument();
      else expect(row).not.toBeInTheDocument();
    }
    for (const label of RETIRED_ROWS) {
      expect(within(nav).queryByRole('link', { name: label })).not.toBeInTheDocument();
    }
  });
});

describe('the command bar, the shortcut sheet and the g keys (§7.4, §7.5)', { timeout: 30_000 }, () => {
  const expected = (role: UserRole) => RAIL.filter(([, who]) => who.includes(role));

  it.each(READERS)('offers %s the same modules in ⌘K as in the rail', async (role) => {
    signInAs(role);
    renderAt('/settings');
    await screen.findByTestId('screen');
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const goTo = await screen.findByTestId('command-go-to', {}, { timeout: 15_000 });
    const offered = within(goTo)
      .getAllByRole('option')
      .map((option) => option.textContent?.replace(/g[a-z]$/, '').trim());
    expect(offered).toEqual(expected(role).map(([label]) => label));
  });

  it.each(READERS)('lists only %s’s own keys in the ? sheet', async (role) => {
    signInAs(role);
    renderAt('/settings');
    await screen.findByTestId('screen');
    fireEvent.keyDown(window, { key: '?' });
    const sheet = await screen.findByTestId('shortcut-sheet');
    for (const [label, who, key] of RAIL) {
      if (!key) continue;
      const listed = within(sheet).queryByText(label);
      if (who.includes(role)) expect(listed).toBeInTheDocument();
      else expect(listed).not.toBeInTheDocument();
    }
  });

  it.each(READERS)('lets %s use g to reach its modules, and no other', async (role) => {
    signInAs(role);
    renderAt('/settings');
    await screen.findByTestId('screen');
    for (const [, who, key, id] of RAIL) {
      if (!key || !who.includes(role)) continue;
      rendered.clear();
      act(() => {
        fireEvent.keyDown(window, { key: 'g' });
        fireEvent.keyDown(window, { key });
      });
      expect(await screen.findByTestId('screen')).toHaveTextContent(id);
    }
    // A letter no module of this role owns goes nowhere.
    rendered.clear();
    act(() => {
      fireEvent.keyDown(window, { key: 'g' });
      fireEvent.keyDown(window, { key: 'z' });
    });
    expect([...rendered]).toEqual([]);
  });
});

describe('a user with no workspace', () => {
  // API_USER, and a role the manifest has never heard of: both fail closed.
  it.each(['API_USER', 'AUDITOR'])('%s gets no rail and no CRM words', async (role) => {
    signInAs(role);
    renderAt('/');
    expect(await screen.findByText(/doesn.t have access to a workspace/)).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
    for (const word of ['Desk', 'Companies', 'Agenda', 'Follow-ups', 'Pipeline', 'Qualification criteria']) {
      expect(screen.queryByText(word)).not.toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'My profile' })).toHaveAttribute('href', '/settings');
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    expect([...rendered]).toEqual([]);
  });

  it('still reaches My profile, which every role may use', async () => {
    signInAs('API_USER');
    renderAt('/settings');
    expect(await screen.findByTestId('screen')).toHaveTextContent('settings');
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument();
  });

  it('gets NotFound, not the CRM, from a CRM address', async () => {
    signInAs('AUDITOR');
    renderAt('/companies');
    expect(await screen.findByRole('heading', { name: NOT_FOUND_TITLE })).toBeInTheDocument();
    expect([...rendered]).toEqual([]);
  });
});
