/**
 * The ISO 3166-1 alpha-2 country codes the CRM stores (249), and their English names.
 *
 * The same list the server uses for the import template (`domain/countries.py`). Names
 * come from the browser (`countryName`), so only the codes live here.
 */

import { countryName } from './constants';

export const COUNTRY_CODES: readonly string[] = `
AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR
BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ
EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW
GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY
KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV
MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY
QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG
TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM
ZW
`
  .trim()
  .split(/\s+/);

/** The country chosen most often, offered first. */
export const PINNED_COUNTRY = 'IN';

const CODES = new Set(COUNTRY_CODES);

/** Whether `code` is one of the ISO codes above. */
export function isCountryCode(code: string): boolean {
  return CODES.has(code);
}

/** Every country as `{ code, name }`, India first, then by name. */
export function countryOptions(): { code: string; name: string }[] {
  const rest = COUNTRY_CODES.filter((code) => code !== PINNED_COUNTRY)
    .map((code) => ({ code, name: countryName(code) }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return [{ code: PINNED_COUNTRY, name: countryName(PINNED_COUNTRY) }, ...rest];
}

/** A country as a person reads it: "India", or the stored value itself if it is not a known code. */
export function countryLabel(code: string | null | undefined): string {
  if (!code) return '';
  return isCountryCode(code.toUpperCase()) ? countryName(code.toUpperCase()) : code;
}

/**
 * The countries as `{ value, label }` for a plain select. A stored value that is not a
 * known code is kept as the first option, so opening an old record never changes it.
 */
export function countrySelectOptions(current?: string | null): { value: string; label: string }[] {
  const options = countryOptions().map(({ code, name }) => ({ value: code, label: name }));
  if (current && !isCountryCode(current)) return [{ value: current, label: current }, ...options];
  return options;
}
