import os

from flask import Flask, g, request, session, send_from_directory, Response
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
        UPLOAD_FOLDER=os.getenv("UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads")),
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    )
    if config_object:
        app.config.from_object(config_object)
    if not app.testing:
        secret_key = app.config.get("SECRET_KEY")
        if not isinstance(secret_key, str) or len(secret_key) < 32:
            raise RuntimeError("Configure a SECRET_KEY with at least 32 characters outside testing.")
        if os.getenv("APP_ENV", "").strip().lower() == "production" and app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:"):
            raise RuntimeError("Configure DATABASE_URL with a persistent PostgreSQL database for production.")

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = "auth.login"

    from . import models

    @app.cli.command("bootstrap-sulex")
    def bootstrap_sulex():
        """Create the initial Sulex store and owner from private environment variables."""
        from sqlalchemy.exc import IntegrityError

        owner_email = os.getenv("SULEX_OWNER_EMAIL", "").strip().lower()
        owner_password = os.getenv("SULEX_OWNER_PASSWORD", "")
        existing_business = models.Business.query.filter_by(slug="sulex").first()
        existing_owner = models.User.query.filter_by(email=owner_email).first() if owner_email else None

        # Safe on every restart after successful setup; never resets an existing password.
        if existing_business and existing_owner and existing_owner.business_id == existing_business.id:
            print("Sulex bootstrap already completed.")
            return
        if not owner_email or not owner_password:
            raise RuntimeError("Set SULEX_OWNER_EMAIL and SULEX_OWNER_PASSWORD in the service environment.")
        if len(owner_password) < 12:
            raise RuntimeError("SULEX_OWNER_PASSWORD must be at least 12 characters.")
        if existing_owner:
            raise RuntimeError("SULEX_OWNER_EMAIL is already assigned to a different account.")
        if existing_business and existing_business.status != "ACTIVE":
            raise RuntimeError("The existing Sulex store is not active; refusing to change its status.")

        try:
            business = existing_business or models.Business(
                name="Sulex",
                slug="sulex",
                description="Sulex clothing store",
                contact_email=owner_email,
                status="ACTIVE",
            )
            if not existing_business:
                db.session.add(business)
                db.session.flush()

            owner = models.User(
                business_id=business.id,
                name="Sulex Owner",
                email=owner_email,
                role="OWNER",
                active=True,
            )
            owner.set_password(owner_password)
            db.session.add(owner)

            if not models.StoreSettings.query.filter_by(business_id=business.id).first():
                db.session.add(models.StoreSettings(business_id=business.id))

            if not models.Category.query.filter_by(business_id=business.id).first():
                defaults = {
                    "Men": ["Shirts", "Trousers", "Native Wear", "Senator Outfits", "Agbada", "Kaftans", "Jackets", "Shoes", "Accessories"],
                    "Women": ["Dresses", "Abayas", "Hijabs", "Jilbabs", "Two-Piece Outfits", "Skirts", "Blouses", "Trousers", "Accessories"],
                }
                for gender, names in defaults.items():
                    for category_name in names:
                        slug = "-".join((gender + "-" + category_name).lower().replace("&", " ").split())
                        db.session.add(models.Category(
                            business_id=business.id,
                            name=category_name,
                            slug=slug,
                            gender=gender,
                        ))
            db.session.commit()
            print("Sulex store and owner account created successfully.")
        except IntegrityError:
            db.session.rollback()
            raise RuntimeError("Sulex bootstrap encountered an existing database record; no partial setup was saved.")

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

    @app.get("/media/products/<int:image_id>")
    def product_image(image_id):
        image = models.ProductImage.query.filter_by(id=image_id).first_or_404()
        if not image.image_data or not image.mime_type:
            # Preserve old filesystem-backed catalogue image URLs.
            from flask import abort
            abort(404)
        response = Response(image.image_data, mimetype=image.mime_type)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "public, max-age=86400, immutable"
        return response

    @app.get("/media/businesses/<int:business_id>/logo")
    def business_logo(business_id):
        business = models.Business.query.filter_by(id=business_id).first_or_404()
        if not business.logo_data or not business.logo_mime_type:
            from flask import abort
            abort(404)
        response = Response(business.logo_data, mimetype=business.logo_mime_type)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    @app.get("/media/businesses/<int:business_id>/banner")
    def business_banner(business_id):
        business = models.Business.query.filter_by(id=business_id).first_or_404()
        if not business.banner_data or not business.banner_mime_type:
            from flask import abort
            abort(404)
        response = Response(business.banner_data, mimetype=business.banner_mime_type)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    @app.get("/media/<path:filename>")
    def uploaded_media(filename):
        response = send_from_directory(
            app.config["UPLOAD_FOLDER"],
            filename,
            max_age=86400,
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

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
