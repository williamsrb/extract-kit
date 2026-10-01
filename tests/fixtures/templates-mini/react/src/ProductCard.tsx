import React from 'react';
import PriceTag from './PriceTag';

interface Props {
  title: string;
  price: number;
  items: string[];
  onBuy: () => void;
}

export function ProductCard({ title, price, items, onBuy }: Props) {
  return (
    <div className="card">
      <h3>{title}</h3>
      {price > 100 && <span className="premium">Premium</span>}
      {items.length > 0 && <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>}
      <PriceTag price={price} />
      <button onClick={onBuy}>Buy</button>
    </div>
  );
}
