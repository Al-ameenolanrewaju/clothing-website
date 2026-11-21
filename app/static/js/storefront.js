(function () {
  const KEY = "storefront_cart_v1";
  const money = value => new Intl.NumberFormat("en-NG", {style:"currency",currency:"NGN",maximumFractionDigits:0}).format(Number(value)||0);
  const readCart = () => { try { const value=JSON.parse(localStorage.getItem(KEY)||"[]"); return Array.isArray(value)?value:[]; } catch (_) { return []; } };
  const saveCart = cart => { localStorage.setItem(KEY,JSON.stringify(cart)); updateCount(cart); };
  const updateCount = cart => { const count=cart.reduce((sum,item)=>sum+(Number(item.quantity)||0),0); document.querySelectorAll("[data-cart-count]").forEach(el=>el.textContent=count); };
  function randomizeImages() {
    document.querySelectorAll("[data-product-card]").forEach(card=>{
      const img=card.querySelector("[data-random-product-image]");
      if(!img) return;
      let urls=[]; try { urls=JSON.parse(card.dataset.productImages||"[]"); } catch (_) {}
      if(urls.length>1) img.src=urls[Math.floor(Math.random()*urls.length)];
    });
  }
  function addToCart(button) {
    const card=button.closest("[data-product-card]"); if(!card) return;
    const id=String(card.dataset.productId);
    const img=card.querySelector("[data-random-product-image]");
    const cart=readCart(); const found=cart.find(item=>item.id===id);
    if(found) found.quantity+=1;
    else cart.push({id,name:card.dataset.productName,price:Number(card.dataset.productPrice),description:card.dataset.productDescription||"",image:img?img.src:"",quantity:1});
    saveCart(cart);
    const original=button.textContent; button.textContent="Added to bag ✓"; button.classList.add("is-added");
    window.setTimeout(()=>{button.textContent=original;button.classList.remove("is-added");},1100);
  }
  function renderCart() {
    const root=document.getElementById("cart-items"); if(!root) return;
    const cart=readCart(); const empty=document.getElementById("cart-empty"); const summary=document.getElementById("cart-summary");
    root.innerHTML="";
    if(!cart.length){empty.hidden=false;summary.hidden=true;return;}
    empty.hidden=true;summary.hidden=false;
    cart.forEach(item=>{
      const row=document.createElement("article"); row.className="cart-row";
      const image=item.image?'<img src="'+String(item.image).replace(/&/g,"&amp;").replace(/"/g,"&quot;")+'" alt="">':'<div class="cart-image-placeholder"></div>';
      row.innerHTML=image+'<div class="cart-item-info"><h2></h2><p class="cart-item-price"></p><div class="cart-quantity"><button type="button" data-decrease aria-label="Decrease quantity">−</button><span></span><button type="button" data-increase aria-label="Increase quantity">+</button><button type="button" class="cart-remove" data-remove>Remove</button></div></div><strong class="cart-line-total"></strong>';
      row.querySelector("h2").textContent=item.name; row.querySelector(".cart-item-price").textContent=money(item.price);
      row.querySelector(".cart-quantity span").textContent=item.quantity; row.querySelector(".cart-line-total").textContent=money(item.price*item.quantity);
      row.querySelector("[data-decrease]").addEventListener("click",()=>changeQuantity(item.id,-1));
      row.querySelector("[data-increase]").addEventListener("click",()=>changeQuantity(item.id,1));
      row.querySelector("[data-remove]").addEventListener("click",()=>removeItem(item.id));
      root.appendChild(row);
    });
    document.getElementById("cart-subtotal").textContent=money(cart.reduce((sum,item)=>sum+item.price*item.quantity,0));
  }
  function changeQuantity(id,delta){const cart=readCart();const item=cart.find(x=>x.id===id);if(!item)return;item.quantity+=delta;if(item.quantity<=0){saveCart(cart.filter(x=>x.id!==id));}else saveCart(cart);renderCart();}
  function removeItem(id){saveCart(readCart().filter(x=>x.id!==id));renderCart();}
  function checkout(){
    const cart=readCart(); const phone=(window.STORE_WHATSAPP||"").replace(/[^0-9]/g,"");
    if(!phone){alert("This store has not added a WhatsApp number yet.");return;}
    if(!cart.length)return;
    const lines=cart.map(item=>"- "+item.name+" × "+item.quantity+" — "+money(item.price*item.quantity));
    const total=cart.reduce((sum,item)=>sum+item.price*item.quantity,0);
    const message="Hello "+(window.STORE_NAME||"")+", I would like to order:\n"+lines.join("\n")+"\n\nSubtotal: "+money(total)+"\nPlease confirm availability.";
    window.open("https://wa.me/"+phone+"?text="+encodeURIComponent(message),"_blank","noopener");
  }
  document.addEventListener("DOMContentLoaded",()=>{
    randomizeImages(); const cart=readCart(); updateCount(cart); renderCart();
    document.querySelectorAll("[data-add-to-cart]").forEach(button=>button.addEventListener("click",()=>addToCart(button)));
    const checkoutButton=document.getElementById("whatsapp-checkout"); if(checkoutButton)checkoutButton.addEventListener("click",checkout);
  });
})();