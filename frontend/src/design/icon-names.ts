/**
 * Every icon the app draws, named by what it means (frontend-plan §5.5) — the one
 * list to edit. Screens say `<Icon.followUp />` (`./icons.ts`), never a glyph's
 * own name, so the set can change here.
 *
 * Each value is a Phosphor glyph name. Phosphor's own modules carry six weights per
 * glyph (295 kB for this set); the app draws one, so `scripts/build-icons.mjs` copies
 * only the `regular` paths — and `fill` for the glyphs in `FILLED` — into
 * `icon-paths.ts`. After editing this file, run `pnpm icons` (the test in
 * `icons.test.ts` fails until you do).
 */

export const ICON_NAMES = {
  // Modules and places.
  desk: 'House',
  company: 'Buildings',
  agenda: 'ListChecks',
  board: 'Kanban',
  review: 'Seal',
  settings: 'Gear',
  criteria: 'SlidersHorizontal',
  requiredDocuments: 'Files',
  deal: 'Briefcase',
  branch: 'Bank',
  trade: 'Handshake',
  explore: 'Compass',
  users: 'Users',
  roles: 'IdentificationCard',
  person: 'UserCircle',

  // Record dimensions.
  journey: 'Path',
  qualification: 'SealCheck',
  conversation: 'ChatCircle',
  logActivity: 'ChatCircleText',
  backgroundCheck: 'ShieldCheck',
  shield: 'Shield',
  flagged: 'ShieldWarning',
  marker: 'Flag',
  profile: 'PencilSimpleLine',
  identity: 'Fingerprint',
  document: 'FileText',
  csv: 'FileCsv',
  checklist: 'ClipboardText',
  history: 'ClockCounterClockwise',
  activity: 'Pulse',
  receipt: 'Receipt',
  signature: 'Signature',
  paperclip: 'Paperclip',

  // Time.
  followUp: 'CalendarDots',
  calendar: 'CalendarBlank',
  clock: 'Clock',
  pause: 'PauseCircle',

  // States.
  passed: 'CheckCircle',
  check: 'Check',
  done: 'Checks',
  warning: 'Warning',
  error: 'WarningCircle',
  info: 'Info',
  notStarted: 'CircleDashed',
  notConnected: 'Plugs',
  prohibited: 'Prohibit',
  locked: 'LockSimple',
  hint: 'Lightbulb',
  primary: 'Star',

  // Actions.
  add: 'Plus',
  addUser: 'UserPlus',
  edit: 'PencilSimple',
  remove: 'Trash',
  close: 'X',
  search: 'MagnifyingGlass',
  filter: 'Funnel',
  upload: 'UploadSimple',
  download: 'DownloadSimple',
  copy: 'Copy',
  external: 'ArrowSquareOut',
  retry: 'ArrowsClockwise',
  reveal: 'Eye',
  conceal: 'EyeSlash',
  key: 'Key',
  signOut: 'SignOut',
  more: 'DotsThree',
  menu: 'List',
  command: 'Command',
  keyboard: 'Keyboard',
  question: 'Question',
  spinner: 'CircleNotch',

  // Direction.
  back: 'ArrowLeft',
  forward: 'ArrowRight',
  caretDown: 'CaretDown',
  caretUp: 'CaretUp',
  caretLeft: 'CaretLeft',
  caretRight: 'CaretRight',
  railCollapse: 'CaretDoubleLeft',
  railExpand: 'CaretDoubleRight',

  // Theme.
  themeSystem: 'Monitor',
  themeLight: 'Sun',
  themeDark: 'Moon',

  // Contact.
  email: 'Envelope',
  phone: 'Phone',
  place: 'MapPin',
  country: 'Globe',
} as const;

export type IconName = keyof typeof ICON_NAMES;

/** Glyphs also drawn filled — the rail and bottom bar mark the active module so. */
export const FILLED: readonly IconName[] = [
  'desk',
  'company',
  'agenda',
  'board',
  'review',
  'settings',
  'criteria',
  'requiredDocuments',
];
