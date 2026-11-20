from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import update
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, logout_user
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, DecimalField, BooleanField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, Regexp

from .. import db
from ..media import delete_image, read_image
from ..models import ActivityLog, Business, Category, Customer, Domain, Order, OrderItem, PasswordResetToken, Product, ProductImage, ProductVariant, StoreEvent, StoreSettings, StoreVisit
from ..security import roles_required
from ..utils import slugify


bp = Blueprint("owner", __name__, url_prefix="/dashboard")


class CategoryForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    slug = StringField("Slug", validators=[DataRequired(), Length(max=140), Regexp(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")])
    gender = SelectField("Gender", choices=[("Men", "Men"), ("Women", "Women"), ("Unisex", "Unisex")])
    submit = SubmitField("Save category")


class ProductForm(FlaskForm):
    name = StringField("Product name", validators=[DataRequired(), Length(max=180)])
    slug = StringField("Slug", validators=[Optional(), Length(max=200), Regexp(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")])
    regular_price = DecimalField(
        "Price",
        places=2,
        validators=[DataRequired(), NumberRange(min=0, max=Decimal("9999999999.99"))],
    )
    discounted_price = DecimalField(
        "Discounted price",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=Decimal("9999999999.99"))],
    )
    category_id = StringField("Category")
    gender = SelectField("Gender", choices=[("Men", "Men"), ("Women", "Women"), ("Unisex", "Unisex")])
    fashion_type = StringField("Fashion type", validators=[Optional(), Length(max=30)])
    sku = StringField("SKU", validators=[Optional(), Length(max=100)])
    description = TextAreaField("Description")
    sizes = StringField("Available sizes")
    colours = StringField("Available colours")
    featured = BooleanField("Featured")
    new_arrival = BooleanField("New arrival")
    is_published = BooleanField("Published")
    submit = SubmitField("Save product")

class StoreSettingsForm(FlaskForm):
    name = StringField("Business name", validators=[DataRequired(), Length(max=160)])
    description = TextAreaField("Business description")
    phone = StringField("Business phone", validators=[Optional(), Regexp(r"^\+?[0-9][0-9\s().-]{5,38}$")])
    contact_email = StringField("Contact email", validators=[Optional(), Email(), Length(max=255)])
    address = TextAreaField("Business address")
    whatsapp_number = StringField(
        "WhatsApp number",
        validators=[Optional(), Regexp(r"^\+?[0-9][0-9\s().-]{5,38}$")],
    )
    brand_color = StringField("Brand colour", validators=[Regexp(r"^#[0-9a-fA-F]{6}$")])
    announcement = StringField("Announcement bar", validators=[Length(max=255)])
    hero_title = StringField("Hero headline", validators=[Length(max=180)])
    about_text = TextAreaField("About the brand")
    submit = SubmitField("Save store information")


class PasswordChangeForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired(), Length(max=128)])
    new_password = PasswordField("New password", validators=[DataRequired(), Length(min=12, max=128)])
    confirm_password = PasswordField("Confirm new password", validators=[DataRequired(), EqualTo("new_password")])
    submit = SubmitField("Change password")


def _split_options(value):
    return list(dict.fromkeys(
        item.strip() for item in (value or "").replace("\n", ",").split(",")
        if item.strip()
    ))


def _sync_product_variants(product, sizes, colours):
    kept = set()
    for size in sizes:
        for colour in colours:
            kept.add((size, colour))
            existing = ProductVariant.query.filter_by(
                business_id=product.business_id,
                product_id=product.id,
                size=size,
                colour=colour,
            ).first()
            if not existing:
                db.session.add(ProductVariant(
                    business_id=product.business_id,
                    product_id=product.id,
                    size=size,
                    colour=colour,
                    stock_quantity=1,
                    is_available=True,
                ))
    for variant in list(product.variants):
        if (variant.size, variant.colour) not in kept:
            db.session.delete(variant)

def _save_product_images(product):
    images = [image for image in request.files.getlist("images") if image and image.filename]
    if len(images) > 8:
        raise ValueError("Upload no more than eight images at a time.")
    # Validate/read all files before adding rows so a bad later file cannot
    # leave a partially uploaded product gallery.
    uploaded = [read_image(image) for image in images]
    for offset, (image_data, mime_type, filename) in enumerate(uploaded, start=len(product.images)):
        image = ProductImage(
            business_id=product.business_id,
            product_id=product.id,
            url="",
            image_data=image_data,
            mime_type=mime_type,
            original_filename=filename,
            alt_text=product.name,
            sort_order=offset,
        )
        db.session.add(image)
        db.session.flush()
        image.url = url_for("product_image", image_id=image.id)


@bp.route("/")
@roles_required("OWNER")
def dashboard():
    business_id = current_user.business_id
    business = Business.query.filter_by(id=business_id, status="ACTIVE").first_or_404()
    stats = {
        "products": Product.query.filter_by(business_id=business_id).count(),
        "published": Product.query.filter_by(business_id=business_id, is_published=True).count(),
        "categories": Category.query.filter_by(business_id=business_id).count(),
        "out_of_stock": ProductVariant.query.filter(
            ProductVariant.business_id == business_id,
            db.or_(ProductVariant.is_available.is_(False), ProductVariant.stock_quantity <= 0),
        ).count(),
    }
    recent_products = Product.query.filter_by(business_id=business_id).order_by(
        Product.updated_at.desc()
    ).limit(6).all()
    return render_template(
        "owner/dashboard.html",
        business=business,
        stats=stats,
        recent_products=recent_products,
    )


@bp.route("/products", methods=["GET", "POST"])
@roles_required("OWNER")
def products():
    form = ProductForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        base_slug = slugify(form.slug.data or name) or "product"
        slug = base_slug
        suffix = 2
        while Product.query.filter_by(business_id=current_user.business_id, slug=slug).first():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        if form.discounted_price.data is not None and form.discounted_price.data > form.regular_price.data:
            flash("Discounted price cannot exceed regular price.", "danger")
            items = Product.query.filter_by(business_id=current_user.business_id).order_by(Product.created_at.desc()).all()
            categories = Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name).all()
            return render_template("owner/products.html", form=form, items=items, categories=categories), 200
        category_id = None
        try:
            parsed_category_id = int(form.category_id.data or 0)
            if parsed_category_id > 0:
                category = Category.query.filter_by(id=parsed_category_id, business_id=current_user.business_id).first()
                category_id = category.id if category else None
        except (TypeError, ValueError):
            category_id = None
        product = Product(
            business_id=current_user.business_id,
            category_id=category_id,
            name=name,
            slug=slug,
            description=form.description.data,
            regular_price=form.regular_price.data,
            discounted_price=form.discounted_price.data,
            gender=form.gender.data or "Unisex",
            fashion_type=form.fashion_type.data or "Ready-to-wear",
            sku=form.sku.data or None,
            is_published=True if "is_published" not in request.form or form.is_published.data else False,
            featured=form.featured.data,
            new_arrival=form.new_arrival.data if form.new_arrival.data is not None else True,
        )
        db.session.add(product)
        db.session.flush()
        try:
            _save_product_images(product)
            _sync_product_variants(
                product,
                _split_options(form.sizes.data),
                _split_options(form.colours.data),
            )
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
            return redirect(url_for("owner.products"))
        db.session.commit()
        db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                                   action="PRODUCT_CREATED", details=product.name))
        db.session.commit()
        flash("Product created.", "success")
        return redirect(url_for("owner.products"))
    items = Product.query.filter_by(business_id=current_user.business_id).order_by(Product.created_at.desc()).all()
    categories = Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name).all()
    return render_template("owner/products.html", form=form, items=items, categories=categories)

