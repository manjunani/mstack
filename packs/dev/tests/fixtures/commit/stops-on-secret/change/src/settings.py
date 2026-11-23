import os

REGION = "eu-west-1"
AWS_ACCESS_KEY_ID = "@@FAKE_AWS_KEY_ID@@"
AWS_SECRET_ACCESS_KEY = "@@FAKE_AWS_SECRET@@"
BUCKET = os.environ.get("CONFIG_BUCKET", "shop-config")
