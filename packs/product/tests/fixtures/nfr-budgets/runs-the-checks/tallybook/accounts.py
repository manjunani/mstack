"""Password reset for team members. Tokens are kept in memory; the link goes out by email."""
import datetime
import secrets

TOKEN_MINUTES = 30
MIN_LENGTH = 10
_tokens = {}


def request_reset(email, users, now=None):
    """Return a reset link for a known address, or None. Unknown addresses get no link."""
    if email.lower() not in users:
        return None
    now = now or datetime.datetime.now(datetime.timezone.utc)
    token = secrets.token_urlsafe(16)
    _tokens[token] = (email.lower(), now + datetime.timedelta(minutes=TOKEN_MINUTES))
    return f"/reset?token={token}"


def reset_password(token, new_password, users, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    entry = _tokens.pop(token, None)
    if entry is None or entry[1] < now:
        raise ValueError("this reset link has expired; ask for a new one")
    if len(new_password) < MIN_LENGTH:
        raise ValueError(f"the password needs at least {MIN_LENGTH} characters")
    users[entry[0]] = new_password
    return entry[0]
