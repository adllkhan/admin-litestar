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
    config=AdminConfig(path="/admin"),
    specs=[INVOICE],
    auth=Auth(),
    audit=YourAuditSink(),
    cache=lambda request: your_cache,
    session_factory=async_sessionmaker(engine),
    csrf_secret=SECRET,
)

app = Litestar(
    route_handlers=[admin.router()],
    template_config=admin.template_config(),
    middleware=[admin.session_config(MemoryStore()).middleware],
)
```

That yields a login page, a gated sidebar shell, and list / detail / delete / CSV-export
routes for every spec that declares the matching capability — all under the single router
`admin.router()` returns. Static assets (the stylesheet, vendored HTMX) are served nested
inside it, at `<path><static_path>` (`/admin/static` by default); there is nothing else to
mount.

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

## Sorting

Click a column header. The order is a URL, so it survives a reload and a shared
link, and `Load more` and `Export CSV` both carry it. A sort is validated against
`list_columns` rather than trusted, so a hidden column named in a query string
falls back to the spec's `order_by` instead of ordering by it.

Keyset paging follows the chosen column, and the order is tie-broken by the primary
key: sorting by a non-unique column leaves rows arbitrarily ordered within a value,
and a cursor over an unstable order both skips and repeats rows.

## Filters

A declared filter renders as a segmented control — one connected object, `All`
plus one segment per value, the active one filled — with each value carrying how
many rows it holds:

```
STATUS  ┃ All 140 │ paid 48 │ pending 46 │ void 46 ┃
```

The counts are taken against the rest of the current view: the search and every
*other* filter apply, the column's own filter does not. So a number says what
clicking that segment would actually give you, rather than what the table holds in
total. Clicking the active segment clears it, so a filter is undone where it was
set.

The set of segments is fixed by what the column holds overall, and only the counts
respond to the view — a control whose options come and go as other filters change is
one you cannot learn. A value the current view excludes shows `0` and is rendered as
text rather than a link, since selecting it would leave nothing.

Segments are ordered by value, not by count, for the same reason. Each is a URL that
keeps the rest of the view, so filtering never drops the search or the sort and a
filtered list can be shared.

Several values can be on at once, which widens the filter rather than replacing it:
`?status=paid&status=pending` matches either, as `IN`. Clicking a selected segment
removes it.

An enumerated column offers its own declared values; anything else is asked what it
holds. A column with more than `FILTER_CHOICE_LIMIT` (40) values stays a text field
instead — a truncated list hides the rest with no way to reach them.

A **date or timestamp** column is asked "between" rather than "which of these", so it
renders as a pair of date fields — a year of distinct days is not a control. Either
end may be left open. An end given as a date covers that whole day: comparing `<=`
midnight would silently exclude every row in it. A malformed bound is ignored rather
than failing the page, because bounds arrive from URLs.

Every control on the page — sort header, filter segment, range form, paging trigger,
export link — is built from one `ListView` object, so none of them can disagree about
what is being shown. A form that owns part of the view (the search box, a range)
carries the rest as hidden fields, since a GET form replaces the whole query string.

## Bulk actions

Rows grow checkboxes when something can act on a selection — a declared `BulkAction`,
or the `DELETE` capability. The toolbar appears only while something is selected, and
says how many.

```python
bulk_actions=(
    BulkAction(label="Mark all paid", path="/admin/bulk-mark-paid"),
    BulkAction(label="Purge", path="/admin/purge", confirm=True, danger=True),
)
```

The selection posts as repeated `pk` fields, so a handler reads a list rather than
being called once per row. A path containing `{pk}` is rejected at construction — that
is a `RowAction`, not a bulk one.

`Delete selected` is built in wherever the spec declares `DELETE`. It loads and
deletes one record at a time and writes **one audit entry per record**: a trail that
answers "who deleted invoice 4821" must not depend on someone reconstructing which
batch it was in. A row that has already gone is skipped rather than failing the batch,
and an empty selection deletes nothing.

There is no `Filter` button: the search field submits itself on change, and a
visually hidden submit keeps implicit submission and no-script use working.

## Relations

A foreign key holds an integer, and nobody reads an admin to learn that invoice
4821 belongs to customer 12. Declare the relation and the column reads as the
related record, linked to it, and edits as a list of choices:

```python
INVOICE = ModelSpec(
    ...,
    list_columns=("id", "number", "customer_id", "total"),
    relations={"customer_id": Relation(model=Customer, label="name")},
)
```

Labels are resolved in one query per related model per page, never one per row. The
link target comes from whichever spec registers that model; where two specs expose
the same model, name the one you mean with `Relation(..., slug="...")`. A target
with more than `RELATION_OPTION_LIMIT` (200) rows is not offered as a select at
all — a truncated list of options hides records with no way to pick them — so the
field falls back to accepting a key.

## Row actions

`RowAction` puts host-defined buttons on every row. The admin renders them, formats
the record's key into the path, and carries a CSRF token on anything that posts;
what the button does is a route you write (a `CustomPage` handler is the usual
place).

```python
row_actions=(
    RowAction(label="Mark paid", path="/admin/mark-paid/{pk}", method="post"),
    RowAction(label="Void", path="/admin/void/{pk}", method="post",
              confirm=True, danger=True),
    RowAction(label="Receipt", path="/admin/receipt/{pk}"),
)
```

A click inside the actions cell does not open the record's dialog. `confirm=True`
asks first, in markup rather than a `confirm()`, so it is styleable and survives
scripting being off. A path without `{pk}` and a method other than get/post are
rejected at construction.

## Charts

Two forms ship, rendered server-side with no library and no runtime fetch:
`_bars.html` for magnitude across labelled categories and `_spark.html` for change
over time. `admin_litestar.charts` computes the geometry; the templates only place
it.

```python
from admin_litestar.charts import bars, spark