@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@roles_required("OWNER")
def edit_product(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    form = ProductForm(obj=product)
    if request.method == "GET":
        form.category_id.data = str(product.category_id or "")
        form.slug.data = product.slug
        form.featured.data = bool(product.featured)
        form.new_arrival.data = bool(product.new_arrival)
        form.is_published.data = bool(product.is_published)
        form.sizes.data = ", ".join(dict.fromkeys(v.size for v in product.variants))
        form.colours.data = ", ".join(dict.fromkeys(v.colour for v in product.variants))
    if form.validate_on_submit():
        if form.discounted_price.data is not None and form.discounted_price.data > form.regular_price.data:
            flash("Discounted price cannot exceed regular price.", "danger")
            return render_template("owner/product_edit.html", form=form, product=product), 200
        product.name = form.name.data.strip()
        new_slug = slugify(form.slug.data or product.name)
        if new_slug:
            collision = Product.query.filter(
                Product.business_id == current_user.business_id,
                Product.slug == new_slug,
                Product.id != product.id,
            ).first()
            if collision:
                flash("A product with that slug already exists.", "danger")
                return render_template("owner/product_edit.html", form=form, product=product), 200
            product.slug = new_slug
        product.description = form.description.data
        product.regular_price = form.regular_price.data
        product.discounted_price = form.discounted_price.data
        product.gender = form.gender.data or "Unisex"
        product.fashion_type = form.fashion_type.data or "Ready-to-wear"
        product.sku = form.sku.data or None
        product.featured = form.featured.data
        product.new_arrival = form.new_arrival.data
        product.is_published = form.is_published.data
        try:
            parsed_category_id = int(form.category_id.data or 0)
            product.category_id = parsed_category_id if parsed_category_id > 0 and Category.query.filter_by(
                id=parsed_category_id,
                business_id=current_user.business_id,
            ).first() else None
        except (TypeError, ValueError):
            product.category_id = None
        try:
            _save_product_images(product)
            _sync_product_variants(
                product,
                _split_options(form.sizes.data),
                _split_options(form.colours.data),
            )
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
            return redirect(url_for("owner.edit_product", product_id=product.id))
        db.session.commit()
        db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                                   action="PRODUCT_UPDATED", details=product.name))
        db.session.commit()
        flash("Product updated.", "success")
        return redirect(url_for("owner.products"))
    categories = Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name).all()
    return render_template("owner/product_edit.html", form=form, product=product, categories=categories)

