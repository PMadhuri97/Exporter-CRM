/**
 * The style guide (frontend-plan §12.4) — the page the TL reviews: every token and
 * primitive in its states, then the CRM's own parts seen as each role. Mounted at
 * `/__design` only when `import.meta.env.DEV` (see `routes/AppRouter.tsx`), so the
 * production build never contains it.
 *
 * Static fixtures only: it makes no request and needs no sign-in. Light, dark, or
 * both stacked. Floating layers (menus, popovers, the side panel) portal to the
 * page body, so they take the page's theme rather than their pane's.
 */

import * as Menu from '@radix-ui/react-dropdown-menu';
import { useState, type ReactNode } from 'react';

import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Count,
  DatePopover,
  Editable,
  EmptyLine,
  ErrorState,
  Field,
  FormError,
  InlineError,
  Input,
  Kbd,
  MENU_CONTENT,
  MENU_ITEM,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Segmented,
  Select,
  SidePanel,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  type BadgeTone,
} from '@/components';
import { OnboardingStyleGuide } from '@/modules/onboarding';

import { BrandMark } from '../BrandMark';
import { Icon, type IconName } from '../icons';

const NEUTRALS = ['paper', 'surface', 'raised', 'sunken', 'line', 'line-strong', 'ink', 'ink-2', 'ink-3', 'ink-4'];
const ACCENT = ['accent', 'accent-solid', 'accent-solid-hover', 'accent-tint'];
const MEANINGS = ['positive', 'negative', 'attention', 'progress', 'idle'] as const;
const TONES: BadgeTone[] = ['neutral', 'progress', 'attention', 'positive', 'negative'];

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card title={title} description={description}>
      <div className="space-y-4">{children}</div>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 sm:grid-cols-[10rem_1fr] sm:items-center">
      <span className="text-caption text-ink-3">{label}</span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

function Swatch({ name }: { name: string }) {
  return (
    <div className="w-24">
      <div className="h-10 rounded border border-line" style={{ background: `rgb(var(--${name}))` }} />
      <p className="mt-1 text-caption text-ink-2">{name}</p>
    </div>
  );
}

function Palette() {
  return (
    <Section title="Colour" description="Neutral greys; one brand blue for what can be acted on; five meanings for state.">
      <Row label="Neutrals">
        {NEUTRALS.map((name) => (
          <Swatch key={name} name={name} />
        ))}
      </Row>
      <Row label="Brand (placeholder)">
        {ACCENT.map((name) => (
          <Swatch key={name} name={name} />
        ))}
      </Row>
      {MEANINGS.map((meaning) => (
        <Row key={meaning} label={meaning === 'idle' ? 'neutral' : meaning}>
          <Swatch name={meaning} />
          <Swatch name={`${meaning}-tint`} />
          <Swatch name={`${meaning}-solid`} />
        </Row>
      ))}
    </Section>
  );
}

function Type() {
  return (
    <Section title="Type" description="One family, the system UI font (Segoe UI on Windows). Weight sets the hierarchy.">
      <Row label="Count 24/32">
        <span className="text-count font-semibold text-ink">48</span>
      </Row>
      <Row label="Title 20/28">
        <span className="text-title font-semibold text-ink">Bharat Precision Metals</span>
      </Row>
      <Row label="Card title 16/22">
        <span className="text-heading font-semibold text-ink">Open follow-ups</span>
      </Row>
      <Row label="Body 14/20">
        <span className="text-body text-ink">The default size for everything that is read.</span>
      </Row>
      <Row label="Secondary 13/18">
        <span className="text-secondary text-ink-2">Precision engineering · Mumbai, India · RM R. Mehta</span>
      </Row>
      <Row label="Label 12/16">
        <span className="text-caption text-ink-3">Background check</span>
      </Row>
      <Row label="Identifiers">
        <span className="text-body text-ink">PAN AAAPL1234C · GSTIN 27AAAPL1234C1ZV · DL-2026-0041 · ₹ 1,40,00,000</span>
      </Row>
    </Section>
  );
}

