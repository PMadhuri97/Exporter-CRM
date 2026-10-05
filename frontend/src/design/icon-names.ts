/**
 * Every icon the app draws, named by what it means (frontend-plan §5.8) — the one
 * list to edit. Screens say `<Icon.followUp />` (`./icons.ts`), never a glyph's
 * own name, so the set can change here.
 *
 * Each value is a Fluent UI System Icons name (Microsoft, MIT), drawn at its 20 px
 * size. The package ships every glyph at six sizes and three styles; the app draws
 * one, so `scripts/build-icons.mjs` copies only the `regular` path — and `filled`
 * for the glyphs in `FILLED` — into `icon-paths.ts`. After editing this file, run
 * `pnpm icons` (the test in `icons.test.ts` fails until you do).
 */

export const ICON_NAMES = {
  // Modules and places.
  home: 'home',
  company: 'building',
  followUps: 'task_list_ltr',
  pipeline: 'board',
  approvals: 'approvals_app',
  settings: 'settings',
  criteria: 'options',
  requiredDocuments: 'document_multiple',
  deal: 'briefcase',
  branch: 'building_bank',
  trade: 'handshake',
  users: 'people',
  roles: 'person_key',
  person: 'person_circle',

  // Record dimensions.
  journey: 'arrow_routing',
  qualification: 'ribbon',
  conversation: 'chat',
  logActivity: 'chat_add',
  backgroundCheck: 'shield_checkmark',
  shield: 'shield',
  flagged: 'shield_error',
  marker: 'flag',
  profile: 'person_edit',
  identity: 'fingerprint',
  document: 'document_text',
  csv: 'document_table',
  checklist: 'clipboard_task_list_ltr',
  history: 'history',
  activity: 'pulse',
  receipt: 'receipt',
  signature: 'signature',
  paperclip: 'attach',

  // Time.
  followUp: 'calendar_clock',
  calendar: 'calendar_ltr',
  clock: 'clock',
  pause: 'pause_circle',

  // States.
  passed: 'checkmark_circle',
  check: 'checkmark',
  done: 'checkbox_checked',
  warning: 'warning',
  error: 'error_circle',
  info: 'info',
  notStarted: 'circle',
  notConnected: 'plug_disconnected',
  prohibited: 'prohibited',
  locked: 'lock_closed',
  hint: 'lightbulb',
  primary: 'star',

  // Actions.
  add: 'add',
  addUser: 'person_add',
  edit: 'edit',
  remove: 'delete',
  close: 'dismiss',
  search: 'search',
  filter: 'filter',
  upload: 'arrow_upload',
  download: 'arrow_download',
  copy: 'copy',
  external: 'open',
  retry: 'arrow_sync',
  reveal: 'eye',
  conceal: 'eye_off',
  key: 'key',
  signOut: 'sign_out',
  more: 'more_horizontal',
  menu: 'navigation',
  keyboard: 'keyboard',
  question: 'question_circle',
  spinner: 'spinner_ios',

  // Direction.
  back: 'arrow_left',
  forward: 'arrow_right',
  caretDown: 'chevron_down',
  caretUp: 'chevron_up',
  caretLeft: 'chevron_left',
  caretRight: 'chevron_right',
  navCollapse: 'panel_left_contract',
  navExpand: 'panel_left_expand',

  // Theme.
  themeLight: 'weather_sunny',
  themeDark: 'weather_moon',

  // Contact.
  email: 'mail',
  phone: 'call',
  place: 'location',
  country: 'globe',
} as const;

export type IconName = keyof typeof ICON_NAMES;

/** Glyphs also drawn filled: the side navigation marks the current module so, and
 * the Critical risk badge draws its warning solid. */
export const FILLED: readonly IconName[] = [
  'home',
  'company',
  'followUps',
  'pipeline',
  'approvals',
  'settings',
  'criteria',
  'requiredDocuments',
  'users',
  'roles',
  'person',
  'warning',
];
