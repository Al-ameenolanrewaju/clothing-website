# Client Deployment Guide

This project is being prepared as a reusable clothing-catalogue product that can be delivered to multiple businesses.

## Delivery models

Each client receives an independent installation. Do not share a production database, uploaded-media storage, credentials, or customer/order records between clients.

### Managed hosting

- The service provider owns and operates the hosting account and production database.
- Create a separate web service and a separate persistent PostgreSQL database for each client.
- Configure a unique `SECRET_KEY`, database URL, owner credentials, and domain for each installation.
- The service provider handles backups, monitoring, security updates, and agreed maintenance.
- Charge separately for setup and recurring hosting/maintenance.

### Client-owned hosting

- The client owns the hosting account, database, domain, and billing relationship.
- Deploy the same approved application release into the client's account.
- The client supplies or securely configures their own environment variables and credentials.
- Agree whether future updates and maintenance are included or billed separately.
- Never copy another client's database or secrets into the new installation.

## Current application notes

The current application is a Flask application backed by PostgreSQL in production. Its data model already associates businesses, users, products, categories, product images, customers, orders, settings, and custom domains with a business.

The current production installation is Sulex. Its deployment currently uses a Sulex-specific bootstrap command and must be preserved while generic client provisioning is developed.

The current request-host resolver can select a business from a connected custom domain, but an installation without a matching custom domain falls back to the first active business. This is suitable only for a one-business-per-installation deployment. Do not put multiple clients in the same installation under this fallback behavior.

## Per-client isolation checklist

Before a new client goes live, verify all of the following:

- [ ] A separate application deployment exists for this client.
- [ ] A separate PostgreSQL database exists for this client.
- [ ] A unique application secret is configured.
- [ ] Owner credentials are unique to this client and are delivered securely.
- [ ] The business name, slug, contact details, logo, brand colour, and storefront copy are configured.
- [ ] The client's own products, categories, and photos are added.
- [ ] The client's domain is connected and HTTPS is working.
- [ ] Product browsing and WhatsApp checkout are tested.
- [ ] The owner can only access this installation's dashboard.
- [ ] Database backup and restore procedures are documented.
- [ ] Health checks, logs, and deployment status are verified.

## Release and update policy

Maintain one canonical source repository and use tagged releases for client deployments. Test each release against a staging installation before rollout. For managed clients, deploy the approved release to each installation in a controlled sequence. For client-owned installations, provide the release and deployment instructions or perform the update under an agreed maintenance arrangement.

A code release may be shared; production data, environment secrets, uploaded files, and database backups must never be shared between clients.

## Required productization work

Before onboarding clients at scale, replace the Sulex-only bootstrap with a generic, safe first-install command that accepts per-installation environment configuration while retaining backward compatibility for the existing Sulex deployment. Add a documented environment example, repeatable deployment configuration, backup/restore instructions, and automated installation smoke tests.