@bp.route("/products/<int:product_id>/archive", methods=["POST"])
@roles_required("OWNER")
def archive_product(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    product.is_published = False
    db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                               action="PRODUCT_ARCHIVED", details=product.name))
    db.session.commit()
    flash("Product archived and removed from the storefront.", "success")
    return redirect(url_for("owner.products"))




@bp.route("/products/<int:product_id>/publish", methods=["POST"])
@roles_required("OWNER")
def publish_product(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    product.is_published = True
    db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                               action="PRODUCT_PUBLISHED", details=product.name))
    db.session.commit()
    flash("Product published on the storefront.", "success")
    return redirect(url_for("owner.products"))


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@roles_required("OWNER")
def delete_product(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    linked_variant_ids = db.session.query(ProductVariant.id).filter_by(
        product_id=product.id, business_id=current_user.business_id
    )
    linked_orders = OrderItem.query.filter(
        OrderItem.business_id == current_user.business_id,
        db.or_(
            OrderItem.product_id == product.id,
            OrderItem.variant_id.in_(linked_variant_ids),
        ),
    ).first()
    if linked_orders:
        flash("This product has order history and cannot be permanently deleted. Archive it instead.", "warning")
        return redirect(url_for("owner.products"))
    for image in product.images:
        if image.cloudinary_public_id and not image.image_data:
            try:
                delete_image(image.cloudinary_public_id)
            except RuntimeError as error:
                flash(f"Product was not deleted because an image could not be removed: {error}", "danger")
                return redirect(url_for("owner.products"))
    name = product.name
    db.session.delete(product)
    db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                               action="PRODUCT_DELETED", details=name))
    db.session.commit()
    flash("Product permanently deleted.", "success")
    return redirect(url_for("owner.products"))


