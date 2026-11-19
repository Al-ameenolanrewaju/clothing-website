from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import update
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, logout_user
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, DecimalField, BooleanField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional, Regexp

from .. import db
from ..media import delete_image, upload_image, validate_image
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
    name = StringField("Name", validators=[DataRequired(), Length(max=180)])
    slug = StringField("Slug", validators=[DataRequired(), Length(max=200), Regexp(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")])
    description = TextAreaField("Description")
    regular_price = DecimalField(
        "Regular price",
        places=2,
        validators=[DataRequired(), NumberRange(min=0, max=Decimal("9999999999.99"))],
    )
    discounted_price = DecimalField(
        "Discounted price",
        places=2,
        validators=[Optional(), NumberRange(min=0, max=Decimal("9999999999.99"))],
    )
    category_id = SelectField("Category", coerce=int)
    gender = SelectField("Gender", choices=[("Men", "Men"), ("Women", "Women"), ("Unisex", "Unisex")])
    fashion_type = SelectField("Fashion type", choices=[("Ready-to-wear", "Ready-to-wear"), ("Modest fashion", "Modest fashion")])
    sku = StringField("SKU")
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


def _product_form_choices(form):
    form.category_id.choices = [(0, "Uncategorized")] + [
        (category.id, category.name)
        for category in Category.query.filter_by(business_id=current_user.business_id).order_by(Category.name).all()
    ]


def _save_product_images(product):
    images = [image for image in request.files.getlist("images") if image and image.filename]
    if len(images) > 8:
        flash("Upload no more than eight images at a time.", "danger")
        return
    try:
        for image in images:
            validate_image(image)
        uploaded = []
        for image in images:
            url, public_id = upload_image(image, f"clothing-catalogue/{product.business_id}/products/{product.id}")
            uploaded.append((url, public_id))
    except (ValueError, RuntimeError) as error:
        flash(str(error), "danger")
        return
    for offset, (url, public_id) in enumerate(uploaded, start=len(product.images)):
        db.session.add(ProductImage(
            business_id=product.business_id,
            product_id=product.id,
            url=url,
            cloudinary_public_id=public_id,
            alt_text=product.name,
            sort_order=offset,
        ))


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
    _product_form_choices(form)
    if form.validate_on_submit():
        slug = slugify(form.slug.data)
        if form.discounted_price.data is not None and form.discounted_price.data > form.regular_price.data:
            flash("Discounted price cannot exceed regular price.", "danger")
        elif Product.query.filter_by(business_id=current_user.business_id, slug=slug).first():
            flash("A product with that slug already exists.", "danger")
        else:
            product = Product(
                business_id=current_user.business_id,
                name=form.name.data.strip(),
                slug=slug,
                description=form.description.data,
                regular_price=form.regular_price.data,
                discounted_price=form.discounted_price.data,
                category_id=form.category_id.data or None,
                gender=form.gender.data,
                fashion_type=form.fashion_type.data,
                sku=form.sku.data,
                featured=form.featured.data,
                new_arrival=form.new_arrival.data,
                is_published=form.is_published.data,
            )
            db.session.add(product)
            db.session.commit()
            _save_product_images(product)
            db.session.commit()
            db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                                       action="PRODUCT_CREATED", details=product.name))
            db.session.commit()
            flash("Product created.", "success")
            return redirect(url_for("owner.products"))
    items = Product.query.filter_by(business_id=current_user.business_id).order_by(Product.created_at.desc()).all()
    return render_template("owner/products.html", form=form, items=items)


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@roles_required("OWNER")
def edit_product(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    form = ProductForm(obj=product)
    _product_form_choices(form)
    if form.validate_on_submit():
        slug = slugify(form.slug.data)
        collision = Product.query.filter(
            Product.business_id == current_user.business_id,
            Product.slug == slug,
            Product.id != product.id,
        ).first()
        if form.discounted_price.data is not None and form.discounted_price.data > form.regular_price.data:
            flash("Discounted price cannot exceed regular price.", "danger")
        elif collision:
            flash("A product with that slug already exists.", "danger")
        else:
            product.name = form.name.data.strip()
            product.slug = slug
            product.description = form.description.data
            product.regular_price = form.regular_price.data
            product.discounted_price = form.discounted_price.data
            product.category_id = form.category_id.data or None
            product.gender = form.gender.data
            product.fashion_type = form.fashion_type.data
            product.sku = form.sku.data
            product.featured = form.featured.data
            product.new_arrival = form.new_arrival.data
            product.is_published = form.is_published.data
            _save_product_images(product)
            db.session.commit()
            db.session.add(ActivityLog(business_id=current_user.business_id, user_id=current_user.id,
                                       action="PRODUCT_UPDATED", details=product.name))
            db.session.commit()
            flash("Product updated.", "success")
            return redirect(url_for("owner.products"))
    return render_template("owner/product_edit.html", form=form, product=product)


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




@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@roles_required("OWNER")
def delete_product(product_id):
    product = Product.query.filter_by(id=product_id, business_id=current_user.business_id).first_or_404()
    linked_orders = OrderItem.query.filter_by(product_id=product.id, business_id=current_user.business_id).first()
    if linked_orders:
        flash("This product has order history and cannot be permanently deleted. Archive it instead.", "warning")
        return redirect(url_for("owner.products"))
    for image in product.images:
        if image.cloudinary_public_id:
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
    if image.cloudinary_public_id:
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
                new_logo = upload_image(logo, f"clothing-catalogue/{business.id}/brand")
            except (ValueError, RuntimeError) as error:
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
            business.logo_url, business.logo_public_id = new_logo
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
