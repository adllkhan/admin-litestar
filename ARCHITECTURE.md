# Architecture

## Repository layout

```
admin-litestar/              distribution name — hyphens, per PEP 503 normalisation
├── pyproject.toml
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
├── RELEASING.md
├── LICENSE
├── .github/workflows/       ci.yml (tests, build, wheel contents), release.yml (tag → PyPI)
├── src/                     see "Why src" below
│   └── admin_litestar/      import name — underscores; identifiers cannot contain hyphens
│       ├── __init__.py      the entire public API; nothing deeper is a supported import
│       ├── constants.py     every literal in the package
│       ├── protocols.py     what a host implements
│       ├── spec.py          ModelSpec, Registry
│       ├── queries.py       statement builders — where the column boundary is enforced
│       ├── render.py        cell formatting, request-shape helpers
│       ├── export.py        streaming CSV
│       ├── passwords.py     scrypt hash/verify
│       ├── auth.py          session gate, revalidation, lockout
│       ├── pages.py         CustomPage
│       ├── admin.py         Admin, AdminConfig — the assembly a host mounts
│       ├── controllers/     session (login/logout), models (generic CRUD routes)
│       ├── templates/       Jinja templates, shipped as package data
│       ├── static/          admin.css and vendored htmx.min.js, package data
│       └── py.typed         marks the package typed for consumers' type checkers
└── tests/                   throwaway models; imports no host application
```

## Why `src`

Python puts the working directory on `sys.path`. In a flat layout the import package sits
beside `tests/` at the repo root, so `import admin_litestar` resolves to the **source
tree** whether or not the package is correctly installed. Tests then pass while the built
artifact is broken.

That matters more here than in a pure-code library, because four of the things this
package ships are not `.py` files: the templates, the stylesheet, the vendored HTMX, and
`py.typed`. Under a flat layout, omitting any of them from the wheel is invisible — the
tests read them from the source tree and pass. Under `src`, the source tree is not
importable, so the suite exercises the installed package and a missing asset fails
immediately.

The CI wheel-contents assertion still exists, because `src` proves the *paths* resolve
while the assertion proves the *files shipped*. Different failures.

## Layers, and which way dependencies point

```
             host application
                    │  constructs
                    ▼
  admin.py ───────────────────────► Admin, AdminConfig
     │  wires together
     ├──► controllers/  ──► queries.py ──► spec.py
     │                      render.py      constants.py
     │                      export.py
     ├──► auth.py       ──► protocols.py
     └──► templates/ static/
```

Rules that hold, and must keep holding:

- **Nothing imports the host.** Enforced by `tests/test_boundary.py`, an allowlist
  permitting only the standard library, the three declared dependencies, and this package.
- **`constants.py` imports nothing.** It is the leaf. Every literal lives there so no
  magic value appears at a call site.
- **`spec.py` knows nothing about Litestar.** Data plus validation over SQLAlchemy models,
  which is why `ModelSpec` is testable without an app.
- **`queries.py` knows nothing about HTTP.** It returns `Select` objects, which is why the
  column boundary can be tested by compiling SQL rather than by making requests.
- **`admin.py` is the only module that assembles.** If a change makes another module reach
  across layers to wire something, the wiring belongs here instead.
- **Only `__init__.py` is a supported import path.** `from admin_litestar.queries import
  list_statement` works, but the compatibility promise is `__all__` and nothing deeper.

## Where the guarantees live

Each substantive promise is enforced in exactly one place, deliberately:

| Guarantee | Enforced in | Not relied on |
|---|---|---|
| A list query never loads a hidden column | `queries.list_statement` via `load_only` | templates |
| An excluded column appears in no query | `spec.ModelSpec.__post_init__` + `queries` | reviewer attention |
| An export cannot contain a hidden column | `export.csv_rows` reads `spec.list_columns` | callers remembering to filter |
| A capability typo fails loudly | `spec.ModelSpec.__post_init__` | the route appearing to work |
| A revoked admin loses access in seconds | `auth.Revalidator` as `before_request` | session expiry |
| The package cannot reach into its host | `tests/test_boundary.py` allowlist | convention |
| The public surface changes deliberately | `tests/test_api.py` | code review alone |

One enforcement point per promise is what makes each testable by compiling a statement or
parsing an AST, instead of hoping an integration test happens to cover the path.

## Extension points for a host

A host supplies four things and gets an admin:

1. **`ModelSpec` per model** — which columns, which are hidden, which are excluded, what is
   searchable, which capabilities exist.
2. **`AuthBackend`** — who may log in, what identity to store, whether they still qualify.
3. **`AuditSink`** — where admin actions are recorded.
4. **`CacheBackend`** and a **session factory** — infrastructure the package borrows rather
   than owns.

Anything a generic table cannot express becomes a `CustomPage`: the host's own Litestar
handlers, hosted in the admin's router, listed in its nav, rendering templates that extend
the package's `base.html`. Host template directories take precedence, so any template can
be overridden by name.

## Invariants for anyone changing this

- Adding a model to a host's admin stays one `ModelSpec` entry. If a change requires
  editing package code to support a host's model, the abstraction has leaked.
- A new literal goes in `constants.py`, not at its call site.
- A new guarantee gets one enforcement point and a test that has been **observed to fail**.
  A boundary test nobody has seen fail is not evidence of anything.
- The dependency list stays `litestar`, `sqlalchemy`, `jinja2`. `tests/test_boundary.py`
  asserts it, and it is the reason the package can claim to be host-agnostic.
- The suite runs under `-W error`. A dependency's deprecation is something to see now
  rather than at a major-version bump.
- Public API changes go through `tests/test_api.py`, so they appear in a diff.
