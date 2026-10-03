import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { NotInPipelineNotice } from './NotInPipelineNotice';

it('says what is not needed and why, rather than showing an empty form', () => {
  render(<NotInPipelineNotice what="Qualification" />);

  expect(screen.getByText(/Qualification is not needed/)).toBeInTheDocument();
  expect(screen.getByText(/buyer on a deal/)).toBeInTheDocument();
  // It is still a full company record — that is the part someone reading this needs
  // to know, or they will assume the company is half-created.
  expect(screen.getByText(/screened and cleared like any other/)).toBeInTheDocument();
});

it('offers the one action that changes it, for a role that may act', () => {
  const onBringIn = vi.fn();
  render(<NotInPipelineNotice what="Qualification" onBringIn={onBringIn} />);

  fireEvent.click(screen.getByRole('button', { name: /Bring into the pipeline/ }));
  expect(onBringIn).toHaveBeenCalled();
});

it('offers no action to a role the server would refuse', () => {
  // DEVELOPER is read-only throughout the CRM, so a button here would 403.
  render(<NotInPipelineNotice what="Qualification" />);
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it('cannot be pressed twice while the request is in flight', () => {
  // The route is a 409 the second time — it starts a journey, and doing that twice
  // would append a second LEAD row.
  render(<NotInPipelineNotice what="Qualification" onBringIn={vi.fn()} busy />);
  expect(screen.getByRole('button', { name: /Bring into the pipeline/ })).toBeDisabled();
});