@bp.route("/products/<int:product_id>/images/<int:image_id>/delete", methods=["POST"])
@roles_required("OWNER")
def delete_product_image(product_id, image_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    image = ProductImage.query.filter_by(
        id=image_id,
        product_id=product.id,
        business_id=current_user.business_id,
    ).first_or_404()
    if image.cloudinary_public_id and not image.image_data:
        try:
            delete_image(image.cloudinary_public_id)
        except RuntimeError as error:
            flash(str(error), "danger")
            return redirect(url_for("owner.edit_product", product_id=product.id))
    db.session.delete(image)
    db.session.commit()
    flash("Product image deleted.", "success")
    return redirect(url_for("owner.edit_product", product_id=product.id))


@bp.route("/categories", methods=["GET", "POST"])
@roles_required("OWNER")
def categories():
    form = CategoryForm()
    if form.validate_on_submit():
        slug = slugify(form.slug.data)
        if Category.query.filter_by(business_id=current_user.business_id, slug=slug).first():
            flash("A category with that slug already exists.", "danger")
        else:
            db.session.add(Category(
                business_id=current_user.business_id,
                name=form.name.data.strip(),
                slug=slug,
                gender=form.gender.data,
            ))
            db.session.commit()
            flash("Category created.", "success")
            return redirect(url_for("owner.categories"))
    items = Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name).all()
    return render_template("owner/categories.html", form=form, items=items)


@bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@roles_required("OWNER")
def edit_category(category_id):
    category = Category.query.filter_by(id=category_id, business_id=current_user.business_id).first_or_404()
    form = CategoryForm(obj=category)
    if form.validate_on_submit():
        slug = slugify(form.slug.data)
        collision = Category.query.filter(
            Category.business_id == current_user.business_id,
            Category.slug == slug,
            Category.id != category.id,
        ).first()
        if collision:
            flash("A category with that slug already exists.", "danger")
        else:
            category.name = form.name.data.strip()
            category.slug = slug
            category.gender = form.gender.data
            db.session.commit()
            flash("Category updated.", "success")
            return redirect(url_for("owner.categories"))
    return render_template("owner/category_edit.html", form=form, category=category)


@bp.route("/categories/<int:category_id>/delete", methods=["POST"])
@roles_required("OWNER")
def delete_category(category_id):
    category = Category.query.filter_by(id=category_id, business_id=current_user.business_id).first_or_404()
    if Product.query.filter_by(category_id=category.id, business_id=current_user.business_id).first():
        flash("Move or uncategorize this category's products before deleting it.", "danger")
    else:
        db.session.delete(category)
        db.session.commit()
        flash("Category deleted.", "success")
    return redirect(url_for("owner.categories"))


@bp.route("/orders")
@roles_required("OWNER")
def orders():
    status = request.args.get("status")
    allowed_statuses = [
        "WHATSAPP_CHECKOUT_INITIATED", "PENDING", "CONFIRMED", "PROCESSING",
        "READY_FOR_DELIVERY", "COMPLETED", "CANCELLED",
    ]
    if status and status not in allowed_statuses:
        abort(400)
    query = Order.query.filter_by(business_id=current_user.business_id).join(Customer)
    search = request.args.get("q", "").strip()
    if search:
        query = query.filter(db.or_(
            Order.reference.ilike(f"%{search}%"),
            Customer.name.ilike(f"%{search}%"),
            Customer.phone.ilike(f"%{search}%"),
        ))
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    if date_from:
        try:
            query = query.filter(Order.created_at >= datetime.combine(date.fromisoformat(date_from), time.min))
        except ValueError:
            abort(400)
    if date_to:
        try:
            query = query.filter(Order.created_at < datetime.combine(date.fromisoformat(date_to) + timedelta(days=1), time.min))
        except ValueError:
            abort(400)
    if status:
        query = query.filter(Order.status == status)
    items = query.order_by(Order.created_at.desc()).all()
    return render_template("owner/orders.html", items=items, status=status, search=search,
                           date_from=date_from, date_to=date_to, statuses=allowed_statuses)


