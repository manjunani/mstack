export function Hero({ onStart, onRead }) {
  return (
    <section>
      <h1>Freight quotes for small shippers</h1>
      <button onClick={onStart}>Get started</button>
      <a href="/docs">Learn more</a>
    </section>
  );
}
