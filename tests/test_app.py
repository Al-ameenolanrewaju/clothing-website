import re
from io import BytesIO
from urllib.parse import unquote

import pytest
from werkzeug.datastructures import FileStorage

from app import create_app, db
from app.models import (
    Business,
    Category,
    Customer,
    Domain,
    Order,
    OrderItem,
    PasswordResetToken,
    Product,
    ProductImage,
    ProductVariant,
    StoreEvent,
    StoreSettings,
    User,
)
from app.media import delete_image, upload_image, validate_image
from app.utils import normalize_domain


class TestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-secret"
    SESSION_COOKIE_SECURE = False
    DEFAULT_STORE_SLUG = None


class CsrfConfig(TestConfig):
    WTF_CSRF_ENABLED = True


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def make_tenant(app, name="Store A", slug="store-a", host="store-a.test"):
    with app.app_context():
        business = Business(
            name=name,
            slug=slug,
            status="ACTIVE",
            whatsapp_number="2348000000000",
            brand_color="#242424",
        )
        db.session.add(business)
        db.session.flush()
        db.session.add(Domain(
            business_id=business.id,
            host=host,
            status="CONNECTED",
            provider_status="VERIFIED",
            is_primary=True,
        ))
        owner = User(business_id=business.id, name="Owner", email=f"{slug}@example.com", role="OWNER")
        owner.set_password("secret123")
        db.session.add(owner)
        admin = User.query.filter_by(email="admin@example.com").first()
        if not admin:
            admin = User(name="Admin", email="admin@example.com", role="SUPER_ADMIN")
            admin.set_password("secret123")
            db.session.add(admin)
        db.session.commit()
        return business.id, owner.id


def make_product(app, business_id, **values):
    defaults = {
        "business_id": business_id,
        "name": "Linen Shirt",
        "slug": "linen-shirt",
        "description": "A relaxed linen shirt",
        "regular_price": 25000,
        "gender": "Men",
        "fashion_type": "Ready-to-wear",
        "is_published": True,
    }
    defaults.update(values)
    with app.app_context():
        product = Product(**defaults)
        db.session.add(product)
        db.session.commit()
        return product.id


def login_owner(client, slug="store-a", host="store-a.test"):
    return client.post(
        "/login",
        data={"email": f"{slug}@example.com", "password": "secret123"},
        base_url=f"http://{host}",
    )


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_missing_secret_key_prevents_non_test_startup(monkeypatch):
    class ProductionConfig:
        TESTING = False
        SECRET_KEY = None

    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(ProductionConfig)


def test_short_secret_key_prevents_non_test_startup(monkeypatch):
    class ProductionConfig:
        TESTING = False
        SECRET_KEY = "too-short"

    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="32 characters"):
        create_app(ProductionConfig)


def test_production_requires_persistent_database(monkeypatch):
    class ProductionConfig:
        TESTING = False
        SECRET_KEY = "a-production-secret-key-with-at-least-32-characters"

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="persistent PostgreSQL"):
        create_app(ProductionConfig)


def test_session_cookies_are_secure_by_default(monkeypatch):
    class SecureCookieConfig:
        TESTING = True
        SECRET_KEY = "test-secret"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    app = create_app(SecureCookieConfig)
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_login_rejects_bad_credentials_and_owner_cannot_open_admin(app, client):
    make_tenant(app)
    response = client.post("/login", data={"email": "store-a@example.com", "password": "wrong"})
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data
    login_owner(client)
    assert client.get("/admin/", base_url="http://store-a.test").status_code == 403


def test_admin_business_provisioning_creates_owner_categories_and_settings(app, client):
    with app.app_context():
        admin = User(name="Admin", email="admin@example.com", role="SUPER_ADMIN")
        admin.set_password("secret123")
        db.session.add(admin)
        db.session.commit()
    client.post("/login", data={"email": "admin@example.com", "password": "secret123"})
    assert client.get("/admin/").status_code == 200
    response = client.post("/admin/businesses", data={
        "name": "New Atelier",
        "slug": "new-atelier",
        "description": "A clothing studio",
        "owner_name": "A Owner",
        "owner_email": "owner@atelier.example",
        "owner_phone": "123",
        "contact_email": "hello@atelier.example",
        "address": "1 High Street",
        "whatsapp_number": "2348010000000",
        "domain": "",
        "status": "ACTIVE",
    })
    assert response.status_code == 302
    with app.app_context():
        business = Business.query.filter_by(slug="new-atelier").one()
        owner = User.query.filter_by(email="owner@atelier.example").one()
        assert owner.password_hash != "ChangeMe!2026"
        assert owner.check_password(owner.password_hash) is False
        assert Category.query.filter_by(business_id=business.id).count() == 18
        assert StoreSettings.query.filter_by(business_id=business.id).one()


