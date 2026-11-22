import random

from flask import Blueprint, g, render_template, request, abort

from .. import db
from ..models import Category, Product, ProductVariant, StoreVisit, StoreSettings

bp = Blueprint("storefront", __name__)


def public_business():
    business = getattr(g, "business", None)
    if business is None:
        abort(404)
    return business


@bp.before_app_request
def track_store_visit():
    if request.endpoint and request.endpoint.startswith("storefront.") and request.method == "GET":
        business = getattr(g, "business", None)
        if business:
            db.session.add(StoreVisit(business_id=business.id, path=request.path))
            db.session.commit()


def storefront_context(business):
    settings = StoreSettings.query.filter_by(business_id=business.id).first()
    all_categories = Category.query.filter_by(business_id=business.id).order_by(Category.name, Category.id).all()
    # Old stores may contain categories with the same display name but different slugs.
    # Keep one visible filter per name without deleting or rewriting any stored records.
    categories = []
    seen_names = set()
    for category in all_categories:
        key = " ".join((category.name or "").split()).casefold()
        if key and key not in seen_names:
            categories.append(category)
            seen_names.add(key)
    return settings, categories


@bp.route("/")
def home():
    business = public_business()
    products = Product.query.filter_by(
        business_id=business.id, is_published=True
    ).order_by(Product.created_at.desc()).limit(8).all()
    random.shuffle(products)
    settings, categories = storefront_context(business)
    return render_template(
        "storefront/home.html", business=business, featured=products,
        settings=settings, categories=categories,
    )


@bp.route("/collection")
def collection():
    business = public_business()
    query = Product.query.filter_by(business_id=business.id, is_published=True)
    category_id = request.args.get("category", type=int)
    selected_category = None
    selected_size = (request.args.get("size") or "").strip()
    selected_colour = (request.args.get("colour") or "").strip()
    if category_id:
        selected_category = Category.query.filter_by(
            id=category_id, business_id=business.id
        ).first()
        if selected_category:
            all_categories = Category.query.filter_by(business_id=business.id).all()
            matching_ids = [
                category.id for category in all_categories
                if " ".join((category.name or "").split()).casefold()
                == " ".join((selected_category.name or "").split()).casefold()
            ]
            query = query.filter(Product.category_id.in_(matching_ids))
        else:
            abort(404)
    if selected_size:
        matching_products = db.session.query(ProductVariant.product_id).filter(
            ProductVariant.business_id == business.id,
            ProductVariant.size.ilike(selected_size),
            ProductVariant.is_available.is_(True),
        ).subquery()
        query = query.filter(Product.id.in_(matching_products))
    if selected_colour:
        matching_products = db.session.query(ProductVariant.product_id).filter(
            ProductVariant.business_id == business.id,
            ProductVariant.colour.ilike(selected_colour),
            ProductVariant.is_available.is_(True),
        ).subquery()
        query = query.filter(Product.id.in_(matching_products))
    products = query.order_by(Product.created_at.desc()).all()
    random.shuffle(products)
    variant_rows = ProductVariant.query.filter_by(
        business_id=business.id, is_available=True
    ).order_by(ProductVariant.size, ProductVariant.colour).all()
    sizes = sorted({variant.size.strip() for variant in variant_rows if variant.size and variant.size.strip()}, key=str.casefold)
    colours = sorted({variant.colour.strip() for variant in variant_rows if variant.colour and variant.colour.strip()}, key=str.casefold)
    settings, categories = storefront_context(business)
    return render_template(
        "storefront/collection.html", business=business, products=products,
        categories=categories, selected_category=selected_category, settings=settings,
        sizes=sizes, colours=colours, selected_size=selected_size,
        selected_colour=selected_colour,
    )


@bp.route("/cart")
def cart():
    # Backwards-compatible URL: render the storefront with its cart drawer,
    # rather than rendering a dedicated cart page.
    business = public_business()
    products = Product.query.filter_by(
        business_id=business.id, is_published=True
    ).order_by(Product.created_at.desc()).limit(4).all()
    settings, categories = storefront_context(business)
    return render_template(
        "storefront/home.html", business=business, featured=products,
        settings=settings, categories=categories,
    )
