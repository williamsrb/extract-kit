import React from 'react';

export default function PriceTag({ price }: { price: number }) {
  return <span className="price">{price.toFixed(2)}</span>;
}