function Buttons() {
  return (
    <Section title="Buttons" description="One primary button per view. A verb and an object on every button.">
      {(['md', 'sm'] as const).map((size) => (
        <Row key={size} label={size === 'md' ? '32 px' : '28 px (in a card)'}>
          <Button variant="primary" size={size}>
            Hand over
          </Button>
          <Button variant="secondary" size={size}>
            Open deal
          </Button>
          <Button variant="subtle" size={size}>
            Cancel
          </Button>
          <Button variant="destructive" size={size}>
            Withdraw deal
          </Button>
          <Button variant="primary" size={size} loading>
            Saving
          </Button>
          <Button variant="secondary" size={size} disabled>
            Not right now
          </Button>
        </Row>
      ))}
      <Row label="Menu">
        <Menu.Root>
          <Menu.Trigger asChild>
            <Button variant="primary">
              <Icon.add size={16} aria-hidden />
              New
              <Icon.caretDown size={14} aria-hidden />
            </Button>
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Content align="start" sideOffset={4} className={MENU_CONTENT}>
              <Menu.Item className={MENU_ITEM}>
                <Icon.company size={16} className="text-ink-3" aria-hidden />
                New company
              </Menu.Item>
              <Menu.Item className={MENU_ITEM}>
                <Icon.upload size={16} className="text-ink-3" aria-hidden />
                Import companies
              </Menu.Item>
            </Menu.Content>
          </Menu.Portal>
        </Menu.Root>
      </Row>
    </Section>
  );
}

function Badges() {
  return (
    <Section title="Badges" description="Status in words. Colour and the dot repeat the label; they never replace it.">
      <Row label="Tones">
        {TONES.map((tone) => (
          <Badge key={tone} tone={tone}>
            {tone === 'neutral' ? 'Not started' : tone === 'progress' ? 'In review' : tone === 'attention' ? 'More information needed' : tone === 'positive' ? 'Clear' : 'Flagged'}
          </Badge>
        ))}
      </Row>
      <Row label="Outline">
        <Badge variant="outline">Awaiting approval</Badge>
        <Badge variant="outline">Outside pipeline</Badge>
      </Row>
      <Row label="Solid (Critical only)">
        <Badge variant="solid">Critical risk</Badge>
      </Row>
    </Section>
  );
}

function Controls() {
  const [lens, setLens] = useState<'all' | 'leads' | 'prospects' | 'customers'>('all');
  const [result, setResult] = useState<'PASS' | 'FAIL' | 'UNKNOWN'>('PASS');
  const [date, setDate] = useState<string | null>('2026-11-12');
  const [industry, setIndustry] = useState<string | null>('Precision engineering');
  const [country, setCountry] = useState<string | null>('IN');
  const [tab, setTab] = useState('overview');

  return (
    <Section title="Controls">
      <Row label="Record tabs">
        <Tabs value={tab} onValueChange={setTab} className="w-full">
          <TabsList>
            <TabsTrigger value="overview">Details</TabsTrigger>
            <TabsTrigger value="qualification">Qualification</TabsTrigger>
            <TabsTrigger value="conversation">Activity</TabsTrigger>
            <TabsTrigger value="deals">Deals</TabsTrigger>
            <TabsTrigger value="documents">Documents</TabsTrigger>
            <TabsTrigger value="background-check">Background check</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
          </TabsList>
          {['overview', 'qualification', 'conversation', 'deals', 'documents', 'background-check', 'history'].map((key) => (
            <TabsContent key={key} value={key} className="pt-3 text-secondary text-ink-2">
              The tab&apos;s content.
            </TabsContent>
          ))}
        </Tabs>
      </Row>
      <Row label="Segmented">
        <Segmented
          label="Journey"
          value={lens}
          onValueChange={setLens}
          options={[
            { value: 'all', label: 'All' },
            { value: 'leads', label: 'Leads', count: 48 },
            { value: 'prospects', label: 'Prospects', count: 21 },
            { value: 'customers', label: 'Customers', count: '200+' },
          ]}
        />
        <Segmented
          label="Result"
          size="sm"
          value={result}
          onValueChange={setResult}
          options={[
            { value: 'PASS', label: 'Pass' },
            { value: 'FAIL', label: 'Fail' },
            { value: 'UNKNOWN', label: 'Unknown' },
          ]}
        />
      </Row>
      <Row label="Date popover">
        <DatePopover label="Check back on" value={date} onChange={setDate} verb="Park until then" />
        <DatePopover label="Due" value={null} onChange={setDate} />
      </Row>
      <Row label="Inline edit">
        <dl className="grid w-full max-w-xl gap-x-8 gap-y-3 sm:grid-cols-2">
          <div>
            <dt className="text-caption text-ink-3">Industry</dt>
            <dd>
              <Editable label="Industry" value={industry} onSave={setIndustry} />
            </dd>
          </div>
          <div>
            <dt className="text-caption text-ink-3">Country</dt>
            <dd>
              <Editable
                label="Country"
                kind="select"
                value={country}
                onSave={setCountry}
                options={[
                  { value: 'IN', label: 'India' },
                  { value: 'NL', label: 'Netherlands' },
                  { value: 'DE', label: 'Germany' },
                ]}
                display={country === 'IN' ? 'India' : country === 'NL' ? 'Netherlands' : 'Germany'}
              />
            </dd>
          </div>
          <div>
            <dt className="text-caption text-ink-3">Year founded (refused on save)</dt>
            <dd>
              <Editable
                label="Year founded"
                kind="number"
                value="2009"
                onSave={() => Promise.reject(new Error('Year founded cannot be in the future.'))}
              />
            </dd>
          </div>
          <div>
            <dt className="text-caption text-ink-3">Read only</dt>
            <dd>
              <Editable label="Industry" value="Seafood" onSave={() => undefined} readOnly />
            </dd>
          </div>
        </dl>
      </Row>
    </Section>
  );
}

