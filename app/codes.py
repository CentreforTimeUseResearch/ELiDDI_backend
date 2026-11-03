import hashlib
import hmac
import secrets

# 31 characters: A-Z and 2-9 without the look-alikes 0/O and 1/I/L, so a code
# can be read off a screen or an email and typed back correctly
DEFAULT_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
DEFAULT_LENGTH = 8


def generate_code(length=DEFAULT_LENGTH, alphabet=DEFAULT_ALPHABET):
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# What a Respondent typed -> what is compared: case, spaces and hyphens are
# ignored, so "abcd-efgh" and "ABCDEFGH" are the same code
def normalize_code(text):
    return ''.join(text.split()).replace('-', '').upper()


# ABCDEFGH -> ABCD-EFGH, the way a code is shown
def format_code(code, group=4):
    return '-'.join(code[i : i + group] for i in range(0, len(code), group))


# Codes are stored as a keyed hash (HMAC-SHA256), never as written. A code has
# about 40 bits, so a plain hash could be brute-forced from a leaked database
# in reasonable time. The key stays out of the database. The same code and key
# always give the same hash, which is what lets login look a code up.
def hash_code(code, key):
    return hmac.new(key.encode(), normalize_code(code).encode(), hashlib.sha256).hexdigest()


# $ELIDDI_CODE_HASH_KEY, or else a random key kept in <state_dir>/code_hash_key,
# created on first use. Losing the key makes every stored code unusable.
def load_hash_key(state_dir, environ):
    key = environ.get('ELIDDI_CODE_HASH_KEY')
    if key:
        return key
    path = state_dir / 'code_hash_key'
    if not path.exists():
        state_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding='ascii')
    return path.read_text(encoding='ascii').strip()