def test_admin_business_edit_page_and_domain_page_render(app, client):
    business_id, owner_id = make_tenant(app)
    client.post("/login", data={"email": "admin@example.com", "password": "secret123"})
    assert client.get(f"/admin/businesses/{business_id}/edit").status_code == 200
    assert client.get("/admin/domains").status_code == 200


def test_unauthenticated_dashboard_redirects_to_login(client):
    response = client.get("/dashboard/")
    assert response.status_code == 302
    assert "/login" in response.location


def test_inactive_users_and_suspended_businesses_cannot_keep_sessions(app, client):
    business_id, owner_id = make_tenant(app)
    with app.app_context():
        db.session.get(User, owner_id).active = False
        db.session.commit()
    invalid_login = client.post("/login", data={
        "email": "store-a@example.com", "password": "secret123",
    }, base_url="http://store-a.test")
    assert b"Invalid email or password" in invalid_login.data
    with app.app_context():
        db.session.get(User, owner_id).active = True
        db.session.commit()
    login_owner(client)
    with app.app_context():
        db.session.get(Business, business_id).status = "SUSPENDED"
        db.session.commit()
    response = client.get("/dashboard/", base_url="http://store-a.test")
    assert response.status_code == 302
    assert "/login" in response.location


def test_domain_resolution_isolated_and_single_store_fallback(app, client):
    business_a, _ = make_tenant(app)
    business_b, _ = make_tenant(app, "Store B", "store-b", "store-b.test")
    product_a = make_product(app, business_a, name="A coat", slug="a-coat")
    product_b = make_product(app, business_b, name="B dress", slug="b-dress", gender="Women")

    response_a = client.get("/catalogue", base_url="http://store-a.test")
    response_b = client.get("/catalogue", base_url="http://store-b.test")
    response_unknown = client.get("/catalogue", base_url="http://unknown.test")
    assert b"A coat" in response_a.data and b"B dress" not in response_a.data
    assert b"B dress" in response_b.data and b"A coat" not in response_b.data
    assert b"A coat" in response_unknown.data and b"B dress" not in response_unknown.data


def test_owner_cannot_read_or_mutate_another_business_product_or_order(app, client):
    business_a, _ = make_tenant(app)
    business_b, _ = make_tenant(app, "Store B", "store-b", "store-b.test")
    product_b = make_product(app, business_b, name="Private dress", slug="private-dress")
    with app.app_context():
        customer = Customer(business_id=business_b, name="Other customer", phone="123")
        db.session.add(customer)
        db.session.flush()
        order = Order(
            business_id=business_b,
            customer_id=customer.id,
            reference="PRIVATE-ORDER",
            subtotal=10,
            total=10,
        )
        db.session.add(order)
        db.session.commit()
        order_id = order.id
        variant = ProductVariant(
            business_id=business_b,
            product_id=product_b,
            size="M",
            colour="Blue",
            stock_quantity=4,
            is_available=True,
        )
        db.session.add(variant)
        db.session.commit()
    login_owner(client)
    assert client.get(f"/dashboard/products/{product_b}/edit", base_url="http://store-a.test").status_code == 404
    assert client.post(f"/dashboard/products/{product_b}/variants", data={
        "size": "M", "colour": "Blue", "stock": "0", "available": "on",
    }, base_url="http://store-a.test").status_code == 404
    assert client.get(f"/dashboard/orders/{order_id}", base_url="http://store-a.test").status_code == 404
    assert client.get("/dashboard/orders", base_url="http://store-a.test").status_code == 200
    assert b"PRIVATE-ORDER" not in client.get("/dashboard/orders", base_url="http://store-a.test").data