@bp.route("/orders/<int:order_id>", methods=["GET", "POST"])
@roles_required("OWNER")
def order_detail(order_id):
    order = Order.query.filter_by(id=order_id, business_id=current_user.business_id).first_or_404()
    if request.method == "POST":
        status = request.form.get("status")
        valid_statuses = {"PENDING", "CONFIRMED", "PROCESSING", "READY_FOR_DELIVERY", "COMPLETED", "CANCELLED"}
        notes = request.form.get("internal_notes", "").strip()
        if status not in valid_statuses or len(notes) > 5000:
            abort(400)
        if order.status == "CANCELLED" and status != "CANCELLED":
            abort(400)
        if status == "CANCELLED" and order.status != "CANCELLED":
            for item in order.items:
                if item.variant_id:
                    variant = ProductVariant.query.filter_by(
                        id=item.variant_id,
                        business_id=current_user.business_id,
                    ).with_for_update().first()
                    if variant:
                        variant.stock_quantity += item.quantity
                        variant.is_available = True
        order.status = status
        order.internal_notes = notes or None
        db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                                   action="ORDER_UPDATED", details=f"{order.reference}: {status}"))
        db.session.commit()
        flash("Order updated. WhatsApp checkout initiation is not a confirmed order.", "success")
        return redirect(url_for("owner.order_detail", order_id=order.id))
    statuses = ["PENDING", "CONFIRMED", "PROCESSING", "READY_FOR_DELIVERY", "COMPLETED", "CANCELLED"]
    return render_template("owner/order_detail.html", order=order, statuses=statuses)


@bp.route("/customers")
@roles_required("OWNER")
def customers():
    search = request.args.get("q", "").strip()
    query = Customer.query.filter_by(business_id=current_user.business_id)
    if search:
        query = query.filter(db.or_(
            Customer.name.ilike(f"%{search}%"),
            Customer.phone.ilike(f"%{search}%"),
        ))
    items = query.order_by(Customer.created_at.desc()).all()
    return render_template("owner/customers.html", items=items, search=search)


@bp.route("/products/<int:product_id>/variants", methods=["GET", "POST"])
@roles_required("OWNER")
def variants(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    if request.method == "POST":
        size = request.form.get("size", "").strip()
        colour = request.form.get("colour", "").strip()
        try:
            stock = int(request.form.get("stock", "0"))
            price_text = request.form.get("price_override", "").strip()
            price_override = Decimal(price_text) if price_text else None
        except (ValueError, InvalidOperation):
            abort(400)
        sku = request.form.get("sku", "").strip()
        if (not size or len(size) > 50 or not colour or len(colour) > 50
                or stock < 0 or stock > 1000000 or len(sku) > 100
                or (price_override is not None and (
                    not price_override.is_finite()
                    or price_override < 0
                    or price_override > Decimal("9999999999.99")
                ))):
            abort(400)
        existing = ProductVariant.query.filter_by(
            product_id=product.id,
            size=size,
            colour=colour,
        ).first()
        available = request.form.get("available") == "on" and stock > 0
        if existing:
            existing.sku = sku or None
            existing.price_override = price_override
            existing.stock_quantity = stock
            existing.is_available = available
        else:
            db.session.add(ProductVariant(
                business_id=current_user.business_id,
                product_id=product.id,
                size=size,
                colour=colour,
                sku=sku or None,
                price_override=price_override,
                stock_quantity=stock,
                is_available=available,
            ))
        db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                                   action="INVENTORY_UPDATED", details=f"{product.name}: {size}/{colour}"))
        db.session.commit()
        flash("Variant saved.", "success")
        return redirect(url_for("owner.variants", product_id=product.id))
    return render_template("owner/variants.html", product=product)




