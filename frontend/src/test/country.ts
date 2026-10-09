/**
 * Choose a country in a `CountrySelect`, the way a person does: open the list and pick
 * the entry. `code` is the ISO code ("IN"), which each entry shows after the name.
 */

import { fireEvent, screen } from '@testing-library/react';

export async function chooseCountry(code: string, label: RegExp | string = /country/i) {
  fireEvent.click(screen.getByRole('combobox', { name: label }));
  const options = await screen.findAllByRole('option');
  const option = options.find((candidate) => candidate.textContent?.endsWith(code));
  if (!option) throw new Error(`No country option for ${code}`);
  fireEvent.click(option);
}
