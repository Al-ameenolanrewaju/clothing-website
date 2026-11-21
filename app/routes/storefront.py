from flask import Blueprint, g, render_template, request, abort

from .. import db
from ..models import Category, Product, StoreVisit, StoreSettings

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
    categories = Category.query.filter_by(business_id=business.id).order_by(Category.name).all()
    return settings, categories


@bp.route("/")
def home():
    business = public_business()
    products = Product.query.filter_by(
        business_id=business.id, is_published=True
    ).order_by(Product.created_at.desc()).limit(4).all()
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
    if category_id:
        selected_category = Category.query.filter_by(
            id=category_id, business_id=business.id
        ).first()
        if selected_category:
            query = query.filter_by(category_id=selected_category.id)
        else:
            abort(404)
    products = query.order_by(Product.created_at.desc()).all()
    settings, categories = storefront_context(business)
    return render_template(
        "storefront/collection.html", business=business, products=products,
        categories=categories, selected_category=selected_category, settings=settings,
    )


@bp.route("/cart")
def cart():
    business = public_business()
    settings, categories = storefront_context(business)
    return render_template(
        "storefront/cart.html", business=business, settings=settings, categories=categories,
    )
