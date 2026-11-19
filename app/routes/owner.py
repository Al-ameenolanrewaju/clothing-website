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


,