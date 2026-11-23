const items = [{ name: "Boat cover", price: 45, qty: 1 }];

function render() {
  const list = document.getElementById("items");
  list.innerHTML = items
    .map((i, n) => `<li>${i.name} <input type="number" min="0" value="${i.qty}" data-row="${n}"></li>`)
    .join("");
  const total = items.reduce((sum, i) => sum + i.price * i.qty, 0);
  document.getElementById("total").textContent = total.toFixed(2);
}

document.addEventListener("change", (event) => {
  const row = event.target.dataset.row;
  if (row !== undefined) {
    items[row].qty = Number(event.target.value);
    if (items[row].qty === 0) items.splice(row, 1);
  }
});

render();
