/** Where an automatic qualification answer comes from, and which kind of criterion each fits. */

import type { CriterionKind } from '../types';

export type AutoSource =
  | 'IEC_VERIFICATION'
  | 'YEARS_ESTABLISHED'
  | 'INDUSTRY'
  | 'EXPORT_MARKETS'
  | 'TRADE_HISTORY'
  | 'DEAL_VALUE';

export const AUTO_SOURCE_LABEL: Record<AutoSource, string> = {
  IEC_VERIFICATION: 'IEC check',
  YEARS_ESTABLISHED: 'Year established',
  INDUSTRY: 'Company industry',
  EXPORT_MARKETS: 'Export markets',
  TRADE_HISTORY: 'Trade history',
  DEAL_VALUE: 'Deal value',
};

export const AUTO_SOURCE_KIND: Record<AutoSource, CriterionKind> = {
  IEC_VERIFICATION: 'YES_NO',
  YEARS_ESTABLISHED: 'NUMBER_THRESHOLD',
  INDUSTRY: 'ALLOWED_VALUES',
  EXPORT_MARKETS: 'ALLOWED_VALUES',
  TRADE_HISTORY: 'YES_NO',
  DEAL_VALUE: 'NUMBER_THRESHOLD',
};

export const AUTO_SOURCE_RULE: Record<AutoSource, string> = {
  IEC_VERIFICATION: 'Pass when a passed IEC check is recorded',
  YEARS_ESTABLISHED: 'Years since the year established, or the incorporation year in the CIN',
  INDUSTRY: "The company's industry is one of the allowed values",
  EXPORT_MARKETS: 'Any export market is one of the allowed values',
  TRADE_HISTORY: 'Pass when at least one export is recorded',
  DEAL_VALUE: 'The largest deal value, in the unit when it is a currency',
};
