"""Package-wide defaults and literals."""

DEFAULT_PATH = "/admin"
# Relative to DEFAULT_PATH, not an absolute mount — static assets nest under
# the admin's own router rather than being mounted as a second one.
DEFAULT_STATIC_PATH = "/static"

# Theme name -> the stylesheet the shell links. Both carry the same class
# names, so switching one for the other restyles without touching markup.
THEMES = {
    "classic": "admin.css",
    "schematic": "schematic.css",
    "black": "black.css",
}
DEFAULT_THEME = "classic"

SESSION_ACTOR_KEY = "admin_actor_id"
FLASH_SESSION_KEY = "admin_flash"
FLASH_KIND_SUCCESS = "success"
FLASH_KIND_DANGER = "danger"
EXCLUDE_FROM_AUTH_KEY = "exclude_from_auth"

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
# How many choices a relation may offer in a form. Past this the target is
# too large to enumerate honestly, so the field falls back to accepting a key.
RELATION_OPTION_LIMIT = 200
# How many distinct values a filter may offer as a list. Past this the column
# is not a dropdown, and the filter stays a text field.
FILTER_CHOICE_LIMIT = 40
# Query-string suffixes for the two ends of a range filter.
RANGE_START_SUFFIX = "_from"
RANGE_END_SUFFIX = "_to"

# Sort directions, as they appear in a URL.
ASCENDING = "asc"
DESCENDING = "desc"
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
ACTION_UPDATE = "update"
ACTION_CREATE = "create"

LIST = "list"
DETAIL = "detail"
DELETE = "delete"
EXPORT = "export"
EDIT = "edit"
CREATE = "create"

# The complete set a ModelSpec may declare. Exported so a host has something to
# import rather than spelling capability names as bare strings, and validated in
# ModelSpec.__post_init__ so a typo fails loudly instead of producing a model
# whose routes silently do not exist.
CAPABILITIES = frozenset({LIST, DETAIL, DELETE, EXPORT, EDIT, CREATE})

# Defaults for discover_specs: the module a subpackage may define, and the
# attribute expected inside it.
DEFAULT_SPECS_MODULE_NAME = "specs"
DEFAULT_SPECS_ATTRIBUTE = "SPECS"
