import { humanize } from '@/lib/format';

/** Category names as people say them; anything else is humanised. */
const CATEGORY_LABEL: Record<string, string> = {
  KYC: 'KYC',
  KYB: 'KYB',
  AML: 'AML',
  PRE_SHIPMENT: 'Pre-shipment',
  POST_SHIPMENT: 'Post-shipment',
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] ?? humanize(category);
}
