# WhatsApp Clothing Catalogue

A simple, single-business clothing catalogue built with Flask. Customers can
browse products, view photos and available sizes/colours, then send an order
request directly to the shop's WhatsApp number. Customers do not need accounts,
and the application does not take payments.

The private dashboard is for one shop owner to manage products, categories,
images, inventory and store details.

## Local setup (Windows PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:SECRET_KEY = "replace-with-a-random-secret-at-least-32-characters"
$env:DATABASE_URL = "sqlite:///clothing_store.db"
$env:COOKIE_SECURE = "false"
python -m flask --app run:app db upgrade
python run.py
```

Open `http://127.0.0.1:5000/login` for the owner login. The app requires a
`SECRET_KEY` of at least 32 characters outside test mode.

## Create the shop and owner account

Run `python -m flask --app run:app shell` using the same environment variables,
then create the single shop and its owner:

```python
from app import db
from app.models import Business, User

shop = Business(
    name="Your Clothing Store",
    slug="your-shop",
    description="Your store description",
    whatsapp_number="2348012345678",
)
owner = User(
    name="Store Owner",
    email="owner@example.com",
    role="OWNER",
)
owner.set_password("use-a-unique-password-at-least-12-characters")
shop.users.append(owner)
db.session.add(shop)
db.session.commit()
```

The app automatically loads the first active business from the database on
the Render URL and any hostname that is not explicitly mapped to a connected
custom domain. You do not need to configure a store slug. Keep only one active
business in the database for this single-shop setup. A connected custom domain
can still point to the shop.

## Configuration

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Required outside testing; at least 32 random characters |
| `DATABASE_URL` | PostgreSQL in production; SQLite for local development |
| `COOKIE_SECURE` | Keep `true` on HTTPS; set `false` only for local HTTP |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | Product and logo image uploads |
| `RENDER_API_KEY`, `RENDER_SERVICE_ID` | Optional existing custom-domain integration |

Image uploads validate JPEG, PNG and WebP signatures and use Cloudinary. Keep
credentials in your environment or Render settings; never commit them.

## Deploy to Render

1. Connect this repository to a Render Web Service.
2. Build command: `pip install -r requirements.txt`.
3. Start command: `gunicorn run:app`.
4. Configure `SECRET_KEY`, `DATABASE_URL`, `DEFAULT_STORE_SLUG` and
   `COOKIE_SECURE=true`. Add Cloudinary credentials to enable image uploads.
5. Run `python -m flask --app run:app db upgrade` once from the Render shell.
6. Create the shop and owner account with the Flask shell if they do not
   already exist.
7. Visit `/health` to check application and database readiness.

## Customer ordering

1. Customer opens the catalogue and chooses a product.
2. Customer selects an available size, colour and quantity.
3. The **Order on WhatsApp** link opens a message addressed to the shop,
   containing the selected product, variant, quantity, price and product URL.
4. The shop owner confirms availability, delivery and payment directly with
   the customer in WhatsApp.

The catalogue does not reserve stock or deduct inventory when a customer opens
WhatsApp. The owner updates inventory from the dashboard after handling the
order. Existing legacy cart/order routes and database tables are retained during
this simplification to avoid destructive database changes; they are no longer
part of the customer-facing navigation or product-order flow.

## Tests

```powershell
python -m pytest -q
```
