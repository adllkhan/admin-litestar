# Changelog

Notable changes to `admin-litestar`. Versions follow semantic versioning, with the caveat
that `0.x` carries no stability promise — see the note at the end of 0.1.0.

## 0.4.0 — 2026-08-04

### Added — bulk actions

Rows grow checkboxes wherever something can act on a selection: a declared
`BulkAction`, or the `DELETE` capability. The toolbar appears only while something is
selected and says how many, because an empty toolbar is a control that does nothing
taking the space of one that does. The checkboxes are real form fields tied to the
form by `id` rather than by nesting — a form cannot wrap a `tbody`, and wrapping the
table would break the row-click behaviour.

`Delete selected` ships built in. It loads and deletes one record at a time and writes
one audit entry per record rather than one for the batch: a trail answering "who
deleted invoice 4821" must not depend on reconstructing which batch it was in, and a
bulk `DELETE` statement would skip the model's own cascades and events. A record that
has already gone is skipped rather than failing the rest, and an empty selection
deletes nothing.

Host bulk actions post the selection as repeated `pk` fields, so a handler reads a
list. A path containing `{pk}` is rejected at construction — that is a `RowAction`.

### Added — filters hold several values, and dates are ranges

A filter matched one value. Selecting a second now widens it rather than replacing it:
`?status=paid&status=pending` is `IN`, verified against the data as 46 + 47 = 93 rows.
Clicking a selected segment removes it.

A date or timestamp column is asked "between" instead, as a pair of date fields, since
a year of distinct days was never a list anyone could use. Either end may be left
open. An end given as a date covers that whole day — compared as `<=` midnight it
would silently exclude every row in the day it names, which reads as missing data
rather than an off-by-one. Bounds get their own coercion rather than the cursor rule:
a cursor is a value this admin produced, so a naive datetime against an aware column
means something went wrong and is discarded, while a bound is a date a person typed
and the only useful reading is UTC. A malformed bound is ignored rather than failing
the page.

### Changed — one object builds every URL on a list page

Sort headers, filter segments, the range forms, the paging trigger and the export link
were each assembling query strings in Jinja. That worked while a filter held one value
and stopped being honest the moment one could hold several. All of them now come from a
single `ListView`, which also means they cannot disagree about what is being shown. A
form that owns part of the view carries the rest as hidden fields, since a GET form
replaces the whole query string: searching would otherwise clear the filters, and
setting a date range would clear the sort.


### Added — sortable columns

Ordering was one column per spec, hardcoded descending, while every theme drew
headers that looked clickable. Clicking one now sorts by it and clicking again
flips it. The order lives in the URL, so it survives a reload and a shared link,
and both `Load more` and `Export CSV` carry it.

A sort is validated against `list_columns` rather than trusted: a hidden column
named in a query string falls back to the spec's `order_by`. Keyset paging follows
the sorted column, and the order is now tie-broken by the primary key — sorting by
a non-unique column left rows arbitrarily ordered within a value, and a cursor over
an unstable order both skips and repeats rows.

### Fixed — export ignored the view it was launched from

`Export CSV` sits in the same toolbar as the search box and the filters, and sent
none of them to the query: a filtered view downloaded the whole table, up to the
10 000-row export cap. Nobody checks a download against the page, so this was wrong
quietly. The export now takes the same search, filters and ordering as the list, and
the audit entry records them beside the row count rather than only how many rows
left the building.

### Changed — filters are a segmented control with counts, and the Filter button is gone

A filter was a text box, which asks the reader to guess at spellings that exist. It
is now a segmented control: one connected object per filter, `All` plus a segment per
value, the active one filled, and each segment carrying how many rows it holds.

The counts are real facet counts — taken with the search and every *other* filter
applied, and without the column's own — so a number says what clicking that segment
would give you rather than what the table holds in total. Clicking the active segment
clears it. Each segment is a URL carrying the rest of the view, so filtering never
drops the search or the sort, and a filtered list can be shared.

The segment set is fixed by what the column holds overall, and only the counts
respond to the view. A first pass had the counts decide the segments too, which meant
picking one filter made another filter's options vanish — a control that reshapes
itself under the reader. A value the current view excludes now shows `0` and renders
as text rather than a link, since selecting it would leave nothing. Ordering is by
value, never by count, for the same reason.

An enumerated column offers its own declared values; anything else is asked what it
holds. A column with more than `FILTER_CHOICE_LIMIT` (40) values stays a text field
rather than showing a truncated set that hides the rest.

The `Filter` button is gone with the dropdown that needed it: the search field
submits on change, and a visually hidden submit button keeps implicit submission —
which a browser withholds from a form with several text fields and no submit — and
no-script use working.