def test_product_create_edit_publish_and_archive(app, client):
    business_id, _ = make_tenant(app)
    with app.app_context():
        category = Category(business_id=business_id, name="Shirts", slug="shirts", gender="Men")
        db.session.add(category)
        db.session.commit()
        category_id = category.id
    login_owner(client)
    create_response = client.post("/dashboard/products", data={
        "name": "Linen shirt",
        "slug": "linen-shirt",
        "description": "Lightweight fabric",
        "regular_price": "125.00",
        "discounted_price": "",
        "category_id": str(category_id),
        "gender": "Men",
        "fashion_type": "Ready-to-wear",
        "sku": "SHIRT-1",
        "featured": "y",
        "new_arrival": "y",
        "is_published": "y",
    }, base_url="http://store-a.test")
    assert create_response.status_code == 302
    with app.app_context():
        product = Product.query.filter_by(business_id=business_id, slug="linen-shirt").one()
        product_id = product.id
        assert product.featured and product.new_arrival and product.is_published
    edit_response = client.post(f"/dashboard/products/{product_id}/edit", data={
        "name": "Linen shirt updated",
        "slug": "linen-shirt",
        "description": "Updated description",
        "regular_price": "135.00",
        "discounted_price": "120.00",
        "category_id": str(category_id),
        "gender": "Men",
        "fashion_type": "Ready-to-wear",
        "sku": "SHIRT-1",
        "is_published": "y",
    }, base_url="http://store-a.test")
    assert edit_response.status_code == 302
    with app.app_context():
        product = db.session.get(Product, product_id)
        assert product.name == "Linen shirt updated"
        assert product.price == 120
    archive = client.post(f"/dashboard/products/{product_id}/archive", base_url="http://store-a.test")
    assert archive.status_code == 302
    with app.app_context():
        assert db.session.get(Product, product_id).is_published is False


def test_multiple_product_images_are_saved_and_deleted(app, client, monkeypatch):
    business_id, _ = make_tenant(app)
    monkeypatch.setattr("app.routes.owner.upload_image", lambda file, folder: (
        f"https://media.example/{file.filename}", f"{folder}/{file.filename}",
    ))
    login_owner(client)
    response = client.post("/dashboard/products", data={
        "name": "Photo Coat",
        "slug": "photo-coat",
        "regular_price": "150",
        "category_id": "0",
        "gender": "Women",
        "fashion_type": "Ready-to-wear",
        "is_published": "y",
        "images": [
            (BytesIO(b"\xff\xd8\xff" + b"\x00" * 20), "front.jpg"),
            (BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20), "back.png"),
        ],
    }, base_url="http://store-a.test", content_type="multipart/form-data")
    assert response.status_code == 302
    with app.app_context():
        product = Product.query.filter_by(business_id=business_id, slug="photo-coat").one()
        assert ProductImage.query.filter_by(product_id=product.id).count() == 2
        image_id = product.images[0].id
    deleted = []
    monkeypatch.setattr("app.routes.owner.delete_image", lambda public_id: deleted.append(public_id))
    response = client.post(
        f"/dashboard/products/{product.id}/images/{image_id}/delete",
        base_url="http://store-a.test",
    )
    assert response.status_code == 302
    assert deleted
    with app.app_context():
        assert ProductImage.query.filter_by(product_id=product.id).count() == 1


def test_discount_cannot_exceed_regular_price(app, client):
    make_tenant(app)
    login_owner(client)
    response = client.post("/dashboard/products", data={
        "name": "Bad discount", "slug": "bad-discount", "regular_price": "100",
        "discounted_price": "101", "category_id": "0", "gender": "Unisex",
        "fashion_type": "Ready-to-wear", "is_published": "y",
    }, base_url="http://store-a.test")
    assert response.status_code == 200
    assert b"Discounted price cannot exceed regular price" in response.data
    with app.app_context():
        assert Product.query.filter_by(slug="bad-discount").count() == 0


def test_variant_inventory_update_and_validation(app, client):
    business_id, _ = make_tenant(app)
    product_id = make_product(app, business_id)
    login_owner(client)
    response = client.post(f"/dashboard/products/{product_id}/variants", data={
        "size": "M", "colour": "Wine", "sku": "LINEN-M-WINE",
        "price_override": "26000.00", "stock": "3", "available": "on",
    }, base_url="http://store-a.test")
    assert response.status_code == 302
    with app.app_context():
        variant = ProductVariant.query.one()
        variant_id = variant.id
        assert variant.stock_quantity == 3 and variant.price_override == 26000
    bad_response = client.post(f"/dashboard/products/{product_id}/variants", data={
        "size": "M", "colour": "Wine", "stock": "-2",
    }, base_url="http://store-a.test")
    assert bad_response.status_code == 400
    with app.app_context():
        assert db.session.get(ProductVariant, variant_id).stock_quantity == 3


