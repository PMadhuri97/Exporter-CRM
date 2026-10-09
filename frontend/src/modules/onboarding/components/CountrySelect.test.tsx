import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { CountrySelect } from './CountrySelect';

function Harness({ initial = '', onChange = vi.fn() }: { initial?: string; onChange?: (code: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="country">Country</label>
      <CountrySelect
        id="country"
        value={value}
        onChange={(code) => {
          setValue(code);
          onChange(code);
        }}
      />
    </>
  );
}

function optionNames() {
  return screen.getAllByRole('option').map((option) => option.textContent);
}

describe('CountrySelect', () => {
  it('shows the name of the stored code', () => {
    render(<Harness initial="NL" />);
    expect(screen.getByRole('combobox', { name: 'Country' })).toHaveTextContent('Netherlands');
  });

  it('offers India first, then every other country by name', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Country' }));
    const names = optionNames();
    expect(names[0]).toBe('IndiaIN');
    expect(names).toHaveLength(249);
    expect(names[1]).toBe('AfghanistanAF');
  });

  it('narrows the list as you type a name or a code, and returns the code', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Country' }));
    fireEvent.change(screen.getByPlaceholderText('Search countries'), { target: { value: 'ind' } });
    expect(optionNames()).toEqual(expect.arrayContaining(['IndiaIN', 'IndonesiaID']));
    expect(optionNames()).not.toContain('NetherlandsNL');

    fireEvent.click(screen.getAllByRole('option').find((o) => o.textContent === 'IndonesiaID')!);
    expect(onChange).toHaveBeenCalledWith('ID');
    expect(screen.getByRole('combobox', { name: 'Country' })).toHaveTextContent('Indonesia');
  });

  it('keeps showing a stored value that is not a known code', () => {
    render(<Harness initial="XX" />);
    expect(screen.getByRole('combobox', { name: 'Country' })).toHaveTextContent('XX');
  });
});
