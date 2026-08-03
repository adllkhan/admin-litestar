# Changelog

Notable changes to `admin-litestar`. Versions follow semantic versioning, with the caveat
that `0.x` carries no stability promise — see the note at the end of 0.1.0.

## 0.2.0 — 2026-07-31

First contact with a real consumer exposed five defects. All five are fixed here; the
first is a correctness bug serious enough that anyone running 0.1.0 needs to know about it
plainly.

### Fixed — admin deletes and audit writes did not persist (0.1.0)

**In 0.1.0, every delete made through the admin, and every audit row `AuditSink.write` was
asked to record, was silently discarded.** `Admin._provide_session` opened a session and
yielded it but never committed. A `session.delete()` followed by `flush()` is visible
within that same session, so the row appeared gone and the audit write appeared to succeed
— until the session closed, at which point nothing had reached the database. The host's
own `before_send_handler="autocommit"` does not help: it only autocommits sessions the
SQLAlchemy plugin itself provides, never one `Admin` opens. If you installed 0.1.0 and
used the admin to delete anything, or relied on its audit trail: **those rows were never
written.** `_provide_session` now commits once its handler returns successfully, and lets
the session's own exit roll back on any exception, rather than committing nothing either
way.

A related defect surfaced while writing the database-backed regression test for this fix:
the generic detail and delete routes bind a primary key from the URL as a plain string,
and PostgreSQL via `asyncpg` refuses an implicit `bigint = character varying` comparison —
so `detail_statement` would fail at the database for any integer-keyed model, not just
misbehave quietly. `detail_statement` now coerces the incoming key to the primary-key
column's Python type first, the same pattern `list_statement` already used for keyset
cursors.

### Fixed — two routers where the host expected one

`Admin.static_router()` returned a second, separately-mounted `Router` at an absolute
`AdminConfig.static_path` (`/admin-static`). A host now mounts `Admin.router()` alone:
static assets are nested inside it, at `<admin_path><static_path>`. `static_router()` is
removed — a method that would return nothing useful once everything is one router is worse
than not having it. **Breaking:** `AdminConfig.static_path` is now a path segment relative
to `path` (default `/static`), not an absolute mount path, and a host that called
`admin.static_router()` must delete that call.

### Fixed — session and CSRF cookies were not marked `Secure`

Both cookies came back with `secure=False` unconditionally, so a session cookie — and with
it the login gate, the lockout counter and revalidation together — would travel over plain
HTTP if a host's TLS terminated anywhere the browser could observe. `AdminConfig` gained
`secure_cookies: bool = True`; a host serving over plain HTTP locally or in tests sets it to
`False` explicitly rather than getting an insecure cookie by default.

### Fixed — `session_factory` broke silently on the second `Admin` built in a process

`Admin.router()` builds a `Router` that Litestar deep-copies on registration — in fact
twice over now that static assets nest inside it. `copy.deepcopy` treats a plain function
as atomic and returns it unchanged, but recurses into anything else, including a bound
method's `__self__`. A `session_factory` bound to a live engine or connection pool (for
example `sqlalchemy_config.get_session`, or a bare `async_sessionmaker` instance — the very
shape this class's own docstring recommended) therefore failed to deep-copy on the second
`Admin` constructed in one process, once that engine existed. `Admin.__init__` now wraps
whatever `session_factory` it is given in its own plain closure before it is stored
anywhere. This was chosen over detecting and rejecting a bound method specifically: a bare
`async_sessionmaker` instance fails the exact same way and a bound-method check would have
missed it, so unconditional wrapping is the fix that actually covers every shape a host
might reasonably pass, rather than the one shape a bug report happened to name.

### Fixed — `csrf_config` applied CSRF app-wide

`Admin.csrf_config(secret)` returned a bare `CSRFConfig` for `Litestar(csrf_config=...)` —
the only hook Litestar accepts one at, which is app-wide by construction. A host mounting
the admin beside its own API turned every one of that API's mutating routes' rejections
into a 403. `csrf_config()` is removed. CSRF protection is now a constructor argument,
`Admin(..., csrf_secret=...)`, and — when supplied — is attached as `CSRFMiddleware`
directly to the admin's own gated router rather than the app. Litestar resolves middleware
per route through the same ownership chain it already uses for guards, so this scopes
enforcement to the admin's routes structurally, with no `exclude` pattern: an `exclude`
regex broad enough to scope CSRF to one path is exactly the shape that trips Litestar's own
"middleware is effectively disabled" warning, which would have argued for weakening the
scoping it was added to achieve. `csrf_secret` defaults to `None` (no CSRF), matching a
host that has deliberately declined it. **Breaking:** a host calling `admin.csrf_config(...)`
must pass `csrf_secret=` to `Admin(...)` instead and drop the app-level `csrf_config=`.

### Added

- `discover_specs`: an optional helper that walks a package's immediate subpackages and
  imports a `specs.py` from each one that has it, collecting the `ModelSpec` objects it
  declares. Lets a host with many domain modules keep a `specs.py` beside each one instead
  of one central file importing models from everywhere.
- This is discovery of hand-written spec files, not generation of specs — nothing infers a
  spec from a model. A subpackage with no `specs.py` is skipped silently, since a domain
  module may legitimately have no admin surface. A `specs.py` that exists but does not
  define `SPECS` (or a module/attribute name given via `module_name=` / `attribute=`), or
  whose `SPECS` is not an iterable of `ModelSpec`, raises immediately, naming the module. A
  slug collision across two discovered modules raises at discovery, naming both.
- `discovery.py` is the one module in the package permitted a dynamic import, scoped
  narrowly in `tests/test_boundary.py` and explained there.

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
