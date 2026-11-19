import os

from flask import Flask, g, request, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf import CSRFProtect


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config_object=None):
    app = Flask(__name__)
    database_url = os.getenv("DATABASE_URL", "sqlite:///clothing_store.db").strip()
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        WTF_CSRF_ENABLED=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "true").lower() == "true",
        UPLOAD_FOLDER=os.getenv("UPLOAD_FOLDER", "app/static/uploads"),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    )
    if config_object:
        app.config.from_object(config_object)
    if not app.testing and app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:"):
        raise RuntimeError("Configure DATABASE_URL with a persistent PostgreSQL database for production.")
    if not app.testing:
        secret_key = app.config.get("SECRET_KEY")
        if not isinstance(secret_key, str) or len(secret_key) < 32:
            raise RuntimeError("Configure a SECRET_KEY with at least 32 characters outside testing.")

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = "auth.login"

    from . import models

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return None
        user = models.User.query.filter_by(id=user_id, active=True).first()
        if not user or not user.active:
            return None
        if user.role == "OWNER" and not models.Business.query.filter_by(
            id=user.business_id,
            status="ACTIVE",
        ).first():
            return None
        if user.role not in {"OWNER", "SUPER_ADMIN"}:
            return None
        return user

    @app.before_request
    def resolve_store():
        """Resolve the one configured shop; a connected custom domain may override it."""
        host = (request.host or "").split(":")[0].rstrip(".").lower()
        domain = models.Domain.query.filter(
            db.func.lower(models.Domain.host) == host
        ).first()

        if domain:
            business = domain.business if domain.status == "CONNECTED" else None
            if business and business.status == "ACTIVE":
                g.business = business
                g.domain_status = "CONNECTED"
            else:
                g.business = None
                g.domain_status = domain.status
            return None

        # This app is configured as a single-business catalogue. Use the
        # first active business automatically; no store slug setting is needed.
        business = models.Business.query.filter_by(
            status="ACTIVE"
        ).order_by(models.Business.id.asc()).first()
        g.business = business
        g.domain_status = "default" if business else "NOT_CONFIGURED"

    from .routes.auth import bp as auth_bp
    from .routes.admin import bp as admin_bp
    from .routes.owner import bp as owner_bp
    from .routes.storefront import bp as storefront_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(owner_bp)
    app.register_blueprint(storefront_bp)

    @app.get("/health")
    def health():
        db.session.execute(db.text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    @app.context_processor
    def inject_common():
        business = getattr(g, "business", None)
        store_settings = models.StoreSettings.query.filter_by(business_id=business.id).first() if business else None
        cart_count = 0
        if business:
            cart = session.get("cart", {})
            try:
                variant_ids = [int(key.split(":", 1)[0]) for key in cart]
            except (TypeError, ValueError):
                variant_ids = []
            if variant_ids:
                variants = models.ProductVariant.query.filter(
                    models.ProductVariant.business_id == business.id,
                    models.ProductVariant.id.in_(variant_ids),
                ).all()
                cart_count = sum(int(cart.get(f"{variant.id}:", 0)) for variant in variants)
        return {"tenant": business, "cart_count": cart_count, "settings": store_settings}

    @app.errorhandler(404)
    def not_found(error):
        return {"error": "Not found"}, 404

    return app