### Added — foreign keys read and edit as records

A key column rendered as an integer, and the edit form asked for one by hand.
`ModelSpec.relations` maps a column to a `Relation`, after which the cell reads as
the related record's label, links to it, and the form offers a list of choices.

Labels are resolved in one query per related model per page rather than one per row.
The link target comes from whichever spec registers that model, and `Relation.slug`
settles it where two specs expose the same one — an ambiguity a test caught by
registering the same model twice. A target with more than `RELATION_OPTION_LIMIT`
(200) rows is not enumerated at all: a truncated select hides records with no way to
pick them, so the field falls back to accepting a key.

### Added — row action buttons

`RowAction` puts host-defined buttons on every row: the admin renders them, formats
the record's key into the path, and carries a CSRF token on anything that posts,
while the route belongs to the host. A click inside the actions cell does not also
open the record's dialog — filtered in the trigger rather than with an inline
`stopPropagation`. `confirm=True` asks first, in markup, so it is styleable and
works with scripting off. A path without `{pk}`, or a method other than get or post,
is rejected at construction.

### Added — charts, without a charting library

`admin_litestar.charts` computes the geometry and two templates place it:
`_bars.html` for magnitude across labelled categories, `_spark.html` for change over
time. No build step, no CDN, no runtime fetch — the same promise as the rest of the
package.

Both draw in a single hue, which is a decision rather than a limitation. Running the
palette validator on this admin's six group hues as a categorical series palette
fails: the azure and violet steps differ by ΔE 1.3 under deuteranopia and 8.6 with
full colour vision. That is fine for nav accents, which never sit adjacent, and
wrong for marks that do — and a bar whose category is written beside it needs no
second encoding anyway.

The edge cases are answered rather than left to render oddly: `bars()` refuses
negative values instead of drawing them as short positives, all-zero data draws no
bars rather than dividing by zero, `spark()` returns `None` below two points so the
template can say why, and a flat series is drawn down the middle because a constant
is not a zero. The sparkline states its shape in `aria-label`.

### Changed — the sidebar footer is just the button

The session label and the rule above it are gone; the logout control sits alone at
the bottom of the rail.


### Added — records can be edited and created, not only read and deleted

The admin had no write path but delete. A spec could declare four capabilities, none of which
let anyone change a value: `EDIT` and `CREATE` did not exist, there was no form, no update
route, and no notion of which columns were writable. Answering "why can't I modify data" with
"it was never built" is the honest version, so it is built here.

`EDIT` adds a form for an existing record and `CREATE` a blank one, each gated and 404ing when
the spec does not declare it. Editable means every column in `detail_columns` except the
primary key — a rewritable key would let one form address a different record — so `EDIT` grants
exactly what the detail view already shows. There is deliberately no second allow-list:
`hidden_columns` and `excluded_columns` remain the way to keep a column out of reach, and a
column added to `detail_columns` later becomes writable, which is worth knowing.

The form lives in the dialog a row opens: `Edit` swaps the body in place, and saving returns
the record along with an out-of-band copy of its own table row, so the list behind the dialog
stops showing the old value without a reload. Without scripting the same URLs are ordinary
pages answered with a redirect. New `forms.py` is the single place a submitted string becomes
a column value: each column is classified from its type (integer, number, checkbox, date,
datetime-local, select for an enum, textarea for unbounded text) and coerced back, with a
timezone-aware column reading a naive `datetime-local` value as UTC because the control cannot
send an offset. Only editable columns are read, so a field the form never offered cannot be
written by adding it to the request body. Rejected input returns the form with a per-field
message and the values that were typed, at 200 rather than 422, because HTMX does not swap an
error status and a form nobody can see is worse than an unfussy status code.

### Fixed — a constraint violation on write was a 500

Found while creating a record against SQLite: the insert failed its NOT NULL check and the
admin answered with `Internal Server Error`. A duplicate unique value or a broken foreign key
would have done the same. A constraint violation is a statement about the submitted values, so
`IntegrityError` is now caught at an explicit flush, the session rolled back — after a failed
flush it can accept nothing else, and the commit `Admin` performs on return would fail the same
way — and the form comes back carrying what the database objected to.

### Added — a write reports itself

`Record 141 created`, `Record 9 saved`, `Record 3 deleted`. A redirect carries the message in
the session and clears it on render, so it shows on exactly one page; an HTMX save has no
navigation to carry it, so it arrives out-of-band beside the record. The message fades after
five seconds through CSS rather than a scheduled removal, and under
`prefers-reduced-motion` — where the fade is suppressed — it stays visible and dismissible
instead of never leaving.


