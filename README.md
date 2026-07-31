# admin-litestar

A server-rendered admin panel for [Litestar](https://litestar.dev) applications backed by
SQLAlchemy. No build step, no JavaScript toolchain, no CDN at runtime — the CSS is
hand-written and HTMX is vendored as package data.

It knows SQLAlchemy and Litestar. It knows nothing about your schema, your authentication,
or where you keep your audit trail — those arrive through protocols you implement. A test
in this repository fails if the package ever imports a host application.

## Install

```bash
uv add admin-litestar
```

Requires Python 3.10+. Depends only on `litestar`, `sqlalchemy` and `jinja2`.

## Usage

Declare a `ModelSpec` per model, implement three small protocols, and mount what `Admin`
gives you.

```python
from litestar import Litestar
from litestar.stores.memory import MemoryStore

from admin_litestar import (
    Admin,
    AdminConfig,
    DETAIL,
    EXPORT,
    LIST,
    ModelSpec,
    hash_password,
    verify_password,
)

INVOICE = ModelSpec(
    model=Invoice,
    slug="invoice",
    label="Invoices",
    group="Billing",
    list_columns=("id", "reference", "issued_at"),
    detail_columns=("id", "reference", "note", "issued_at"),
    capabilities=frozenset({LIST, DETAIL, EXPORT}),
    order_by="id",
    searchable=("reference",),
)


class Auth:
    """Decides who may enter the admin, and whether they still may."""

    async def authenticate(self, session, username, password):
        user = await lookup(session, username)
        if user and verify_password(password, user.admin_password):
            return user
        return None

    def identity_of(self, user):
        return user.id

    async def is_valid(self, session, actor_id) -> bool:
        return await still_permitted(session, actor_id)


admin = Admin(
    config=AdminConfig(path="/admin", static_path="/admin-static"),
    specs=[INVOICE],
    auth=Auth(),
    audit=YourAuditSink(),
    cache=lambda request: your_cache,
    session_factory=async_sessionmaker(engine),
)

app = Litestar(
    route_handlers=[admin.router(), admin.static_router()],
    template_config=admin.template_config(),
    middleware=[admin.session_config(MemoryStore()).middleware],
    csrf_config=admin.csrf_config(SECRET),
)
```

That yields a login page, a gated sidebar shell, and list / detail / delete / CSV-export
routes for every spec that declares the matching capability.

## The column boundary

`ModelSpec` distinguishes three kinds of column, and the distinction is enforced where
statements are built rather than where values are rendered:

| Field | Behaviour |
|---|---|
| `list_columns` | Loaded and shown in list views |
| `detail_columns` | Loaded and shown in detail views |
| `hidden_columns` | Permitted in detail views, **never** loaded by a list query |
| `excluded_columns` | Never selected, rendered or exported, anywhere |

List queries use `load_only()` over `list_columns`, so a hidden column is absent from the
SQL itself. That matters when a column's SQLAlchemy type decrypts on load: a list page
neither pays the cost nor can leak the value, even if a template is wrong. `ModelSpec`
rejects contradictory declarations at construction, so a hidden column named in
`list_columns` — or an excluded column named as searchable or filterable — is an error you
get at import time, not a leak you find later.

## Search

`searchable` columns match with `ILIKE`. `exact_searchable` columns match by equality, and
`search_transform` is applied to the term first — which is how you search a keyed-digest
column without this package knowing anything about your hashing:

```python
ModelSpec(
    ...,
    exact_searchable=("iin_digest",),
    search_transform=your_digest_function,
)
```

Exact search takes precedence when both are declared, because a digest cannot be matched
partially.

## Pagination

Keyset, never `OFFSET`. The cursor is the last row's `order_by` value, coerced to the
column's Python type — dates and datetimes are parsed with `fromisoformat`. A malformed or
timezone-naive cursor is treated as absent and yields an unpaginated first page rather than
an error, because cursors arrive from URLs and URLs get edited.

## Custom pages

Generic tables cannot do everything. `CustomPage` lets a host contribute its own routes,
rendered inside the same shell and listed in the same nav:

```python
from admin_litestar import CustomPage

dashboard = CustomPage(
    slug="dashboard", label="Dashboard", group="Overview", handlers=[DashboardController]
)
```

Host templates take precedence over the package's, so `AdminConfig(template_dirs=(...))`
lets you override any template by name while extending `base.html`.

## Authentication

The package owns the mechanism; you own the policy.

- `hash_password` / `verify_password` use `hashlib.scrypt` with `n=16384, r=8, p=1,
  dklen=32`. The encoding is 86 characters, so it fits a `String(128)` column. Anything not
  in that format fails verification — there is no fallback to another scheme.
- Login failures are counted per username **and** client IP, locking after 5 attempts for
  15 minutes. Deliberately separate from any lockout counter on your own user rows, so
  admin brute-force cannot lock someone out of your main application.
- Sessions are server-side over a store you supply. `AuthBackend.is_valid` is re-checked on
  every request, cached briefly, so revoking access takes effect in seconds rather than at
  session expiry.
- CSRF protection covers every mutating route. Templates call `{{ csrf_token() }}`.

## Design

Dark, near-monochrome, one amber accent, monospace for identifiers — chosen because admin
data is mostly ids, hashes, addresses and timestamps, which align and scan far better in a
monospaced column. Light and dark both ship, honouring `prefers-color-scheme` with an
explicit `data-theme` override.

`ModelSpec` validates at construction: unknown column names, a hidden column listed in
`list_columns`, an excluded column named as searchable, or an unknown capability all raise
immediately rather than producing an admin that quietly misbehaves.

## Status

Early. The API has one real consumer, so every protocol here is a considered guess about
the second one. Expect `0.x` releases to move interfaces, and pin exactly if that matters.

`admin_litestar.__all__` is the compatibility promise. Deeper import paths work but carry
none — see [ARCHITECTURE.md](ARCHITECTURE.md).

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — layout, layering, where each guarantee is enforced
- [CHANGELOG.md](CHANGELOG.md) — what moved and when
- [RELEASING.md](RELEASING.md) — how a release is cut

## Licence

MIT. See [LICENSE](LICENSE).
