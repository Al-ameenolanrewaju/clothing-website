(function () {
  "use strict";
  const KEY = "storefront_cart_v1";
  const money = value => new Intl.NumberFormat("en-NG", { style: "currency", currency: "NGN", maximumFractionDigits: 0 }).format(Number(value) || 0);
  const readCart = () => {
    try {
      const value = JSON.parse(localStorage.getItem(KEY) || "[]");
      return Array.isArray(value) ? value : [];
    } catch (_) { return []; }
  };
  const drawer = () => document.getElementById("store-cart-drawer");
  const saveCart = cart => {
    localStorage.setItem(KEY, JSON.stringify(cart));
    updateCount(cart);
    renderCart();
  };
  function updateCount(cart) {
    const count = cart.reduce((sum, item) => sum + (Number(item.quantity) || 0), 0);
    document.querySelectorAll("[data-cart-count]").forEach(el => { el.textContent = count; });
    document.querySelectorAll("[data-cart-drawer-count]").forEach(el => { el.textContent = "(" + count + ")"; });
  }
  function openCart() {
    const panel = drawer();
    if (!panel) return;
    const trigger = document.querySelector("[data-cart-open]");
    panel.hidden = false;
    panel.setAttribute("aria-hidden", "false");
    document.querySelector("[data-cart-overlay]").hidden = false;
    document.body.classList.add("cart-is-open");
    if (trigger) trigger.setAttribute("aria-expanded", "true");
    renderCart();
    const close = panel.querySelector("[data-cart-close]");
    if (close) close.focus();
  }
  function closeCart() {
    const panel = drawer();
    if (!panel) return;
    panel.hidden = true;
    panel.setAttribute("aria-hidden", "true");
    const overlay = document.querySelector("[data-cart-overlay]");
    if (overlay) overlay.hidden = true;
    document.body.classList.remove("cart-is-open");
    const trigger = document.querySelector("[data-cart-open]");
    if (trigger) { trigger.setAttribute("aria-expanded", "false"); trigger.focus(); }
  }
  function addToCart(button) {
    const card = button.closest("[data-product-card]");
    if (!card) return;
    const id = String(card.dataset.productId);
    const cart = readCart();
    const found = cart.find(item => item.id === id);
    if (found) found.quantity += 1;
    else {
      const image = card.querySelector(".product-photo img");
      cart.push({
        id,
        name: card.dataset.productName,
        price: Number(card.dataset.productPrice),
        description: card.dataset.productDescription || "",
        image: image ? image.src : "",
        quantity: 1
      });
    }
    saveCart(cart);
    const original = button.textContent;
    button.textContent = "Added to cart ✓";
    button.classList.add("is-added");
    window.setTimeout(() => {
      button.textContent = original;
      button.classList.remove("is-added");
    }, 1100);
  }
  function renderCart() {
    const root = document.getElementById("cart-items");
    if (!root) return;
    const cart = readCart();
    const empty = document.getElementById("cart-empty");
    const summary = document.getElementById("cart-summary");
    root.replaceChildren();
    if (!cart.length) {
      empty.hidden = false;
      summary.hidden = true;
      return;
    }
    empty.hidden = true;
    summary.hidden = false;
    cart.forEach(item => {
      const row = document.createElement("article");
      row.className = "cart-row";
      const image = document.createElement(item.image ? "img" : "div");
      if (item.image) { image.src = item.image; image.alt = item.name; image.loading = "lazy"; }
      else image.className = "cart-image-placeholder";
      const info = document.createElement("div");
      info.className = "cart-item-info";
      const name = document.createElement("h3");
      name.textContent = item.name;
      const price = document.createElement("p");
      price.className = "cart-item-price";
      price.textContent = money(item.price);
      const controls = document.createElement("div");
      controls.className = "cart-quantity";
      const decrease = document.createElement("button");
      decrease.type = "button"; decrease.textContent = "−"; decrease.setAttribute("aria-label", "Decrease " + item.name + " quantity");
      decrease.addEventListener("click", () => changeQuantity(item.id, -1));
      const quantity = document.createElement("span");
      quantity.textContent = item.quantity;
      const increase = document.createElement("button");
      increase.type = "button"; increase.textContent = "+"; increase.setAttribute("aria-label", "Increase " + item.name + " quantity");
      increase.addEventListener("click", () => changeQuantity(item.id, 1));
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "cart-remove"; remove.textContent = "Remove";
      remove.addEventListener("click", () => removeItem(item.id));
      controls.append(decrease, quantity, increase, remove);
      info.append(name, price, controls);
      const total = document.createElement("strong");
      total.className = "cart-line-total";
      total.textContent = money(item.price * item.quantity);
      row.append(image, info, total);
      root.appendChild(row);
    });
    document.getElementById("cart-subtotal").textContent = money(cart.reduce((sum, item) => sum + item.price * item.quantity, 0));
  }
  function changeQuantity(id, delta) {
    const cart = readCart();
    const item = cart.find(entry => entry.id === id);
    if (!item) return;
    item.quantity += delta;
    saveCart(item.quantity <= 0 ? cart.filter(entry => entry.id !== id) : cart);
  }
  function removeItem(id) { saveCart(readCart().filter(item => item.id !== id)); }
  function checkout() {
    const cart = readCart();
    const phone = (window.STORE_WHATSAPP || "").replace(/[^0-9]/g, "");
    if (!phone) { window.alert("This store has not added a WhatsApp number yet."); return; }
    if (!cart.length) return;
    const lines = cart.map(item => "- " + item.name + " × " + item.quantity + " — " + money(item.price * item.quantity));
    const total = cart.reduce((sum, item) => sum + item.price * item.quantity, 0);
    const message = "Hello " + (window.STORE_NAME || "") + ", I would like to order:\n" + lines.join("\n") + "\n\nSubtotal: " + money(total) + "\nPlease confirm availability.";
    window.open("https://wa.me/" + phone + "?text=" + encodeURIComponent(message), "_blank", "noopener");
  }
  document.addEventListener("DOMContentLoaded", () => {
    const cart = readCart();
    updateCount(cart);
    renderCart();
    document.querySelectorAll("[data-add-to-cart]").forEach(button => button.addEventListener("click", () => addToCart(button)));
    document.querySelectorAll("[data-cart-open]").forEach(button => button.addEventListener("click", openCart));
    document.querySelectorAll("[data-cart-close]").forEach(button => button.addEventListener("click", closeCart));
    const overlay = document.querySelector("[data-cart-overlay]");
    if (overlay) overlay.addEventListener("click", closeCart);
    document.addEventListener("keydown", event => { if (event.key === "Escape" && drawer() && !drawer().hidden) closeCart(); });
    const checkoutButton = document.getElementById("whatsapp-checkout");
    if (checkoutButton) checkoutButton.addEventListener("click", checkout);
  });
})();