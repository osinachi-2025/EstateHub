# Celtine Properties

Celtine Properties is a Flask property marketplace for browsing verified listings, saving properties, scheduling viewings, messaging agents, and publishing new listings through a multi-step agent workflow.

## Features

- Public home page with listing search and browse filters
- Verified-only public property listings
- Filters for purpose, location, property type, price, and bedrooms
- Sorting by newest and price
- Property galleries with cover images and lightbox viewing
- Customer saved properties, messages, reviews, payments, and viewing requests
- Agent dashboard, listing workflow, leads, messages, subscriptions, and profile settings
- Admin listing review and user-management screens
- Password reset by time-limited verification code
- SendGrid email delivery for password reset codes

## Requirements

- Python 3.11 or newer
- A SQL database for production. SQLite works for local development.
- Cloudinary credentials for property image and video uploads
- SendGrid credentials for password reset email delivery

## Local Setup

Create and activate a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create a local environment file:

```powershell
Copy-Item .env.example .env
```

Fill in the values in `.env`, then start Flask:

```powershell
python app.py
```

Open <http://127.0.0.1:5000>.

## Environment Variables

The main settings are documented in `.env.example`:

- `SQLALCHEMY_DATABASE_URI`: database connection string
- `FLASK_SECRET_KEY`: long random value used to sign sessions
- `JWT_SECRET_KEY`: long random value used to sign API tokens
- `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`: media uploads
- `SENDGRID_API_KEY`: SendGrid API key with Mail Send permission
- `SENDGRID_FROM`: verified SendGrid sender address
- `SENDGRID_API_URL`: normally `https://api.sendgrid.com/v3/mail/send`
- `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_FULL_NAME`: optional first-admin configuration

Never commit `.env`, API keys, database credentials, or production secrets.

## Render Deployment

Create a Render **Web Service** connected to this repository.

Use these settings:

- **Runtime:** Python 3
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn app:app`

Render also detects the included `Procfile`, whose command is:

```text
web: gunicorn app:app
```

Add the production environment variables from `.env.example` in Render's Environment settings. Use a Render PostgreSQL database and set `SQLALCHEMY_DATABASE_URI` to its internal connection string. Do not rely on the local SQLite file for production because Render service filesystems are not durable across deployments or restarts.

For property uploads, configure Cloudinary. For password reset codes, configure a verified SendGrid sender and an API key with Mail Send permission.

After deployment, check:

```text
https://your-service.onrender.com/
https://your-service.onrender.com/browse
https://your-service.onrender.com/login
```

## Database Initialization

The application creates missing tables during its first request. When `ADMIN_EMAIL` and `ADMIN_PASSWORD` are configured, the application also creates or updates the configured admin account during initialization.

For production, use a managed database and back it up before deploying schema changes.

## Useful Checks

Compile the Python modules:

```powershell
python -m py_compile app.py models.py
```

Run the application locally with Gunicorn:

```powershell
gunicorn app:app
```
