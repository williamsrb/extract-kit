import React from 'react';

type Props = { price: number };

export default function FeaturedPage({ price }: Props) {
  return <main>{price > 150 && <b>Premium</b>}</main>;
}