context = {
    "status_bars": bars([("paid", 46), ("pending", 47), ("void", 47)]),
    "per_day": spark([3, 9, 5, 14]),
}
```

Both draw in a single hue. That is a decision, not a shortcut: a bar whose category
is written beside it gains nothing from a second encoding, and this admin's six
group hues are *not* a valid categorical series palette — its azure and violet steps
differ by ΔE 1.3 under deuteranopia and 8.6 with full colour vision, which is fine
for nav accents that never sit adjacent and wrong for marks that do.

`bars()` refuses negative values rather than drawing them as short positives.
`spark()` returns `None` for fewer than two points, and the template says so
instead of drawing an empty box; a flat series is drawn down the middle, because a
constant is not a zero. The sparkline carries its shape as text in `aria-label`.

## Writing

Two capabilities cover writes. `EDIT` adds a form for an existing record, `CREATE` adds a
`New` button and a blank one. Neither exists unless the spec declares it, and the routes
404 rather than merely hiding a button.

```python
capabilities=frozenset({LIST, DETAIL, EDIT, CREATE, DELETE})
```

**What is writable.** Every column in `detail_columns` except the primary key — a rewritable
key would let one form address a different record. There is no second allow-list, so a
column you do not want written must not be in `detail_columns`: put it in `hidden_columns`
(detail only, never lists) or `excluded_columns` (never selected at all).

**Where it happens.** The record dialog gains an `Edit` button that swaps its own body for
the form; saving returns the record, and the table row behind the dialog is replaced
out-of-band so the list stops showing what you just changed. Without scripting the same URLs
are ordinary pages: `GET`/`POST` on `/m/<slug>/<pk>/edit` and `/m/<slug>/new`, answered with
a redirect after a successful write.

**Coercion and validation.** A form sends strings; columns want values. Each column is
classified from its type — integer, number, checkbox, date, datetime-local, select for an
enum, textarea for unbounded text — and the submitted string is coerced back. A field the
form never offered is ignored, so adding one to the request body writes nothing. Bad input
comes back as the same form with a per-field message and the values you typed, not the values
that were stored. A constraint the database enforces (a duplicate unique value, a missing
default) is reported in the form too, after a rollback, rather than as a 500.

**Notifications.** A write says so: `Record 141 created`, `Record 9 saved`, `Record 3 deleted`.
A redirect carries the message in the session and shows it exactly once; an HTMX save has no
navigation to carry it, so the message arrives out-of-band with the record. It fades after
five seconds, or stays put and dismissible under `prefers-reduced-motion`.

Writes are audited: `ACTION_CREATE` with the columns set, `ACTION_UPDATE` with the names that
actually changed, `ACTION_DELETE` as before. All of them go through the same CSRF layer and
the same auth gate as everything else.

## Opening a record

A row opens its record in a dialog over the blurred list, so scanning a table and reading one
row do not cost a navigation. The row is focusable and Enter does what a click does. Rows are
inert for a spec that does not declare `DETAIL`.

The dialog is a real `<dialog>` — Escape, focus trapping and `::backdrop` come from the
element rather than from script — and `Close` is a `method="dialog"` submit, so it works
without JavaScript running at all. The same URL opened directly, from a bookmark or a shared
link, renders the full detail page instead: the route answers an `HX-Request` with the dialog
and everything else with the page. `Open page` inside the dialog goes there.

Both the dialog and the page render `_detail_rows.html`, so a record cannot read differently
in one than the other.

The list page pages in place: `Load more` is a row at the end of the table body that swaps
itself for the next page plus a fresh trigger, so rows accumulate. Its URL carries the
search and filters currently applied. When the request arrives with an `HX-Request` header
the route answers with the rows fragment alone; the same URL opened directly renders the
whole page, so paging degrades to plain navigation with scripting off.

## Supplying specs

A host with many domain modules can pass its specs explicitly, as above, or keep a
`specs.py` beside each domain module and let `discover_specs` find them:

```python
# billing/specs.py
SPECS = (INVOICE, PAYMENT)

