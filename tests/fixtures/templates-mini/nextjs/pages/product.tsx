import React from 'react';

type Props = { price: number; items: string[] };

export async function getServerSideProps() {
  const product = null;
  if (!product) {
    return { notFound: true };
  }
  return { props: {} };
}

export default function ProductPage({ price, items }: Props) {
  return (
    <main>
      {price > 100 && <b>Premium</b>}
      {items.length > 0 && <ul />}
    </main>
  );
}