@bp.route("/products/<int:product_id>/variants/<int:variant_id>/delete", methods=["POST"])
@roles_required("OWNER")
def delete_variant(product_id, variant_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    variant = ProductVariant.query.filter_by(id=variant_id, product_id=product.id, business_id=current_user.business_id).first_or_404()
    if OrderItem.query.filter_by(variant_id=variant.id, business_id=current_user.business_id).first():
        flash("This variant appears in order history. Set its stock to zero and mark it unavailable instead.", "warning")
    else:
        label = f"{product.name}: {variant.size}/{variant.colour}"
        db.session.delete(variant)
        db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                                   action="VARIANT_DELETED", details=label))
        db.session.commit()
        flash("Variant deleted.", "success")
    return redirect(url_for("owner.variants", product_id=product.id))


@bp.route("/settings", methods=["GET", "POST"])
@roles_required("OWNER")
def settings():
    business = Business.query.filter_by(id=current_user.business_id).first_or_404()
    store_settings = StoreSettings.query.filter_by(business_id=business.id).first()
    if store_settings is None:
        store_settings = StoreSettings(business_id=business.id)
        db.session.add(store_settings)
        db.session.commit()
    form = StoreSettingsForm()
    if request.method == "GET":
        form.name.data = business.name
        form.description.data = business.description
        form.phone.data = business.phone
        form.contact_email.data = business.contact_email
        form.address.data = business.address
        form.whatsapp_number.data = business.whatsapp_number
        form.brand_color.data = business.brand_color
        form.announcement.data = store_settings.announcement
        form.hero_title.data = store_settings.hero_title
        form.about_text.data = store_settings.about_text
    if form.validate_on_submit():
        logo = request.files.get("logo")
        new_logo = None
        if logo and logo.filename:
            try:
                new_logo = read_image(logo)
            except ValueError as error:
                flash(str(error), "danger")
                return render_template("owner/settings.html", form=form, business=business, domains=business.domains)
        old_logo_id = business.logo_public_id
        business.name = form.name.data.strip()
        business.description = form.description.data.strip() or None
        business.phone = form.phone.data.strip() or None
        business.contact_email = form.contact_email.data.strip().lower() or None
        business.address = form.address.data.strip() or None
        business.whatsapp_number = form.whatsapp_number.data.strip() or None
        business.brand_color = form.brand_color.data
        store_settings.announcement = form.announcement.data.strip() or None
        store_settings.hero_title = form.hero_title.data.strip() or None
        store_settings.about_text = form.about_text.data.strip() or None
        if new_logo:
            business.logo_data, business.logo_mime_type, _filename = new_logo
            business.logo_url = url_for("business_logo", business_id=business.id)
            business.logo_public_id = None
        db.session.add(ActivityLog(business_id=business.id, user_id=current_user.id,
                                   action="STORE_SETTINGS_UPDATED", details=business.name))
        db.session.commit()
        if new_logo and old_logo_id:
            try:
                delete_image(old_logo_id)
            except RuntimeError as error:
                flash(f"Store information saved, but the previous logo could not be removed: {error}", "warning")
        flash("Store information updated.", "success")
        return redirect(url_for("owner.settings"))
    return render_template("owner/settings.html", form=form, business=business, domains=business.domains)


@bp.route("/account/password", methods=["GET", "POST"])
@roles_required("OWNER")
def change_password():
    form = PasswordChangeForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash("The current password is incorrect.", "danger")
        else:
            current_user.set_password(form.new_password.data)
            db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                                       action="PASSWORD_CHANGED"))
            db.session.commit()
            logout_user()
            flash("Password changed. Sign in with your new password.", "success")
            return redirect(url_for("auth.login"))
    return render_template("owner/change_password.html", form=form)


@bp.route("/domains")
@roles_required("OWNER")
def domain_status():
    domains = Domain.query.filter_by(business_id=current_user.business_id).order_by(Domain.is_primary.desc()).all()
    return render_template("owner/domains.html", domains=domains)
