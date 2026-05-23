# Vasavi Clubs International — Backend API

Django 5.x backend for phone OTP auth, branches, room inventory, bookings (Razorpay), donors, and coupons.

## Security

Idempotency keys, protected endpoints, and client integration are documented in **[docs/security.md](docs/security.md)**.

## Apps

| App | Responsibility |
|-----|----------------|
| `core` | Abstract base models (`TimeStampedModel`, `SoftDeleteModel`) |
| `accounts` | Custom `User`, OTP, profile confirmation, admin–branch assignment |
| `branches` | Physical branch locations |
| `properties` | Room types and rooms |
| `donors` | Donor profiles, donations, receipts |
| `bookings` | Reservations and status audit log |
| `coupons` | Coupon batches and individual coupons |

## Quick start

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env

python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Admin: http://127.0.0.1:8000/admin/

## Celery (background tasks)

Requires **Redis** running locally (`redis://localhost:6379/0`).

```bash
# Terminal 1 — API
python manage.py runserver

# Terminal 2 — worker (all queues)
celery -A config worker -l info -Q default,payments,notifications,exports,maintenance

# Terminal 3 — periodic tasks (OTP cleanup)
celery -A config beat -l info
```

### Registered tasks

| Task | Queue | Purpose |
|------|-------|---------|
| `accounts.tasks.cleanup_expired_otps` | maintenance | Hourly purge of old OTP logs |
| `bookings.tasks.razorpay_create_order` | payments | Create Razorpay order for a booking |
| `bookings.tasks.razorpay_verify_payment_webhook` | payments | Verify webhook & mark booking paid |
| `bookings.tasks.send_booking_confirmation` | notifications | Email/SMS booking confirmation |
| `bookings.tasks.booking_status_notification` | notifications | Status change alerts |
| `donors.tasks.export_donors_data` | exports | Async CSV donor export |

Example — enqueue donor export from Django shell:

```python
from donors.tasks import export_donors_data
result = export_donors_data.delay(requested_by_user_id=1)
print(result.get(timeout=120))  # includes download_url
```

## Settings

| Module | Use |
|--------|-----|
| `config.settings.local` | Development (default in `manage.py`) |
| `config.settings.production` | Production (`DJANGO_SETTINGS_MODULE`) |

## Migrations

Migration files are **gitignored** by design. After cloning, always run:

```bash
python manage.py makemigrations
python manage.py migrate
```

## Production

```bash
export DJANGO_SETTINGS_MODULE=config.settings.production
export DATABASE_URL=postgres://user:pass@host:5432/vasavi
export SECRET_KEY=...
export ALLOWED_HOSTS=api.example.com

python manage.py collectstatic --noinput
python manage.py migrate
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```
