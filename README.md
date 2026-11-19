# Multi-Tenant Clothing Catalogue

Flask application for platform-managed clothing storefronts. Each storefront is
resolved by its verified custom hostname; an unknown host does not fall back to
another business.

## Local setup (Windows PowerShell)

```powershell
cd "C:\path\to\clothing store" # Replace with the project folder path
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:SECRET_KEY = "replace-with-a-random-secret-at-least-32-characters"
$env:DATABASE_URL = "sqlite:///clothing_store.db"
$env:COOKIE_SECURE = "false" # Local HTTP only; keep true for HTTPS
python -m flask --app run:app db upgrade
python run.py
```

Open `http://127.0.0.1:5000/login`. The app refuses to start outside test mode
if `SECRET_KEY` is missing or shorter than 32 characters.

Create the first super-admin from another PowerShell window using the same
environment values:

```powershell
python -m flask --app run:app shell
```

```python
from app import db
from app.models import User
admin = User(name="Platform Admin", email="admin@example.com", role="SUPER_ADMIN")
admin.set_password("use-a-unique-password-at-least-12-characters")
db.session.add(admin)
db.session.commit()
```

To preview a local tenant on `localhost`, set `DEFAULT_STORE_SLUG` to an active
business slug before starting Flask. Without that setting, local/unknown hosts
do not select an arbitrary tenant.

Run the test suite:

```powershell
python -m pytest -q
```

## Configuration

Copy `.env.example` values into the process environment or your deployment
provider; `.env` files are not loaded automatically.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Required outside testing; at least 32 characters |
| `DATABASE_URL` | PostgreSQL in production; SQLite is available locally |
| `COOKIE_SECURE` | Defaults to `true`; set to `false` only for local HTTP development |
| `DEFAULT_STORE_SLUG` | Optional local-only tenant preview |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | Product and logo media uploads |
| `RENDER_API_KEY`, `RENDER_SERVICE_ID` | Optional Render custom-domain API integration; configure both |
| `RENDER_SERVICE_HOSTNAME` | Render `onrender.com` hostname used in DNS instructions |

Image uploads validate JPEG, PNG and WebP signatures and require Cloudinary
credentials. Images are delivered through Cloudinary transformations; uploaded
files are not stored in PostgreSQL or the application filesystem.

## Domains and Render

The Render Public API supports adding custom domains and triggering DNS
verification. When both Render API variables are configured, the admin panel
uses those endpoints. Otherwise, an administrator can manage the same workflow
manually. DNS records at the registrar always require manual changes. The app
does not report a domain as connected until Render reports verification (or an
administrator confirms Render's dashboard verification in manual mode). SSL is
reported active only after a real HTTPS certificate check succeeds.

For root domains, use an ALIAS/ANAME to the service hostname or Render's
documented A record `216.24.57.1`. For subdomains, use CNAME to the Render
service hostname. Remove AAAA records while setting up a domain. Follow Render's
current provider-specific instructions:

- [Render custom domains](https://render.com/docs/custom-domains)
- [Render DNS configuration](https://render.com/docs/configure-other-dns)
- [Render custom-domain API](https://api-docs.render.com/reference/create-custom-domain)
- [Render DNS verification API](https://api-docs.render.com/reference/refresh-custom-domain)

## Render deployment

1. Create a Render PostgreSQL database and Web Service.
2. Set build command to `pip install -r requirements.txt`.
3. Set start command to `gunicorn run:app`.
4. Configure `SECRET_KEY` (32+ random characters), `DATABASE_URL`, and
   `COOKIE_SECURE=true`. Add Cloudinary variables to enable uploads.
5. To use Render API domain management, also configure `RENDER_API_KEY`,
   `RENDER_SERVICE_ID`, and `RENDER_SERVICE_HOSTNAME`. Do not put API keys in
   source control.
6. Run `python -m flask --app run:app db upgrade` from the Render shell. The
   checked-in migration history is used; do not re-run `db init`.
7. Create the initial super-admin with the Flask shell. Add each custom domain,
   configure DNS, and verify it through Render.
8. Use `/health` to check application/database readiness.

Render's custom-domain API can add and verify domains but does not manage a
customer's registrar DNS. Render automatically provisions TLS after successful
verification; the application independently checks HTTPS before displaying SSL
as active.

## Account recovery

Platform administrators can issue a single-use, 30-minute password-reset link
from a business's owner account page. The token is stored as a hash and is not
emailed by the application; deliver the displayed link to the owner over a
separately verified channel.

## Operational notes and remaining production work

- `COOKIE_SECURE` defaults to `true`; only disable it for local HTTP development.
- Configure PostgreSQL backups and test restore procedures.
- Configure Render, Cloudinary and a separately verified channel for reset-link
  delivery before onboarding real businesses.
- Login rate limiting, automated password-reset email delivery, comprehensive
  admin audit-log browsing, and full analytics dashboards are not included yet.
- Keep DNS/Render API credentials in the deployment secret manager only.
