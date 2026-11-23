const items = [{ name: "Boat cover", price: 45, qty: 1 }];

function render() {
  const list = document.getElementById("items");
  list.innerHTML = items.map((i) => `<li>${i.name} x ${i.qty}</li>`).join("");
  const total = items.reduce((sum, i) => sum + i.price * i.qty, 0);
  document.getElementById("total").textContent = total.toFixed(2);
}

render();