def test_categories_are_editable_and_cannot_delete_in_use(app, client):
    business_id, _ = make_tenant(app)
    with app.app_context():
        category = Category(business_id=business_id, name="Shirts", slug="shirts", gender="Men")
        db.session.add(category)
        db.session.commit()
        category_id = category.id
    make_product(app, business_id, category_id=category_id)
    login_owner(client)
    assert client.get("/dashboard/categories", base_url="http://store-a.test").status_code == 200
    response = client.post(f"/dashboard/categories/{category_id}/edit", data={
        "name": "Tops", "slug": "tops", "gender": "Men",
    }, base_url="http://store-a.test")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Category, category_id).name == "Tops"
    response = client.post(f"/dashboard/categories/{category_id}/delete", base_url="http://store-a.test")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Category, category_id) is not None


def test_storefront_filters_and_product_pages(app, client):
    business_id, _ = make_tenant(app)
    medium = make_product(app, business_id, name="Blue Coat", slug="blue-coat", gender="Women")
    other = make_product(app, business_id, name="Black Trousers", slug="black-trousers", gender="Men")
    with app.app_context():
        db.session.add_all([
            ProductVariant(business_id=business_id, product_id=medium, size="M", colour="Blue",
                           stock_quantity=2, is_available=True),
            ProductVariant(business_id=business_id, product_id=other, size="S", colour="Black",
                           stock_quantity=1, is_available=True),
        ])
        db.session.commit()
    listing = client.get("/catalogue?gender=Women&size=M&colour=Blue&availability=available",
                         base_url="http://store-a.test")
    detail = client.get("/product/blue-coat", base_url="http://store-a.test")
    home = client.get("/", base_url="http://store-a.test")
    assert b"Blue Coat" in listing.data and b"Black Trousers" not in listing.data
    assert detail.status_code == 200 and b"Order on WhatsApp" in detail.data
    assert home.status_code == 200 and b"Pieces made to be remembered." in home.data
    assert client.get("/cart", base_url="http://store-a.test").status_code == 200
    login_owner(client)
    dashboard = client.get("/dashboard/", base_url="http://store-a.test")
    assert dashboard.status_code == 200 and b"Manage products" in dashboard.data


def test_cart_and_checkout_use_server_price_stock_and_snapshot(app, client):
    business_id, _ = make_tenant(app)
    product_id = make_product(app, business_id, name="Senator Outfit", slug="senator-outfit")
    with app.app_context():
        variant = ProductVariant(
            business_id=business_id,
            product_id=product_id,
            size="L",
            colour="Blue",
            price_override=27500,
            stock_quantity=2,
            is_available=True,
        )
        db.session.add(variant)
        db.session.commit()
        variant_id = variant.id
    added = client.post("/cart/add", data={
        "product_id": product_id, "variant_id": variant_id,
        "size": "L", "colour": "Blue", "quantity": "1", "price": "0.01",
    }, base_url="http://store-a.test")
    assert added.status_code == 302
    response = client.post("/checkout", data={
        "name": "Ada", "phone": "08012345678", "address": "12 Market Road",
        "instructions": "Call before delivery", "total": "0.01",
    }, base_url="http://store-a.test")
    assert response.status_code == 200
    with app.app_context():
        order = Order.query.one()
        item = OrderItem.query.one()
        order_id = order.id
        order_reference = order.reference
        assert order.status == "WHATSAPP_CHECKOUT_INITIATED"
        assert order.total == 27500 and item.unit_price == 27500
        assert item.product_name == "Senator Outfit" and item.size == "L" and item.colour == "Blue"
        assert db.session.get(ProductVariant, variant_id).stock_quantity == 1
        product = db.session.get(Product, product_id)
        product.name = "Renamed after order"
        product.regular_price = 99999
        db.session.commit()
        assert item.product_name == "Senator Outfit" and item.unit_price == 27500
    click = client.get(f"/order/{order_reference}/whatsapp", base_url="http://store-a.test")
    assert click.status_code == 302 and "wa.me/2348000000000" in click.location
    assert "Senator%20Outfit" in click.location or "Senator+Outfit" in click.location
    with app.app_context():
        assert StoreEvent.query.filter_by(order_id=order_id, event_type="WHATSAPP_CHECKOUT_CLICK").count() == 1


