from decimal import Decimal
import re
from urllib.parse import quote
from uuid import uuid4

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import update

from .. import db
from ..models import Business, Category, Customer, Order, OrderItem, Product, ProductVariant, StoreEvent, StoreSettings, StoreVisit


bp = Blueprint("storefront", __name__)


def public_business():
    business = getattr(g, "business", None)
    if business is None:
        abort(404)
    return business


def cart_lines(business):
    lines = []
    cart = session.get("cart", {})
    for key, quantity in cart.items():
        variant_id = int(key.split(":", 1)[0])
        variant = ProductVariant.query.filter_by(
            id=variant_id,
            business_id=business.id,
            is_available=True,
        ).first()
        if not variant:
            continue
        quantity = int(quantity)
        product = Product.query.filter_by(id=variant.product_id, business_id=business.id, is_published=True).first()
        if not product:
            continue
        unit_price = variant.price_override or product.price
        lines.append({
            "variant": variant,
            "product": product,
            "quantity": quantity,
            "unit_price": Decimal(unit_price),
            "line_total": Decimal(unit_price) * quantity,
            "available": variant.is_available and quantity > 0 and quantity <= variant.stock_quantity,
        })
    return lines


@bp.before_app_request
def track_store_visit():
    if request.endpoint and request.endpoint.startswith("storefront.") and request.method == "GET":
        business = getattr(g, "business", None)
        if business:
            db.session.add(StoreVisit(business_id=business.id, path=request.path))
            db.session.commit()


@bp.route("/")
def home():
    business = public_business()
    products = Product.query.filter_by(
        business_id=business.id,
        is_published=True,
    ).order_by(Product.created_at.desc()).limit(12).all()
    featured = [p for p in products if p.featured][:8]
    new_arrivals = Product.query.filter_by(
        business_id=business.id, is_published=True, new_arrival=True
    ).order_by(Product.created_at.desc()).limit(8).all()
    men_products = Product.query.filter_by(
        business_id=business.id, is_published=True, gender="Men"
    ).order_by(Product.created_at.desc()).limit(4).all()
    women_products = Product.query.filter_by(
        business_id=business.id, is_published=True, gender="Women"
    ).order_by(Product.created_at.desc()).limit(4).all()
    best_sellers = Product.query.join(OrderItem, OrderItem.product_id == Product.id).join(
        Order, Order.id == OrderItem.order_id
    ).filter(
        Product.business_id == business.id,
        Product.is_published.is_(True),
        Order.business_id == business.id,
        Order.status.in_(["CONFIRMED", "PROCESSING", "READY_FOR_DELIVERY", "COMPLETED"]),
    ).group_by(Product.id).order_by(db.func.sum(OrderItem.quantity).desc()).limit(4).all()
    settings = StoreSettings.query.filter_by(business_id=business.id).first()
    return render_template("storefront/home.html", business=business, products=products,
                           featured=featured or products[:8], new_arrivals=new_arrivals,
                           men_products=men_products, women_products=women_products,
                           best_sellers=best_sellers, settings=settings)


@bp.route("/catalogue")
def catalogue():
    business = public_business()
    query = Product.query.filter_by(business_id=business.id, is_published=True)
    gender = request.args.get("gender")
    category_id = request.args.get("category", type=int)
    search = request.args.get("q", "").strip()
    size = request.args.get("size", "").strip()
    colour = request.args.get("colour", "").strip()
    availability = request.args.get("availability") == "available"
    sort = request.args.get("sort", "newest")
    if gender:
        query = query.filter_by(gender=gender)
    if category_id:
        query = query.filter_by(category_id=category_id)
    if search:
        query = query.filter(db.or_(Product.name.ilike(f"%{search}%"),
                                    Product.description.ilike(f"%{search}%")))
    if size or colour or availability:
        query = query.join(ProductVariant)
        query = query.filter(ProductVariant.is_available.is_(True), ProductVariant.stock_quantity > 0)
        if size:
            query = query.filter(ProductVariant.size == size)
        if colour:
            query = query.filter(ProductVariant.colour == colour)
    if sort == "price-low":
        query = query.order_by(db.func.coalesce(Product.discounted_price, Product.regular_price).asc())
    elif sort == "price-high":
        query = query.order_by(db.func.coalesce(Product.discounted_price, Product.regular_price).desc())
    else:
        query = query.order_by(Product.created_at.desc())
    query = query.distinct()
    page = max(request.args.get("page", 1, type=int), 1)
    products = query.paginate(page=page, per_page=12, error_out=False)
    categories = Category.query.filter_by(business_id=business.id).order_by(Category.name).all()
    variants = ProductVariant.query.filter_by(business_id=business.id, is_available=True).filter(
        ProductVariant.stock_quantity > 0
    ).join(Product).filter(Product.is_published.is_(True))
    sizes = [row[0] for row in variants.with_entities(ProductVariant.size).distinct().order_by(ProductVariant.size)]
    colours = [row[0] for row in variants.with_entities(ProductVariant.colour).distinct().order_by(ProductVariant.colour)]
    return render_template("storefront/catalogue.html", business=business, products=products,
                           categories=categories, sizes=sizes, colours=colours)


