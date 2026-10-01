import React from 'react';
import PriceTag from './PriceTag';

type Props = { price: number; quantity: number };

export const ProductTile = ({ price, quantity }: Props) => {
  const total = price * quantity;
  return (
    <div className="tile">
      {price > 150 && <span className="premium">Premium</span>}
      <PriceTag price={total} />
    </div>
  );
};