# users/specs.py
SPECS = (USER, ROLE)
```

```python
from admin_litestar import Admin, discover_specs

admin = Admin(config=..., specs=discover_specs("myapp"), auth=..., ...)
```

`discover_specs` walks `myapp`'s immediate subpackages and imports `<subpackage>.specs`
from each one that has it — a subpackage without one is skipped, since a domain module may
legitimately have no admin surface. It finds hand-written spec files; it does not generate
specs from a model. Which columns are hidden, which are excluded, and what is searchable
stay entirely your explicit declaration in each `specs.py` — guessing those from a schema
is what this package exists to replace. A `specs.py` that exists but omits `SPECS`, or
whose `SPECS` isn't an iterable of `ModelSpec`, raises immediately, naming the module. Pass
`module_name=` / `attribute=` to use a different file or attribute name.

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

## Themes

Three stylesheets ship, and `AdminConfig(theme=...)` picks which one the shell links:

| Theme | Look |
|---|---|
| `classic` (default) | Layered surfaces, a serif for titles, zebra tables, cards with shadow. Follows the OS light/dark preference. |
| `schematic` | The admin as a technical drawing: monospace throughout, graph-paper ground, a title-block header, dotted leaders in the nav, dimension lines on detail pages, corner marks framing the table. Follows the OS preference. |
| `black` | Strict monochrome, soft. No accent colour at all: each level of emphasis is the next surface up plus a hairline, grouping reads through a neutral ramp, and danger is dashed rather than red. Off-black ground, off-white type, one 4px rhythm, sentence case, nothing heavier than 600. Commits to one look and ignores the OS preference. |

All three carry the same class names, so a custom page written against one works under the
others, and all three define the six group hues, so the nav's hue coding survives whichever
is picked. A test asserts both of those per theme. An unknown theme name raises at
construction rather than serving a dead stylesheet link.

```python
AdminConfig(path="/admin", theme="schematic")
```

To ship a stylesheet of your own instead, override `base.html` and link it — the shell reads
`stylesheet_path`, which is the chosen theme's URL, but nothing stops a template from
ignoring it.

### The admin root

A successful login and the nav's brand link both go to the admin root. If no custom page
answers there, the admin redirects it to the first spec that declares `LIST` — so the root
is never a dead end, and a host that wants no landing page has to write nothing.

To own the root, give a page a handler mounted at `/`. An empty `slug` keeps it out of the
nav, which suits a landing page the brand link already reaches:

```python
class HomeController(Controller):
    path = "/"

    @get()
    async def index(self, admin_session: NamedDependency[AsyncSession]) -> Template:
        return Template("home.html", context={"tiles": await counts(admin_session)})

home = CustomPage(slug="", label="", group="Overview", handlers=[HomeController])
```

Root ownership is detected from the handler's path as well as the slug, so a landing page
that keeps a nav label while mounting at `/` still wins and does not collide with the
redirect. With no listable spec and no custom page, the root stays a 404.

## Authentication

The package owns the mechanism; you own the policy.

- `hash_password` / `verify_password` use `hashlib.scrypt` with `n=16384, r=8, p=1,
  dklen=32`. The encoding is 86 characters, so it fits a `String(128)` column. Anything not
  in that format fails verification — there is no fallback to another scheme.
- Login failures are counted per username **and** client IP, locking after 5 attempts for
  15 minutes. Deliberately separate from any lockout counter on your own user rows, so
  admin brute-force cannot lock someone out of your main application.
- An unauthenticated **page** request is redirected to the login form, carrying the URL it
  was trying to reach as a `next` parameter, so a bookmarked deep link survives logging in.
  An **HTMX** request gets `401` plus an `HX-Redirect` header instead, because a 401 body
  would otherwise be swapped into the page as content. Anything else — a fetch, a probe, a
  script — keeps the plain `401` it expects.
- `next` is validated, never trusted: it is honoured only when it is a path under the
  admin's own mount point. Absolute URLs, protocol-relative URLs, dot segments (encoded or
  not), backslashes, and the login and logout paths themselves are all discarded in favour
  of the admin root.
- Sessions are server-side over a store you supply. `AuthBackend.is_valid` is re-checked on
  every request, cached briefly, so revoking access takes effect in seconds rather than at
  session expiry.
- Session and CSRF cookies are marked `Secure` by default (`AdminConfig.secure_cookies`,
  default `True`). Set it to `False` only for local development or tests served over plain
  HTTP.
- CSRF protection is opt-in: pass `csrf_secret=` to `Admin(...)` and every mutating route
  under the admin's own path requires a token, via `CSRFMiddleware` attached to the admin's
  router — not app-wide, so a host's own routes are unaffected. Leaving it unset (the
  default) means no CSRF protection, matching a host that has deliberately declined it.
  Templates call `{{ csrf_token() }}` either way.

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