def test_cart_rejects_unavailable_variants_and_changed_stock(app, client):
    business_id, _ = make_tenant(app)
    product_id = make_product(app, business_id)
    with app.app_context():
        variant = ProductVariant(business_id=business_id, product_id=product_id, size="S", colour="White",
                                 stock_quantity=1, is_available=True)
        db.session.add(variant)
        db.session.commit()
        variant_id = variant.id
    response = client.post("/cart/add", data={
        "product_id": product_id, "variant_id": variant_id,
        "size": "XL", "colour": "White", "quantity": "1",
    }, base_url="http://store-a.test")
    assert response.status_code == 302
    client.post("/cart/add", data={
        "product_id": product_id, "size": "S", "colour": "White", "quantity": "1",
    }, base_url="http://store-a.test")
    with app.app_context():
        db.session.get(ProductVariant, variant_id).stock_quantity = 0
        db.session.commit()
    checkout = client.post("/checkout", data={
        "name": "Ada", "phone": "08012345678", "address": "Address",
    }, base_url="http://store-a.test")
    assert checkout.status_code == 200
    assert b"Cart contents changed" in checkout.data
    with app.app_context():
        variant = db.session.get(ProductVariant, variant_id)
        variant.stock_quantity = 1
        variant.is_available = True
        db.session.commit()
    invalid_phone = client.post("/checkout", data={
        "name": "Ada", "phone": "not a phone 123", "address": "Address",
    }, base_url="http://store-a.test")
    assert invalid_phone.status_code == 200
    assert b"valid name, phone number" in invalid_phone.data
    with app.app_context():
        assert Order.query.count() == 0


def test_owner_can_change_profile_and_password(app, client, monkeypatch):
    business_id, owner_id = make_tenant(app)
    monkeypatch.setattr("app.routes.owner.upload_image", lambda file, folder: (
        "https://media.example/store-logo.webp", f"{folder}/store-logo",
    ))
    login_owner(client)
    settings_page = client.get("/dashboard/settings", base_url="http://store-a.test")
    assert settings_page.status_code == 200 and b"Store information" in settings_page.data
    settings_response = client.post("/dashboard/settings", data={
        "name": "My Updated Store",
        "description": "New description",
        "phone": "020000",
        "contact_email": "contact@example.com",
        "address": "1 Market Street",
        "whatsapp_number": "+234 801 222 3333",
        "brand_color": "#123456",
        "announcement": "New drop",
        "hero_title": "The collection",
        "about_text": "Made with care",
        "business_id": "9999",
        "logo": (BytesIO(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 12), "store.webp"),
    }, base_url="http://store-a.test")
    assert settings_response.status_code == 302
    with app.app_context():
        business = db.session.get(Business, business_id)
        assert business.name == "My Updated Store"
        assert business.whatsapp_number == "+234 801 222 3333"
        assert business.logo_url == "https://media.example/store-logo.webp"
        assert StoreSettings.query.filter_by(business_id=business_id).one().hero_title == "The collection"
    password_response = client.post("/dashboard/account/password", data={
        "current_password": "secret123",
        "new_password": "correct horse battery",
        "confirm_password": "correct horse battery",
    }, base_url="http://store-a.test")
    assert password_response.status_code == 302
    bad_login = client.post("/login", data={
        "email": "store-a@example.com", "password": "secret123",
    }, base_url="http://store-a.test")
    assert b"Invalid email or password" in bad_login.data


def test_admin_password_reset_is_single_use(app, client):
    business_id, owner_id = make_tenant(app)
    client.post("/login", data={"email": "admin@example.com", "password": "secret123"})
    response = client.post(f"/admin/owners/{owner_id}/reset-password")
    assert response.status_code == 302
    page = client.get(response.location)
    match = re.search(rb"/reset-password/([A-Za-z0-9_-]+)", page.data)
    assert match
    reset_path = "/reset-password/" + match.group(1).decode("ascii")
    reset_response = client.post(reset_path, data={
        "password": "a much better password",
        "confirm_password": "a much better password",
    })
    assert reset_response.status_code == 302
    assert client.get(reset_path).status_code == 410
    with app.app_context():
        assert PasswordResetToken.query.one().used_at is not None
        assert db.session.get(User, owner_id).check_password("a much better password")