### Added — a row opens its record in a dialog

List rows were inert cells. A spec could declare `DETAIL` and render a perfectly good detail
page that nothing linked to, reachable only by typing its URL — so the obvious gesture, click
the row you are reading, did nothing.

A row now fetches its own record into a dialog over the blurred list. It is focusable and
Enter does what a click does, so the gesture is not mouse-only, and rows stay inert for a spec
that declares no detail route. The dialog is a real `<dialog>`, which is what makes Escape,
focus trapping and the blurred `::backdrop` free rather than scripted, and `Close` is a
`method="dialog"` submit that needs no JavaScript at all. The script that remains does the two
things the element cannot do for itself: open the dialog when the fragment lands, and close it
on a click outside the content. It deliberately does not remove the closed dialog afterwards —
a dialog without `open` is `display: none`, the next row's swap replaces it, and the tidier
`close` hook turned out not to be observable in every engine.

The detail route answers an `HX-Request` with `_modal.html` and everything else with the full
page, so a bookmark or a shared link still opens a page of its own, and `Open page` inside the
dialog goes there. Both render the new `_detail_rows.html`, so one record cannot read
differently in the two places.

The list projection now includes the primary key even when `list_columns` omits it: a table
showing a name and hiding the id could not otherwise name the record its own row links to.

### Changed — the nav rail is fixed, and its footer sits at the foot

The rail scrolled away with the page, and the logout control trailed whatever the last nav
group happened to be, so its position depended on how many models a host registered. The rail
is now sticky and viewport-tall, and the footer is pushed to the bottom of it with the session
label centred above a full-width control. On a long list this is also what keeps logout on
screen at all: pinning the footer inside a rail that stretched to the content height would
have parked it thousands of pixels below the fold.

### Added — two more themes, and `AdminConfig.theme` to choose one

`schematic` draws the admin as a technical drawing rather than a dashboard. One typeface,
monospace, sized and tracked rather than swapped. No cards, no shadows, no radius, no zebra:
structure is carried by rules, by corner marks framing the table as a drawn field, and by a
graph-paper ground. The page header is a title block — the cartouche a drawing carries in its
corner. Nav entries run to dotted leaders like an index. Detail rows are dimension lines,
label to value across a leader with the value ruled underneath. Status chips are bracketed
rather than pilled. Dark is the same drawing on drafting film: lines lighten, ground darkens.

`black` is strict monochrome, and soft about it. No accent colour anywhere: what would be a
hue elsewhere is a step in a neutral ramp, and what would be a highlight is a lift — each
level of emphasis is the next surface up plus a hairline, never an inversion. Nothing is pure
black or pure white, so hairlines stay visible and long sessions stay comfortable. Strict is
the grid rather than the volume: one 4px spacing rhythm, one radius pair, one ramp, sentence
case, no weight above 600. Danger is dashed, since a monochrome scheme has no red to borrow
and a hatch shouts. It declares `color-scheme: dark` and deliberately ignores the OS light
preference, because a monochrome scheme inverted for daylight is a different design rather
than the same one lightened; a test asserts that, so it reads as a choice.

`classic` is the 0.3.0 look and stays the default, so nothing changes for an existing host.
All three stylesheets carry the same class names and all three define the six group hues, so
a host-authored page written against one renders under the others — asserted per theme in
`tests/test_themes.py`, along with reduced-motion support. `AdminConfig(theme=...)`
takes a key of `admin_litestar.constants.THEMES`, not a filename; an unknown name raises at
construction rather than serving a dead stylesheet link. `base.html` now links
`stylesheet_path` instead of a hard-coded `admin.css` — a host that overrode `base.html`
before this keeps working, and keeps its hard-coded link.

### Fixed — an anonymous visitor got a bare 401 instead of the login form

`require_actor` raises `NotAuthorizedException` for every caller alike, and nothing
translated that into something a browser can act on. Opening any admin URL without a session
— the bookmarked root, a deep link someone shared — produced a 401 error page with no form
on it and no way to reach one. Present since 0.1.0.

The admin's router now carries an exception handler for `NotAuthorizedException` that answers
according to what the caller can use. A page request (`GET`/`HEAD` asking for `text/html`)
gets `303` to the login form with the requested URL, query string included, in a `next`
parameter. An HTMX request gets `401` with an `HX-Redirect` header, because a 401 body would
otherwise be swapped into the page as content. Everything else keeps the plain JSON `401` it
expects, so scripts and probes are unaffected. The handler is scoped to the admin's own
router, leaving a host's other 401s alone.

