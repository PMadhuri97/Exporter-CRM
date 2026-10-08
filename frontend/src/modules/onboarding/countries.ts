/**
 * Countries, for the one place that asks someone to pick one.
 *
 * The codes are ISO 3166-1 alpha-2, which is what `exporter_profile.country` stores and
 * what the server matches on. The *names* are not listed: `Intl.DisplayNames` has them
 * already, correctly spelt and in the reader's own language, and a hand-typed list of
 * 249 names is 249 chances to misspell somebody's country.
 *
 * India is pinned to the top rather than sorted into the Is. Nearly every company here
 * is Indian, and scrolling past Iceland to reach the common case is a small tax paid on
 * every use.
 */

/** ISO 3166-1 alpha-2, the officially assigned codes. */
const ISO_ALPHA2 =
  'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN ' +
  'BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ ' +
  'DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL ' +
  'GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM ' +
  'JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME ' +
  'MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP ' +
  'NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD ' +
  'SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO ' +
  'TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW';

/** The home market, first in the list. */
const PINNED = 'IN';

/**
 * A country's name, or its code when the runtime cannot name it.
 *
 * `Intl.DisplayNames` needs a full-ICU build; a trimmed one returns the code back or
 * throws, and neither should empty the dropdown. The code is a poor label but an honest
 * one, and it is what gets sent either way.
 */
function countryName(code: string, display: Intl.DisplayNames | null): string {
  if (!display) return code;
  try {
    return display.of(code) ?? code;
  } catch {
    return code;
  }
}

export interface CountryOption {
  code: string;
  name: string;
}

/** Every country, India first and the rest by name. Built once, on first use. */
export const COUNTRY_OPTIONS: readonly CountryOption[] = (() => {
  let display: Intl.DisplayNames | null = null;
  try {
    display = new Intl.DisplayNames(['en'], { type: 'region' });
  } catch {
    display = null;
  }
  const options = ISO_ALPHA2.split(' ')
    .filter(Boolean)
    .map((code) => ({ code, name: countryName(code, display) }));
  const pinned = options.filter((option) => option.code === PINNED);
  const rest = options
    .filter((option) => option.code !== PINNED)
    .sort((a, b) => a.name.localeCompare(b.name));
  return [...pinned, ...rest];
})();
