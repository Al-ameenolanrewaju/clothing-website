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
    renderProductButtons(cart);
  };
  function updateCount(cart) {
    const count = cart.length;
    document.querySelectorAll("[data-cart-count]").forEach(el => { el.textContent = count; });
    document.querySelectorAll("[data-cart-drawer-count]").forEach(el => { el.textContent = "(" + count + ")"; });
  }
  function renderProductButtons(cart) {
    const ids = new Set(cart.map(item => String(item.id)));
    document.querySelectorAll("[data-product-card]").forEach(card => {
      const button = card.querySelector("[data-add-to-cart]");
      if (!button) return;
      const added = ids.has(String(card.dataset.productId));
      button.textContent = added ? "Remove from cart" : "Add to cart";
      button.classList.toggle("is-added", added);
      button.setAttribute("aria-pressed", added ? "true" : "false");
    });
  }

  function normalizeFilterValue(value) {
    return String(value || "").trim().toLocaleLowerCase().replace(/\s+/g, " ");
  }
  function applyCollectionFilters(form) {
    const grid = document.querySelector("[data-collection-products]");
    if (!grid) return;
    const categorySelect = form.querySelector("[data-filter-category]");
    const sizeSelect = form.querySelector("[data-filter-size]");
    const colourSelect = form.querySelector("[data-filter-colour]");
    const selectedCategory = categorySelect && categorySelect.selectedOptions[0]
      ? normalizeFilterValue(categorySelect.selectedOptions[0].dataset.categoryName)
      : "";
    const selectedSize = normalizeFilterValue(sizeSelect && sizeSelect.value);
    const selectedColour = normalizeFilterValue(colourSelect && colourSelect.value);
    const cards = Array.from(grid.querySelectorAll("[data-product-card]"));
    let visible = 0;
    cards.forEach(card => {
      const categoryMatch = !selectedCategory || normalizeFilterValue(card.dataset.categoryName) === selectedCategory;
      const sizes = String(card.dataset.productSizes || "").split("|").map(normalizeFilterValue);
      const colours = String(card.dataset.productColours || "").split("|").map(normalizeFilterValue);
      const sizeMatch = !selectedSize || sizes.includes(selectedSize);
      const colourMatch = !selectedColour || colours.includes(selectedColour);
      const show = categoryMatch && sizeMatch && colourMatch;
      card.hidden = !show;
      if (show) visible += 1;
    });
    const count = form.parentElement.querySelector("[data-filter-result-count]");
    if (count) count.textContent = visible + (visible === 1 ? " piece" : " pieces");
    const empty = grid.querySelector("[data-filter-empty]");
    if (empty) empty.hidden = visible !== 0;
  }
  function openCart() {
    const panel = drawer();
    if (!panel) return;
    const trigger = document.querySelector("[data-cart-open]");
    const overlay = document.querySelector("[data-cart-overlay]");
    panel.hidden = false;
    panel.setAttribute("aria-hidden", "false");
    if (overlay) overlay.hidden = false;
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
  function toggleCart(button) {
    const card = button.closest("[data-product-card]");
    if (!card) return;
    const id = String(card.dataset.productId);
    const cart = readCart();
    if (cart.some(item => String(item.id) === id)) {
      saveCart(cart.filter(item => String(item.id) !== id));
      return;
    }
    const image = card.querySelector(".product-photo img");
    cart.push({
      id,
      name: card.dataset.productName,
      price: Number(card.dataset.productPrice),
      description: card.dataset.productDescription || "",
      image: image ? image.src : "",
      quantity: 1
    });
    saveCart(cart);
  }
  function renderCart() {
    const root = document.getElementById("cart-items");
    if (!root) return;
    const cart = readCart();
    const empty = document.getElementById("cart-empty");
    const summary = document.getElementById("cart-summary");
    root.replaceChildren();
    if (!cart.length) {
      if (empty) empty.hidden = false;
      if (summary) summary.hidden = true;
      return;
    }
    if (empty) empty.hidden = true;
    if (summary) summary.hidden = false;
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
      decrease.disabled = Number(item.quantity) <= 1;
      decrease.setAttribute("aria-disabled", decrease.disabled ? "true" : "false");
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
    const subtotal = document.getElementById("cart-subtotal");
    if (subtotal) subtotal.textContent = money(cart.reduce((sum, item) => sum + item.price * item.quantity, 0));
  }
  function changeQuantity(id, delta) {
    const cart = readCart();
    const item = cart.find(entry => String(entry.id) === String(id));
    if (!item) return;
    const currentQuantity = Math.max(1, Number(item.quantity) || 1);
    item.quantity = Math.max(1, currentQuantity + delta);
    saveCart(cart);
  }
  function removeItem(id) { saveCart(readCart().filter(item => String(item.id) !== String(id))); }
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
    // Shuffle whole product cards, preserving each card's image and product data.
    document.querySelectorAll(".luxury-product-grid").forEach(grid => {
      const cards = Array.from(grid.children).filter(node => node.matches("[data-product-card]"));
      for (let i = cards.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [cards[i], cards[j]] = [cards[j], cards[i]];
      }
      cards.forEach(card => grid.appendChild(card));
    });
    updateCount(cart);
    renderCart();
    renderProductButtons(cart);
    const filterForm = document.querySelector("[data-collection-filters]");
    if (filterForm) {
      filterForm.addEventListener("change", () => applyCollectionFilters(filterForm));
      filterForm.addEventListener("reset", () => window.requestAnimationFrame(() => applyCollectionFilters(filterForm)));
      // Filtering is display-only: never submit/reload the page or touch cart state.
      filterForm.addEventListener("submit", event => event.preventDefault());
      applyCollectionFilters(filterForm);
    }
    document.addEventListener("click", event => {
      const button = event.target.closest("[data-add-to-cart]");
      if (button) { event.preventDefault(); toggleCart(button); }
    });
    document.querySelectorAll("[data-cart-open]").forEach(button => button.addEventListener("click", openCart));
    document.querySelectorAll("[data-cart-close]").forEach(button => button.addEventListener("click", closeCart));
    const overlay = document.querySelector("[data-cart-overlay]");
    if (overlay) overlay.addEventListener("click", closeCart);
    document.addEventListener("keydown", event => { if (event.key === "Escape" && drawer() && !drawer().hidden) closeCart(); });
    const checkoutButton = document.getElementById("whatsapp-checkout");
    if (checkoutButton) checkoutButton.addEventListener("click", checkout);
    window.addEventListener("storage", event => {
      if (event.key === KEY) { const latest = readCart(); updateCount(latest); renderCart(); renderProductButtons(latest); }
    });
  });
})();