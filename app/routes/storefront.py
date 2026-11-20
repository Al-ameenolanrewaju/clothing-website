from flask import Blueprint, g, render_template, request, abort

from .. import db
from ..models import Category, OrderItem, Product, StoreVisit, StoreSettings, Order


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


@bp.route("/")
def home():
    business = public_business()
    products = Product.query.filter_by(
        business_id=business.id,
        is_published=True,
    ).order_by(Product.created_at.desc()).limit(12).all()
    featured = [product for product in products if product.featured][:8]
    if not featured:
        featured = products[:8]
    new_arrivals = Product.query.filter_by(
        business_id=business.id,
        is_published=True,
        new_arrival=True,
    ).order_by(Product.created_at.desc()).limit(8).all()
    best_sellers = Product.query.join(OrderItem, OrderItem.product_id == Product.id).join(
        Order, Order.id == OrderItem.order_id
    ).filter(
        Product.business_id == business.id,
        Product.is_published.is_(True),
        Order.business_id == business.id,
        Order.status.in_(["CONFIRMED", "PROCESSING", "READY_FOR_DELIVERY", "COMPLETED"]),
    ).group_by(Product.id).order_by(db.func.sum(OrderItem.quantity).desc()).limit(4).all()
    settings = StoreSettings.query.filter_by(business_id=business.id).first()
    categories = Category.query.filter_by(business_id=business.id).order_by(Category.name).all()
    return render_template(
        "storefront/home.html",
        business=business,
        products=products,
        categories=categories,
        featured=featured,
        new_arrivals=new_arrivals,
        best_sellers=best_sellers,
        settings=settings,
    )
