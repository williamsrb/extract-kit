import React from 'react';

const DISABLED = true;
const LIMIT_ON = false;

export function Banner({ booking }: { booking: { status: string; total: number } }) {
  if (LIMIT_ON) {
    return <div>{booking.status === 'late' && <span>Late</span>}</div>;
  }
  return <div>{booking.total > 500 && <span>Big</span>}</div>;
}

export function Early({ booking }: { booking: { status: string; total: number } }) {
  if (DISABLED) return null;
  return <div>{booking.status === 'paid' && booking.total > 500 && <b>Paid</b>}</div>;
}