def test_owner_order_filter_status_and_cancellation_restock(app, client):
    business_id, _ = make_tenant(app)
    product_id = make_product(app, business_id)
    with app.app_context():
        customer = Customer(business_id=business_id, name="Ada Customer", phone="123456")
        variant = ProductVariant(business_id=business_id, product_id=product_id, size="M", colour="Cream",
                                 stock_quantity=0, is_available=False)
        db.session.add_all([customer, variant])
        db.session.flush()
        order = Order(business_id=business_id, customer_id=customer.id, reference="ORDER-ABC",
                      subtotal=100, total=100, status="WHATSAPP_CHECKOUT_INITIATED")
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(business_id=business_id, order_id=order.id, product_id=product_id,
                                 variant_id=variant.id, product_name="Linen Shirt", size="M", colour="Cream",
                                 quantity=2, unit_price=50, line_total=100))
        order_id = order.id
        variant_id = variant.id
        db.session.commit()
    login_owner(client)
    listing = client.get("/dashboard/orders?q=ORDER-ABC&status=WHATSAPP_CHECKOUT_INITIATED",
                         base_url="http://store-a.test")
    assert b"ORDER-ABC" in listing.data
    assert b"ORDER-ABC" not in client.get("/dashboard/orders?q=missing", base_url="http://store-a.test").data
    response = client.post(f"/dashboard/orders/{order_id}", data={
        "status": "CANCELLED", "internal_notes": "Customer cancelled",
    }, base_url="http://store-a.test")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(ProductVariant, variant_id).stock_quantity == 2
        assert db.session.get(ProductVariant, variant_id).is_available
        assert db.session.get(Order, order_id).status == "CANCELLED"
    assert client.post(f"/dashboard/orders/{order_id}", data={
        "status": "CONFIRMED", "internal_notes": "",
    }, base_url="http://store-a.test").status_code == 400


def test_domain_validation_and_manual_verification(app, client, monkeypatch):
    monkeypatch.delenv("RENDER_API_KEY", raising=False)
    monkeypatch.delenv("RENDER_SERVICE_ID", raising=False)
    business_id, _ = make_tenant(app)
    client.post("/login", data={"email": "admin@example.com", "password": "secret123"})
    bad = client.post("/admin/domains", data={
        "business_id": str(business_id), "host": "https://127.0.0.1",
    })
    assert bad.status_code == 200
    good = client.post("/admin/domains", data={
        "business_id": str(business_id), "host": "SHOP.Example.com",
    })
    assert good.status_code == 302
    with app.app_context():
        domain = Domain.query.filter_by(host="shop.example.com").one()
        domain_id = domain.id
        assert domain.status == "PENDING" and domain.provider_status == "MANUAL"
    assert client.get("/catalogue", base_url="http://shop.example.com").status_code == 404
    unconfirmed = client.post(f"/admin/domains/{domain_id}/verify")
    assert unconfirmed.status_code == 302
    with app.app_context():
        assert db.session.get(Domain, domain_id).status == "PENDING"
    confirmed = client.post(f"/admin/domains/{domain_id}/verify", data={"render_verified": "yes"})
    assert confirmed.status_code == 302
    with app.app_context():
        domain = db.session.get(Domain, domain_id)
        assert domain.status == "CONNECTED" and domain.verified_at is not None
    monkeypatch.setattr("app.routes.admin._tls_is_valid", lambda host: True)
    ssl_check = client.post(f"/admin/domains/{domain_id}/ssl-check")
    assert ssl_check.status_code == 302
    with app.app_context():
        assert db.session.get(Domain, domain_id).ssl_status == "ACTIVE"
    assert client.get("/catalogue", base_url="http://shop.example.com").status_code == 200
    suspended = client.post(f"/admin/domains/{domain_id}/suspend")
    assert suspended.status_code == 302
    assert client.get("/catalogue", base_url="http://shop.example.com").status_code == 404
    assert b"Reactivate" in client.get("/admin/domains").data
    reactivated = client.post(f"/admin/domains/{domain_id}/reactivate")
    assert reactivated.status_code == 302
    with app.app_context():
        domain = db.session.get(Domain, domain_id)
        assert domain.status == "PENDING" and domain.verified_at is None
    assert client.get("/catalogue", base_url="http://shop.example.com").status_code == 404