`next` is carried through the form and honoured after a successful login, but validated
rather than trusted, since it arrives from a URL anyone can hand an admin: only a path under
the admin's own mount point is accepted. Absolute and protocol-relative URLs, `://`,
backslashes, dot segments (`/admin/../../elsewhere`, which passes a prefix test but resolves
outside the admin in the browser that receives the header) and their percent-encoded forms,
sibling paths that merely share a prefix (`/adminlookalike`), and the login and logout paths
themselves are all refused in favour of the admin root.

### Fixed — every login landed on a 404 unless the host wrote a landing page

`SessionController` redirects to `{admin_path}/` after a successful login, and `nav.html`
points the brand link at the same URL — but the package never registered a route there. The
only thing that could answer was a host-contributed page, which `CustomPage`'s docstring
mentioned in passing and the README never asked for. A host that mounted the admin and
followed the README exactly therefore sent every fresh login, and every brand-link click, to
a 404. Present since 0.1.0.

The admin now registers a root route that redirects to the first spec declaring `LIST`,
so the root works with no host effort. A custom page still wins whenever one answers there:
ownership is read from the handler's path as well as from an empty `slug`, so a landing page
that keeps its nav label while mounting at `/` takes the root without colliding with the
redirect — two handlers on one path is a Litestar startup error, not a silent shadowing.
With no listable spec and no custom page there is nowhere to send the caller, so nothing is
registered and the root stays a 404. The route sits inside the gated router, so an anonymous
caller gets 401 rather than a redirect naming a model. README documents the whole behaviour
under "The admin root".

## 0.3.0 — 2026-08-03

### Fixed — `Load more` never loaded anything (0.1.0, 0.2.0)

The paging button was rendered after the `.wrap` div and carried
`hx-target="closest .wrap"`. HTMX's `closest` matches ancestors only, and the button had no
`.wrap` ancestor, so the target never resolved and clicking did nothing at all — every list
view was capped at the first 50 rows with no way forward.

Two further defects sat behind it, and would have surfaced the moment the selector was
corrected: the paging URL was answered with `list.html`, a whole document, which swapped
into the page would have nested a second nav and stylesheet link inside the table; and
`outerHTML` on the table container *replaced* the rows on screen instead of adding to them,
so a working button would have discarded page one on the way to page two. The URL also
dropped the active search and filters, paging from a different result set than the one
being read.

`Load more` is now a row at the end of the table body that targets `closest tr` and swaps
itself for the next page plus a fresh trigger — the documented HTMX click-to-load shape, and
the reason rows now accumulate in the existing `tbody`. Its URL carries the current search
and filters. The route answers an `HX-Request` for a cursor with the new `_rows.html`
fragment; the same URL without that header still renders the full page, so paging degrades
to plain navigation when scripting is off.

### Changed — the interface is larger, and no longer one flat tone

The stylesheet was tuned for density: 12px body text, 3px nav padding, hairline separators
and a single gold accent over one background colour. Everything read at the same weight,
so nothing stood out.

The scale moves up — 14px body text, 13px monospace in tables and detail rows, larger
controls and touch targets, a 224px nav rail — and the palette gains depth: a distinct
rail tone behind the nav, a surface tone for cards and tables, a raised tone for zebra
rows, and hue-tinted borders instead of neutral grey. Three type roles now carry the
hierarchy where one did before: a system serif for the brand and page titles, the system
sans for chrome, monospace for data.

Nav groups are hue-coded. Each group in the sidebar takes one of six hues, and the pages
belonging to it pick that hue up again in the page header dot, the active nav marker, the
table header rule and the detail card — so the group a model lives in is visible from
anywhere in the admin. Stat tiles cycle the same six hues automatically, no host markup
change needed. Every accented rule reads a `--hue` custom property that falls back to the
accent, so host-authored pages inherit the scheme for free.

Also: list and detail pages gained a header with a group eyebrow above the title, empty
result sets say so instead of rendering a bare table, the login form is a card with a
proper heading, `:focus-visible` rings are drawn everywhere, `prefers-reduced-motion` is
respected, and below 860px the rail folds into a top strip with the page header stacking.
Both themes were rebuilt in step. No new dependency, no webfont, no CDN — the stylesheet
is still hand-written and the font stacks are the ones already on the machine.

Class names are unchanged, and new ones (`.page`, `.pad`, `.filters`, `.nav-group`,
`.title`, `.eyebrow`) are additive. Host templates that reuse `.btn`, `.tbl`, `.stat`,
`.chip`, `.tabs`, `.split` or `.pane` keep working, restyled.

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