@bp.route("/product/<slug>")
def product_detail(slug):
    business = public_business()
    product = Product.query.filter_by(
        business_id=business.id,
        slug=slug,
        is_published=True,
    ).first_or_404()
    related = Product.query.filter(
        Product.business_id == business.id,
        Product.is_published.is_(True),
        Product.id != product.id,
        db.or_(Product.category_id == product.category_id, Product.gender == product.gender),
    ).limit(4).all()
    sizes = sorted(set(v.size for v in product.variants))
    colours = sorted(set(v.colour for v in product.variants))
    variants = [{
        "id": v.id,
        "size": v.size,
        "colour": v.colour,
        "is_available": v.is_available,
        "stock_quantity": v.stock_quantity,
        "price": str(v.price_override or product.price),
    } for v in product.variants]
    db.session.add(StoreEvent(business_id=business.id, product_id=product.id, event_type="PRODUCT_VIEW"))
    db.session.commit()
    settings = StoreSettings.query.filter_by(business_id=business.id).first()
    return render_template("storefront/product_detail.html", business=business, product=product,
                           related=related, sizes=sizes, colours=colours, variants=variants, settings=settings)


@bp.route("/cart")
def cart():
    business = public_business()
    lines = cart_lines(business)
    total = sum((line["line_total"] for line in lines), Decimal("0"))
    invalid_lines = any(not line["available"] for line in lines)
    return render_template("storefront/cart.html", business=business, lines=lines, total=total,
                           invalid_lines=invalid_lines)


@bp.route("/cart/add", methods=["POST"])
def cart_add():
    business = public_business()
    variant_id = request.form.get("variant_id", type=int)
    quantity = request.form.get("quantity", type=int)
    product_id = request.form.get("product_id", type=int)
    size = request.form.get("size", "")
    colour = request.form.get("colour", "")
    product = Product.query.filter_by(
        id=product_id,
        business_id=business.id,
        is_published=True,
    ).first_or_404()
    if quantity is None or quantity < 1 or quantity > 100 or not size or not colour:
        flash("Select an available size and colour and enter a valid quantity.", "danger")
        return redirect(url_for("storefront.product_detail", slug=product.slug))
    variant_query = ProductVariant.query.filter_by(
        product_id=product_id,
        business_id=business.id,
        size=size,
        colour=colour,
        is_available=True,
    )
    if variant_id:
        variant_query = variant_query.filter_by(id=variant_id)
    variant = variant_query.first()
    if (not variant
            or variant.stock_quantity < quantity):
        flash("The selected size and colour are unavailable.", "danger")
        return redirect(url_for("storefront.product_detail", slug=product.slug))
    key = f"{variant.id}:"
    cart = session.setdefault("cart", {})
    desired_quantity = int(cart.get(key, 0)) + quantity
    if desired_quantity > min(variant.stock_quantity, 100):
        flash("There is not enough stock to add that quantity.", "danger")
        return redirect(url_for("storefront.product_detail", slug=product.slug))
    cart[key] = desired_quantity
    session.modified = True
    return redirect(url_for("storefront.cart"))


@bp.route("/cart/update", methods=["POST"])
def cart_update():
    business = public_business()
    cart = session.get("cart", {})
    for key in list(cart):
        variant_id = int(key.split(":", 1)[0])
        quantity = request.form.get(f"quantity_{variant_id}", type=int)
        variant = ProductVariant.query.filter_by(id=variant_id, business_id=business.id).first()
        if quantity is not None and variant:
            if quantity <= 0:
                cart.pop(key, None)
            elif quantity <= 100 and quantity <= variant.stock_quantity and variant.is_available:
                cart[key] = quantity
    session.modified = True
    return redirect(url_for("storefront.cart"))


@bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    business = public_business()
    lines = cart_lines(business)
    if not lines:
        return redirect(url_for("storefront.cart"))
    total = sum((line["line_total"] for line in lines), Decimal("0"))
    if any(not line["available"] for line in lines):
        return render_template("storefront/checkout.html", business=business, lines=lines,
                               total=total, error="Cart contents changed; update or remove unavailable items.")
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        instructions = request.form.get("instructions", "").strip()
        if (not name or len(name) > 160 or not re.fullmatch(r"\+?[0-9][0-9\s().-]{5,38}", phone)
                or not address or len(address) > 2000 or len(instructions) > 1000):
            return render_template("storefront/checkout.html", business=business, lines=lines,
                                   total=total, error="Enter a valid name, phone number and delivery address.")
        if not business.whatsapp_number:
            return render_template("storefront/checkout.html", business=business, lines=lines,
                                   total=total, error="This store has not configured WhatsApp ordering yet.")

        for line in lines:
            variant = ProductVariant.query.filter_by(
                id=line["variant"].id,
                business_id=business.id,
            ).with_for_update().populate_existing().first()
            if not variant or line["quantity"] > variant.stock_quantity or not variant.is_available:
                return render_template("storefront/checkout.html", business=business, lines=lines,
                                       total=total, error="Cart contents changed and exceed available stock.")
            line["variant"] = variant
            product = Product.query.filter_by(
                id=variant.product_id,
                business_id=business.id,
                is_published=True,
            ).first()
            if not product:
                return render_template("storefront/checkout.html", business=business, lines=lines,
                                       total=total, error="A product in your cart is no longer available.")
            line["product"] = product
            line["unit_price"] = Decimal(variant.price_override or product.price)
            line["line_total"] = line["unit_price"] * line["quantity"]

        total = sum((line["line_total"] for line in lines), Decimal("0"))

        customer = Customer(
            business_id=business.id,
            name=name,
            phone=phone,
            address=address,
        )
        db.session.add(customer)
        db.session.flush()
        order = Order(
            business_id=business.id,
            customer_id=customer.id,
            reference=f"CS-{uuid4().hex[:10].upper()}",
            status="WHATSAPP_CHECKOUT_INITIATED",
            subtotal=total,
            total=total,
            delivery_address=address,
            delivery_instructions=instructions,
        )
        db.session.add(order)
        db.session.flush()
        message_lines = [
            f"Hello {business.name}",
            f"Order reference: {order.reference}",
            "",
        ]
        for line in lines:
            unit = line["unit_price"]
            line_total = line["line_total"]
            message_lines.append(
                f"{line['product'].name} - Size: {line['variant'].size}, Colour: {line['variant'].colour}, "
                f"Qty: {line['quantity']} x {unit} = {line_total}"
            )
            db.session.add(OrderItem(
                business_id=business.id,
                order_id=order.id,
                product_id=line["product"].id,
                variant_id=line["variant"].id,
                product_name=line["product"].name,
                size=line["variant"].size,
                colour=line["variant"].colour,
                quantity=line["quantity"],
                unit_price=unit,
                line_total=line_total,
            ))
            result = db.session.execute(update(ProductVariant).where(
                ProductVariant.id == line["variant"].id,
                ProductVariant.business_id == business.id,
                ProductVariant.is_available.is_(True),
                ProductVariant.stock_quantity >= line["quantity"],
            ).values(stock_quantity=ProductVariant.stock_quantity - line["quantity"]))
            if result.rowcount != 1:
                db.session.rollback()
                return render_template("storefront/checkout.html", business=business, lines=lines,
                                       total=total, error="Stock changed during checkout. Please review your cart."), 409
        db.session.add(StoreEvent(business_id=business.id, order_id=order.id,
                                  event_type="CHECKOUT_INITIATED"))
        message_lines.extend([
            "",
            f"Order total: {total}",
            f"Customer name: {name}",
            f"Customer phone: {phone}",
            f"Delivery address: {address}",
            f"Delivery instructions: {instructions or 'None'}",
        ])
        db.session.commit()
        session.pop("cart", None)
        whatsapp_url = url_for("storefront.whatsapp_click", reference=order.reference)
        return render_template("storefront/whatsapp_redirect.html", whatsapp_url=whatsapp_url,
                               order=order, business=business)
    return render_template("storefront/checkout.html", business=business, lines=lines, total=total)


@bp.route("/order/<reference>/whatsapp")
def whatsapp_click(reference):
    business = public_business()
    order = Order.query.filter_by(
        business_id=business.id,
        reference=reference,
        status="WHATSAPP_CHECKOUT_INITIATED",
    ).first_or_404()
    number = "".join(ch for ch in (business.whatsapp_number or "") if ch.isdigit())
    if not number:
        abort(404)
    message_lines = [
        f"Hello {business.name}",
        f"Order reference: {order.reference}",
        "",
    ]
    for item in order.items:
        message_lines.append(
            f"{item.product_name} - Size: {item.size}, Colour: {item.colour}, "
            f"Qty: {item.quantity} x {item.unit_price} = {item.line_total}"
        )
    message_lines.extend([
        "",
        f"Order total: {order.total}",
        f"Customer name: {order.customer.name}",
        f"Customer phone: {order.customer.phone}",
        f"Delivery address: {order.delivery_address}",
        f"Delivery instructions: {order.delivery_instructions or 'None'}",
    ])
    db.session.add(StoreEvent(business_id=business.id, order_id=order.id,
                              event_type="WHATSAPP_CHECKOUT_CLICK"))
    db.session.commit()
    return redirect(f"https://wa.me/{number}?text={quote(chr(10).join(message_lines))}")
