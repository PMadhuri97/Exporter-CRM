/** Words for a company address: its type, and the address on one line. */

import { countryLabel } from '../countries';
import type { CompanyAddress, CompanyAddressType } from '../types';

export const ADDRESS_TYPE_LABEL: Record<CompanyAddressType, string> = {
  REGISTERED: 'Registered',
  BILLING: 'Billing',
  SHIPPING: 'Shipping',
  FACTORY_WAREHOUSE: 'Factory / warehouse',
  CORRESPONDENCE: 'Correspondence',
};

/** "12 Marine Drive, Floor 3, Mumbai, Maharashtra 400001, India". */
export function addressLine(address: CompanyAddress): string {
  const place = [address.state, address.postal_code].filter(Boolean).join(' ');
  return [address.line1, address.line2, address.city, place, countryLabel(address.country)]
    .filter(Boolean)
    .join(', ');
}