function Fields() {
  return (
    <Section title="Fields" description="Used inside side panels only. There are no long forms on a page.">
      <div className="grid max-w-2xl gap-4 sm:grid-cols-2">
        <Field label="Company name" htmlFor="sg-name" required>
          <Input id="sg-name" placeholder="Lakshmi Polymers Pvt Ltd" />
        </Field>
        <Field label="Source" htmlFor="sg-source" hint="Where the lead came from.">
          <Select id="sg-source" defaultValue="SALES">
            <option value="SALES">Sales</option>
            <option value="REFERRAL">Referral</option>
          </Select>
        </Field>
        <Field label="PAN" htmlFor="sg-pan" error="This PAN belongs to another company.">
          <Input id="sg-pan" defaultValue="AAAPL1234C" aria-invalid />
        </Field>
        <Field label="Disabled" htmlFor="sg-disabled">
          <Input id="sg-disabled" disabled value="Not editable here" readOnly />
        </Field>
        <Field label="Reason" htmlFor="sg-reason" className="sm:col-span-2">
          <Textarea id="sg-reason" rows={2} placeholder="Why this decision" />
        </Field>
      </div>
      <FormError>Couldn&apos;t hand over: the seller&apos;s background check is not clear.</FormError>
    </Section>
  );
}

function Surfaces() {
  const [dialog, setDialog] = useState(false);
  const [panel, setPanel] = useState(false);
  return (
    <Section title="Floating surfaces" description="Menus, popovers, dialogs and the side panel share one shadow. Nothing else floats.">
      <Row label="Open one">
        <Button variant="primary" onClick={() => setPanel(true)}>
          New company
        </Button>
        <Button onClick={() => setDialog(true)}>Hand over</Button>
        <Popover>
          <PopoverTrigger asChild>
            <Button>Approve</Button>
          </PopoverTrigger>
          <PopoverContent>
            <p className="text-body font-semibold text-ink">Approve this Clear?</p>
            <p className="mt-1 text-secondary text-ink-2">Proposed by R. Mehta at 11:02.</p>
            <div className="mt-3 flex justify-end gap-2">
              <Button size="sm">Cancel</Button>
              <Button size="sm" variant="primary">
                Approve
              </Button>
            </div>
          </PopoverContent>
        </Popover>
        <ConfirmDialog
          open={dialog}
          onOpenChange={setDialog}
          title="Hand over this deal?"
          description="This cannot be undone. The handover record is taken at this moment."
          confirmLabel="Hand over"
          onConfirm={() => setDialog(false)}
        />
        <SidePanel
          open={panel}
          onOpenChange={setPanel}
          title="New company"
          submitLabel="Create lead"
          onSubmit={() => setPanel(false)}
        >
          <Field label="Identifier" htmlFor="sg-identifier" hint="PAN, GSTIN, IEC or CIN. The kind is detected.">
            <Input id="sg-identifier" placeholder="27AAAPL1234C1ZV" />
          </Field>
          <Field label="Company name" htmlFor="sg-panel-name" required>
            <Input id="sg-panel-name" />
          </Field>
          <Field label="Country" htmlFor="sg-panel-country" required>
            <Select id="sg-panel-country" defaultValue="IN">
              <option value="IN">India</option>
              <option value="NL">Netherlands</option>
            </Select>
          </Field>
        </SidePanel>
      </Row>
    </Section>
  );
}