def test_render_api_domain_is_not_connected_until_provider_verifies(app, client, monkeypatch):
    business_id, _ = make_tenant(app)
    monkeypatch.setenv("RENDER_API_KEY", "not-a-real-key")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-test")
    monkeypatch.setattr("app.render_api.add_custom_domain", lambda host: {
        "id": "rnd-domain-123", "name": host, "verificationStatus": "unverified",
    })
    verification = {"status": "unverified"}
    monkeypatch.setattr("app.render_api.verify_custom_domain", lambda domain_id: None)
    monkeypatch.setattr("app.render_api.get_custom_domain", lambda domain_id: {
        "id": domain_id, "name": "api.example.com", "verificationStatus": verification["status"],
    })
    client.post("/login", data={"email": "admin@example.com", "password": "secret123"})
    response = client.post("/admin/domains", data={
        "business_id": str(business_id), "host": "api.example.com",
    })
    assert response.status_code == 302
    with app.app_context():
        domain = Domain.query.filter_by(host="api.example.com").one()
        domain_id = domain.id
        assert domain.render_domain_id == "rnd-domain-123"
        assert domain.status == "PENDING"
    response = client.post(f"/admin/domains/{domain_id}/verify")
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Domain, domain_id).status == "PENDING"
    verification["status"] = "verified"
    response = client.post(f"/admin/domains/{domain_id}/refresh")
    assert response.status_code == 302
    with app.app_context():
        domain = db.session.get(Domain, domain_id)
        assert domain.status == "CONNECTED"
        assert domain.provider_status == "VERIFIED"
        assert domain.verified_at is not None


def test_domain_normalization():
    assert normalize_domain(" SHOP.Example.com. ") == "shop.example.com"
    assert normalize_domain("münich.example") == "xn--mnich-kva.example"
    for invalid in ("https://example.com", "127.0.0.1", "bad host.example", "example"):
        with pytest.raises(ValueError):
            normalize_domain(invalid)


def test_local_image_upload_serve_and_delete(app, tmp_path):
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    valid_png = FileStorage(stream=BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 12), filename="test.png")
    validate_image(valid_png)
    invalid = FileStorage(stream=BytesIO(b"<html>not an image"), filename="bad.png")
    with pytest.raises(ValueError, match="valid JPEG"):
        validate_image(invalid)

    with app.test_request_context():
        image_url, storage_key = upload_image(valid_png, "clothing-catalogue/1/products/2")
    assert image_url.startswith("/media/")
    image_path = tmp_path / storage_key
    assert image_path.is_file()
    response = app.test_client().get(image_url)
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"

    delete_image(storage_key)
    assert not image_path.exists()


def test_product_and_variant_deletion_preserve_order_history(app, client):
    business_id, _ = make_tenant(app)
    deletable_id = make_product(app, business_id, name="Unused item", slug="unused-item")
    protected_id = make_product(app, business_id, name="Ordered item", slug="ordered-item")
    with app.app_context():
        variant = ProductVariant(
            business_id=business_id, product_id=protected_id, size="M", colour="Black",
            stock_quantity=2, is_available=True,
        )
        db.session.add(variant)
        db.session.flush()
        customer = Customer(business_id=business_id, name="Buyer", phone="2348000000000")
        db.session.add(customer)
        db.session.flush()
        order = Order(
            business_id=business_id, customer_id=customer.id, reference="ORDER-KEEP",
            subtotal=100, total=100,
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(OrderItem(
            business_id=business_id, order_id=order.id, product_id=None, variant_id=variant.id,
            product_name="Ordered item", size="M", colour="Black", quantity=1,
            unit_price=100, line_total=100,
        ))
        variant_id = variant.id
        db.session.commit()
    login_owner(client)
    deleted = client.post(f"/dashboard/products/{deletable_id}/delete", base_url="http://store-a.test")
    assert deleted.status_code == 302
    with app.app_context():
        assert db.session.get(Product, deletable_id) is None
    blocked_product = client.post(f"/dashboard/products/{protected_id}/delete", base_url="http://store-a.test")
    blocked_variant = client.post(
        f"/dashboard/products/{protected_id}/variants/{variant_id}/delete",
        base_url="http://store-a.test",
    )
    assert blocked_product.status_code == 302
    assert blocked_variant.status_code == 302
    with app.app_context():
        assert db.session.get(Product, protected_id) is not None
        assert db.session.get(ProductVariant, variant_id) is not None


def test_csrf_is_required_outside_disabled_test_configuration():
    app = create_app(CsrfConfig)
    response = app.test_client().post("/login", data={"email": "admin@example.com", "password": "secret123"})
    assert response.status_code == 400
