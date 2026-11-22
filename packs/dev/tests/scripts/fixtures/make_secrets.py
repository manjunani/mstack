"""Test helper: write sample files that hold fake secrets, for the commit and secure script tests.

The token strings are joined from parts so that this file itself does not look like a secret to a scanner.
None of the values is real. Usage: make_secrets.py <folder>
"""
import argparse
import pathlib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("folder", type=pathlib.Path)
args = parser.parse_args()
base = args.folder
(base / "src").mkdir(parents=True, exist_ok=True)

aws = "AKIA" + "IOSFODNN7" + "EXAMPLE"
gh = "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
(base / "src" / "settings.py").write_text(
    "REGION = 'eu-west-1'\n"
    f"AWS_KEY = '{aws}'\n"
    f"api_key = \"{gh}\"\n"
    "password = \"changeme-example\"\n"
    "token = os.environ.get('TOKEN')\n", encoding="utf-8")
(base / "src" / "merge.py").write_text("a = 1\n<<<<<<< HEAD\nb = 2\n=======\nb = 3\n>>>>>>> other\n", encoding="utf-8")
(base / ".env").write_text("DB_PASSWORD=" + "s3cr3t" + "Value99\n", encoding="utf-8")
(base / ".env.example").write_text("DB_PASSWORD=\n", encoding="utf-8")
print(f"wrote sample secrets under {base}")