function States() {
  return (
    <Section title="States" description="Shaped skeletons, one-line empty states, errors in the server's words.">
      <Row label="Counts">
        <Count value={48} />
        <Count value={21} />
        <Count value={200} cap={200} />
      </Row>
      <Row label="Empty">
        <EmptyLine action={<Button size="sm">Log a call</Button>}>No activity yet.</EmptyLine>
      </Row>
      <Row label="Inline error">
        <InlineError onRetry={() => undefined}>Couldn&apos;t load the history: the server did not answer.</InlineError>
      </Row>
      <Row label="Card error">
        <ErrorState title="Couldn't load this company" onRetry={() => undefined}>
          The server said: company not found.
        </ErrorState>
      </Row>
      <Row label="Loading">
        <div className="w-full max-w-md space-y-2">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-5/6" />
        </div>
      </Row>
      <Row label="Keys">
        <Kbd>Ctrl</Kbd>
        <Kbd>K</Kbd>
        <span className="text-secondary text-ink-3">or</span>
        <Kbd>/</Kbd>
        <span className="text-secondary text-ink-3">search ·</span>
        <Kbd>Ctrl</Kbd>
        <Kbd>/</Kbd>
        <span className="text-secondary text-ink-3">shortcuts</span>
      </Row>
    </Section>
  );
}

function Icons() {
  const names = Object.keys(Icon) as IconName[];
  return (
    <Section title="Icons" description="Fluent UI System Icons, regular, 20 px.">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(8rem,1fr))] gap-3">
        {names.map((name) => {
          const Glyph = Icon[name];
          return (
            <div key={name} className="flex items-center gap-2 text-ink-2">
              <Glyph size={20} aria-hidden />
              <span className="truncate text-caption">{name}</span>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function Pane({ theme }: { theme: 'light' | 'dark' }) {
  return (
    <div
      data-theme={theme}
      data-testid={`styleguide-${theme}`}
      className="min-w-0 space-y-4 bg-paper p-4 text-body text-ink sm:p-6"
    >
      <header className="flex h-12 items-center justify-between gap-4 rounded border border-line bg-surface px-4">
        <BrandMark />
        <span className="text-caption text-ink-3">{theme === 'light' ? 'Light theme' : 'Dark theme'}</span>
      </header>
      <OnboardingStyleGuide />
      <Palette />
      <Type />
      <Buttons />
      <Badges />
      <Controls />
      <Fields />
      <Surfaces />
      <States />
      <Icons />
    </div>
  );
}

type Show = 'light' | 'dark' | 'both';

export function StyleGuidePage() {
  const [show, setShow] = useState<Show>('light');
  return (
    <main className="min-h-screen bg-paper">
      <div className="sticky top-0 z-30 flex h-12 items-center justify-between gap-4 border-b border-line bg-surface px-4 sm:px-6">
        <h1 className="text-heading font-semibold text-ink">Style guide</h1>
        <Segmented
          label="Theme"
          size="sm"
          value={show}
          onValueChange={setShow}
          options={[
            { value: 'light', label: 'Light' },
            { value: 'dark', label: 'Dark' },
            { value: 'both', label: 'Both' },
          ]}
        />
      </div>
      {(show === 'light' || show === 'both') && <Pane theme="light" />}
      {(show === 'dark' || show === 'both') && <Pane theme="dark" />}
    </main>
  );
}
