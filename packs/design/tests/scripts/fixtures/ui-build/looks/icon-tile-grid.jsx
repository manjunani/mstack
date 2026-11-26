export function Features() {
  return (
    <div>
      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-orange-100"><TruckIcon /></div>
      <h3 className="mt-4">Carrier choice</h3>
      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-orange-100"><TagIcon /></div>
      <h3 className="mt-4">Batch labels</h3>
      <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-orange-100"><BoxIcon /></div>
      <h3 className="mt-4">Return slips</h3>
    </div>
  );
}
