"""Package-wide defaults and literals."""

DEFAULT_PATH = "/admin"
DEFAULT_STATIC_PATH = "/admin-static"

SESSION_ACTOR_KEY = "admin_actor_id"

HASH_PREFIX = "scrypt"
HASH_SEPARATOR = "$"
HASH_PARTS = 6
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SALT_BYTES = 16
PASSWORD_MAX_LENGTH = 128

LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_TTL = 900
REVALIDATE_TTL = 30
PAGE_SIZE = 50
EXPORT_LIMIT = 10000

CELL_MAX_LENGTH = 48
EMPTY_CELL = "—"
TRUE_CELL = "yes"
FALSE_CELL = "no"
BYTES_CELL = "<{size} bytes>"
HTMX_HEADER = "HX-Request"

ACTION_LOGIN = "login"
ACTION_LOGIN_FAILED = "login_failed"
ACTION_DETAIL_VIEW = "detail_view"
ACTION_EXPORT = "export"
ACTION_DELETE = "delete"

LIST = "list"
DETAIL = "detail"
DELETE = "delete"
EXPORT = "export"
