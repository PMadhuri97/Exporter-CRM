/**
 * The design primitives (frontend-plan §6.11): each behaves as the screens will
 * rely on it — tones that carry a meaning, one choice always held, an edit that
 * saves on Enter and survives a refusal, an honest cap on a count.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { Count, EmptyLine, InlineError } from './Feedback';
import { DatePopover } from './DatePopover';
import { Editable } from './Editable';
import { Popover, PopoverContent, PopoverTrigger } from './Popover';
import { Segmented } from './Segmented';
import { Tag } from './Tag';

describe('Tag', () => {
  it('draws its meaning as a tint and a text colour, with an optional dot', () => {
    render(
      <Tag tone="negative" dot data-testid="tag">
        Flagged
      </Tag>,
    );
    const tag = screen.getByTestId('tag');
    expect(tag).toHaveTextContent('Flagged');
    expect(tag.className).toContain('bg-negative-tint');
    expect(tag.className).toContain('text-negative');
    expect(tag.className).toContain('rounded-sm');
    expect(tag.querySelector('[aria-hidden]')?.className).toContain('bg-negative-solid');
  });

  it('lets a domain tag supply its own look', () => {
    render(
      <Tag className="bg-transparent text-ink" data-testid="tag">
        Lead
      </Tag>,
    );
    expect(screen.getByTestId('tag').className).not.toContain('bg-sunken');
  });
});

describe('Segmented', () => {
  function Harness({ onChange }: { onChange: (v: string) => void }) {
    const [value, setValue] = useState<'PASS' | 'FAIL'>('PASS');
    return (
      <Segmented
        label="Result"
        value={value}
        onValueChange={(next) => {
          setValue(next);
          onChange(next);
        }}
        options={[
          { value: 'PASS', label: 'Pass' },
          { value: 'FAIL', label: 'Fail', count: 3 },
        ]}
      />
    );
  }

  it('holds exactly one value: choosing moves it, re-choosing keeps it', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const group = screen.getByRole('radiogroup', { name: 'Result' });
    expect(group).toBeInTheDocument();

    const pass = screen.getByRole('radio', { name: 'Pass' });
    const fail = screen.getByRole('radio', { name: /Fail/ });
    expect(pass).toHaveAttribute('aria-checked', 'true');
    expect(fail).toHaveTextContent('3');

    fireEvent.click(fail);
    expect(onChange).toHaveBeenLastCalledWith('FAIL');
    expect(fail).toHaveAttribute('aria-checked', 'true');

    // Clicking the chosen segment again does not leave the group empty.
    fireEvent.click(fail);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(fail).toHaveAttribute('aria-checked', 'true');
  });
});

describe('Editable', () => {
  it('keeps a value with its own controls outside the edit button when the pencil is the trigger', () => {
    render(
      <Editable
        label="PAN"
        value="AAACA1234Z"
        onSave={vi.fn()}
        trigger="pencil"
        display={<button type="button">Copy value</button>}
      />,
    );
    const edit = screen.getByRole('button', { name: 'Edit PAN' });
    const copy = screen.getByRole('button', { name: 'Copy value' });
    expect(edit).not.toContainElement(copy);
    fireEvent.click(edit);
    expect(screen.getByRole('textbox', { name: 'PAN' })).toHaveValue('AAACA1234Z');
  });

  it('reads as text with an edit button, and saves a changed value on Enter', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<Editable label="Industry" value="Seafood" onSave={onSave} />);

    fireEvent.click(screen.getByRole('button', { name: 'Edit Industry' }));
    const field = screen.getByRole('textbox', { name: 'Industry' });
    expect(field).toHaveValue('Seafood');

    fireEvent.change(field, { target: { value: 'Spices' } });
    fireEvent.keyDown(field, { key: 'Enter' });

    await waitFor(() => expect(onSave).toHaveBeenCalledWith('Spices'));
    expect(await screen.findByRole('button', { name: 'Edit Industry' })).toBeInTheDocument();
  });

  it('puts the old value back on Escape without saving', () => {
    const onSave = vi.fn();
    render(<Editable label="Industry" value="Seafood" onSave={onSave} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit Industry' }));
    const field = screen.getByRole('textbox', { name: 'Industry' });
    fireEvent.change(field, { target: { value: 'Spices' } });
    fireEvent.keyDown(field, { key: 'Escape' });

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Edit Industry' })).toHaveTextContent('Seafood');
  });

  it('keeps the draft and shows the refusal in the server’s words', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('Year founded cannot be in the future.'));
    render(<Editable label="Year founded" kind="number" value="2009" onSave={onSave} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit Year founded' }));
    const field = screen.getByRole('spinbutton', { name: 'Year founded' });
    fireEvent.change(field, { target: { value: '2099' } });
    fireEvent.keyDown(field, { key: 'Enter' });

    expect(await screen.findByRole('alert')).toHaveTextContent('Year founded cannot be in the future.');
    expect(screen.getByRole('spinbutton', { name: 'Year founded' })).toHaveValue(2099);
    expect(screen.getByRole('spinbutton', { name: 'Year founded' })).toHaveAttribute('aria-invalid', 'true');
  });

  it('does not call the server when nothing changed', async () => {
    const onSave = vi.fn();
    render(<Editable label="Industry" value="Seafood" onSave={onSave} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit Industry' }));
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Industry' }), { key: 'Enter' });
    await screen.findByRole('button', { name: 'Edit Industry' });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('offers no control at all when read-only', () => {
    render(<Editable label="Industry" value="Seafood" onSave={vi.fn()} readOnly />);
    expect(screen.getByText('Seafood')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('saves a select as soon as a new option is chosen', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <Editable
        label="Country"
        kind="select"
        value="IN"
        onSave={onSave}
        options={[
          { value: 'IN', label: 'India' },
          { value: 'NL', label: 'Netherlands' },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Edit Country' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Country' }), { target: { value: 'NL' } });
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('NL'));
  });
});

describe('DatePopover', () => {
  it('names the trigger with its value and sets a date from the popover', async () => {
    const onChange = vi.fn();
    render(<DatePopover label="Check back on" value={null} onChange={onChange} verb="Park" />);

    const trigger = screen.getByRole('button', { name: 'Check back on: not set' });
    fireEvent.click(trigger);
    const input = await screen.findByLabelText('Check back on');
    fireEvent.change(input, { target: { value: '2026-11-12' } });
    fireEvent.click(screen.getByRole('button', { name: 'Park' }));

    expect(onChange).toHaveBeenCalledWith('2026-11-12');
  });

  it('shows a chosen date on the trigger', () => {
    render(<DatePopover label="Due" value="2026-11-12" onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Due: 12 Nov 2026' })).toBeInTheDocument();
  });
});

describe('Popover', () => {
  it('opens next to its trigger and closes on Escape', async () => {
    render(
      <Popover>
        <PopoverTrigger>Approve</PopoverTrigger>
        <PopoverContent>Approve this Clear?</PopoverContent>
      </Popover>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(await screen.findByText('Approve this Clear?')).toBeInTheDocument();

    await act(async () => {
      fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
    });
    await waitFor(() => expect(screen.queryByText('Approve this Clear?')).not.toBeInTheDocument());
  });
});

describe('Count, EmptyLine and InlineError', () => {
  it('says "200+" at the cap, never a guess', () => {
    const { rerender } = render(<Count value={48} cap={200} data-testid="count" />);
    expect(screen.getByTestId('count')).toHaveTextContent('48');
    rerender(<Count value={200} cap={200} data-testid="count" />);
    expect(screen.getByTestId('count')).toHaveTextContent('200+');
  });

  it('keeps an empty state to one line and an optional verb', () => {
    render(<EmptyLine action={<button type="button">Log a call</button>}>No activity yet.</EmptyLine>);
    expect(screen.getByText('No activity yet.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Log a call' })).toBeInTheDocument();
  });

  it('announces an error and offers a retry', () => {
    const onRetry = vi.fn();
    render(<InlineError onRetry={onRetry}>Couldn’t load the ledger.</InlineError>);
    expect(screen.getByRole('alert')).toHaveTextContent('Couldn’t load the ledger.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalled();
  });
});

describe('Composer', () => {
  it('submits with its verb, places a named refusal on its field, and the rest in the footer', async () => {
    const { Composer } = await import('./Composer');
    const { composerFieldError } = await import('./composerFieldError');
    const { ApiError } = await import('@/lib/api/errors');
    const onSubmit = vi.fn();
    const fieldRefusal = new ApiError(422, 'subject: Field required', null, null, null, {
      subject: 'Field required',
    });
    const { rerender } = render(
      <Composer
        open
        onOpenChange={vi.fn()}
        title="Log a call"
        submitLabel="Log it"
        onSubmit={onSubmit}
        fields={['subject']}
        error={fieldRefusal}
      >
        <label htmlFor="subject">Subject</label>
        <input id="subject" />
        <p role="alert">{composerFieldError(fieldRefusal, 'subject')}</p>
      </Composer>,
    );
    expect(screen.getByRole('dialog', { name: 'Log a call' })).toBeInTheDocument();
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(screen.getByRole('alert')).toHaveTextContent('Field required');

    fireEvent.click(screen.getByRole('button', { name: 'Log it' }));
    expect(onSubmit).toHaveBeenCalled();

    rerender(
      <Composer
        open
        onOpenChange={vi.fn()}
        title="Log a call"
        submitLabel="Log it"
        onSubmit={onSubmit}
        error={new ApiError(409, 'Someone moved it; look again.')}
      >
        <input aria-label="Subject" />
      </Composer>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Someone moved it; look again.');
  });
});
