export function Orders({ orders, onPrint }) {
  return (
    <section className="rounded-2xl">
      <h1>Orders waiting to ship</h1>
      <p>{orders.length} orders need a carrier label before 4 pm.</p>
      <button className="focus:outline-none focus-visible:ring-2" onClick={onPrint}>Print {orders.length} labels</button>
    </section>
  );
}
