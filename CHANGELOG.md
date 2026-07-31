# Changelog

Notable changes to `admin-litestar`. Versions follow semantic versioning, with the
caveat that `0.x` carries no stability promise — see the note under Unreleased.

## Unreleased

### Added

- CI now covers Python 3.10 through 3.14, plus 3.15 as a reporting-only job. 3.15 is
  currently an alpha, so a failure there does not block; the suite passes on it today.
  `requires-python` stays `>=3.10` — nothing in the package needs a newer interpreter, and
  the floor is verified rather than assumed.
- `CAPABILITIES`, `LIST`, `DETAIL`, `DELETE` and `EXPORT` are now exported, so a host
  has something to import instead of spelling capability names as bare strings.
- `ModelSpec` rejects unknown capability names at construction. Previously a typo such
  as `capabilities=frozenset({"lst"})` constructed successfully and produced a model
  whose routes silently did not exist.
- `__version__`, resolved from the installed distribution metadata.
- `ARCHITECTURE.md`, documenting the layout, the dependency direction, and where each
  guarantee is enforced.
- A test pinning the public API surface, so an export appearing or disappearing shows up
  in a diff rather than in a consumer's traceback.

### Fixed

- CI's Python matrix was decorative. `uv python install X` only downloads that
  interpreter; the plain `uv sync` that followed picked any interpreter satisfying
  `requires-python`, which measurably resolved to 3.14 on a machine where 3.10 had just
  been installed. CI would have reported four passes across 3.10–3.13 while testing none
  of them. Both workflows now pin `UV_PYTHON`, and CI asserts the running interpreter is
  the matrix one before testing. Verified: the suite does pass on 3.10, the declared floor.

### Changed

- **Breaking:** `Registry`, `Revalidator` and `require_actor` are no longer exported from
  the top-level package. A host never constructs any of them — `Admin` builds and wires
  all three — and exporting them promised compatibility for internal wiring. They remain
  importable from their own modules, which carry no compatibility promise.
- The host-import boundary test is now an allowlist rather than a denylist: the package
  may import only the standard library, its three declared dependencies, and itself. The
  previous version named one consumer's top-level packages, which would have caught
  nothing for anyone else. It now parses with `ast` rather than matching text, so
  multi-line, aliased, comma-separated and in-docstring forms are all handled.

### Notes

The API has one real consumer, so every protocol here is a considered guess about the
second. Expect `0.x` releases to move interfaces. Pin exactly if that matters to you.

## 0.1.0

Initial development. Not released to an index.

- `Admin` / `AdminConfig`: assembles the router, template, session and CSRF
  configuration a Litestar host mounts.
- `ModelSpec` / `Registry`: declarative per-model configuration with validation at
  construction time.
- Generic list, detail, delete and CSV-export routes driven entirely by specs.
- A column boundary enforced where statements are built: `hidden_columns` never load in
  list queries, `excluded_columns` never load anywhere.
- Keyset pagination with type-aware cursor coercion, including `fromisoformat` parsing
  for date and datetime order columns.
- Search: `ILIKE` over `searchable`, equality over `exact_searchable` with an optional
  `search_transform` so a host can query a keyed-digest column.
- `AuthBackend`, `AuditSink` and `CacheBackend` protocols; scrypt password hashing;
  server-side sessions; per-username-and-IP login lockout; CSRF on mutating routes;
  session revalidation so revocation takes effect in seconds.
- `CustomPage` for host-supplied pages, with host template directories taking
  precedence over the package's.
- The "Instrument" design system, shipped as package data with vendored HTMX and no
  build step.
