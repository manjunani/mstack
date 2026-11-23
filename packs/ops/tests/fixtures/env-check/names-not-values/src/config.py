import os

DATABASE_URL = os.environ["DATABASE_URL"]
STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
MAIL_FROM = os.getenv("MAIL_FROM", "bookings@harbour.example.test")
SENTRY_DSN = os.environ.get("SENTRY_DSN")
