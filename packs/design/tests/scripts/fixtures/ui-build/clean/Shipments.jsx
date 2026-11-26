export function Shipments({ shipments, loading, onBook, onTrack }) {
  if (loading) {
    return <div className="h-24 animate-pulse rounded bg-stone-200" aria-busy="true" />;
  }
  return (
    <main className="mx-auto max-w-5xl px-6 py-10 text-left">
      <p className="text-xs uppercase tracking-wide text-stone-600">Depot 4, Leeds</p>
      <h1 className="text-3xl font-semibold">Shipments leaving today</h1>
      <p className="mt-2 text-stone-700">{shipments.length} parcels are booked on the 16:00 van.</p>
      <button className="mt-4 bg-teal-700 px-4 py-2 font-medium text-white hover:bg-teal-800" onClick={onBook}>Book the 16:00 pickup</button>
      <form className="mt-8">
        <label htmlFor="name">Recipient</label>
        <input id="name" placeholder="Jane Doe" className="border px-2" />
        <label htmlFor="mail">Email for tracking</label>
        <input id="mail" type="email" placeholder="you@example.com" className="border px-2" />
      </form>
      <section className="mt-10">
        <h2 className="font-semibold">What needs you</h2>
        <div className="rounded border p-4 shadow-sm">
          <h3>Address check</h3>
          <p>Two parcels have a postcode the carrier rejected.</p>
        </div>
        <div className="rounded border p-4 shadow-sm hover:scale-105">
          <h3>Customs form missing for Oslo</h3>
          <p>One export needs a CN22 before it can go.</p>
        </div>
        <div className="rounded-md border bg-white p-4">
          <h3>Pallet</h3>
          <p>The pallet for Bristol is too heavy for the standard van and needs the tail-lift truck tomorrow morning.</p>
        </div>
      </section>
      <p className="mt-6 text-center text-sm text-stone-600">Rates last updated 06:00.</p>
      <a className="text-indigo-700 underline" href="/help/pickups" onClick={onTrack}>How pickups work</a>
    </main>
  );
}
