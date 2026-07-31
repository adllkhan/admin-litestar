# Changelog

Notable changes to `admin-litestar`. Versions follow semantic versioning, with the caveat
that `0.x` carries no stability promise — see the note at the end of 0.1.0.

## 0.1.0 — 2026-07-31

First release.

### Core

- `Admin` / `AdminConfig`: assembles the router, template, session and CSRF configuration a
  Litestar host mounts. `CustomPage` lets a host contribute its own pages, rendered inside
  the same shell and listed in the same nav, with host template directories taking
  precedence over the package's.
- `ModelSpec`: declarative per-model configuration, validated at construction. Unknown
  column names, a hidden column listed in `list_columns`, an excluded column named as
  searchable, and unknown capabilities all raise immediately rather than producing an admin
  that quietly misbehaves.
- Generic list, detail, delete and CSV-export routes driven entirely by specs.
- `AuthBackend`, `AuditSink` and `CacheBackend` protocols: the host supplies its gate, its
  audit destination and its cache, and the package knows nothing about any of them.

### The column boundary

Enforced where statements are built rather than where values are rendered, so a wrong
template cannot leak and a list page pays no decryption cost:

- `hidden_columns` are loaded in detail views and never by a list query — `load_only` keeps
  them out of the SQL itself.
- `excluded_columns` are never selected, rendered or exported anywhere.
- CSV export takes its column set from the spec, not from the row, so an extra key in a row
  dictionary cannot reach a downloaded file.

### Search and pagination

- `searchable` columns match with `ILIKE`; `exact_searchable` columns match by equality,
  with an optional `search_transform` applied to the term first — which is how a host
  searches a keyed-digest column without the package knowing anything about its hashing.
  Exact matching wins when both are declared, because a digest cannot be matched partially.
- Keyset pagination, never `OFFSET`. Cursors are coerced to the order column's Python type,
  with `fromisoformat` for dates and datetimes. A malformed or timezone-naive cursor is
  treated as absent and yields an unpaginated page rather than an error, because cursors
  arrive from URLs and URLs get edited.

### Authentication

- `hash_password` / `verify_password` using `hashlib.scrypt` with `n=16384, r=8, p=1,
  dklen=32`. The encoding is 86 characters, so it fits a `String(128)` column. Anything not
  in that format fails verification; there is no fallback to another scheme, and a
  structurally broken value returns `False` rather than raising.
- Login failures counted per username **and** client IP, locking after 5 attempts for 15
  minutes — deliberately separate from any lockout counter on a host's own user rows, so
  admin brute-force cannot lock someone out of the host application.
- Server-side sessions over a host-supplied store. `AuthBackend.is_valid` is re-checked on
  every request and cached briefly, so revoking access takes effect in seconds rather than
  at session expiry, and a failed revalidation clears the session before rejecting.
- CSRF protection on every mutating route.

### Presentation

- The "Instrument" design system: dark, near-monochrome, one amber accent, monospace for
  identifiers. Light and dark both ship, honouring `prefers-color-scheme` with an explicit
  `data-theme` override. No build step and no runtime CDN — the stylesheet is hand-written
  and HTMX is vendored as package data.
- `py.typed`, so consumers' type checkers see the annotations.

### Guarantees about the package itself

- The package imports only the standard library, `litestar`, `sqlalchemy` and `jinja2`.
  A test enforces this as an allowlist, so an undeclared dependency or a reach into a host
  application fails the suite.
- Tested on Python 3.10 through 3.14, plus 3.15 as a reporting-only job.
- The test suite runs under `-W error`.
- `admin_litestar.__all__` is the compatibility promise. Deeper import paths work but carry
  none.

### Note on stability

The API has one real consumer, so every protocol here is a considered guess about the
second. Expect `0.x` releases to move interfaces; pin exactly if that matters to you.
