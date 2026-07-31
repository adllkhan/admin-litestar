# Releasing

## One-time setup

### Trusted publishing

Prefer OIDC over a long-lived API token: no secret is stored anywhere, and a leaked token
cannot be replayed because there isn't one.

Because the project does not exist on either index yet, both are configured as a **pending
publisher** — which is how you claim a name and authorise a publisher in one step, before a
first upload exists.

Do this **twice**, once on each index:

- TestPyPI → <https://test.pypi.org/manage/account/publishing/>
- PyPI → <https://pypi.org/manage/account/publishing/>

| Field | TestPyPI | PyPI |
|---|---|---|
| PyPI Project Name | `admin-litestar` | `admin-litestar` |
| Owner | `adllkhan` | `adllkhan` |
| Repository name | `admin-litestar` | `admin-litestar` |
| Workflow name | `release.yml` | `release.yml` |
| Environment name | `testpypi` | `pypi` |

The GitHub environments `testpypi` and `pypi` already exist on the repository. Add a
required reviewer to `pypi` — a tag push otherwise publishes with no further confirmation,
and a published version cannot be withdrawn.

### Rehearse on TestPyPI before the first tag

The workflow accepts a manual run so the whole path — build, wheel checks, clean-install
check, and the OIDC handshake itself — can be exercised without burning a version number:

```bash
gh workflow run release.yml -R adllkhan/admin-litestar -f target=testpypi
gh run watch -R adllkhan/admin-litestar
```

Then confirm the artifact is actually installable from the index, not merely uploaded:

```bash
uv venv /tmp/from-testpypi
VIRTUAL_ENV=/tmp/from-testpypi uv pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ admin-litestar
/tmp/from-testpypi/bin/python -c "import admin_litestar as al; print(al.__version__)"
```

The extra index is required because TestPyPI does not mirror real dependencies, so
`litestar` and `sqlalchemy` have to resolve from PyPI.

TestPyPI shares PyPI's rule that a version cannot be re-uploaded. If a rehearsal needs
repeating, bump to a local or dev suffix — `0.1.0.dev1` — rather than trying to overwrite.

## Every release

### 1. Decide the version

`version` in `pyproject.toml`. **A version can never be re-uploaded to PyPI**, even after
deleting it — a bad `0.1.0` means `0.1.1`, never a corrected `0.1.0`.

While the API is still moving, stay on `0.x`: under semantic versioning `0.y.z` carries no
stability promise, and the protocols here will change as real consumers appear.

### 2. Check the build carries its data

The templates, stylesheet, vendored HTMX and `py.typed` are package data, not code. A
packaging regression is invisible to the test suite and only surfaces for whoever installs
the result, so assert on the artifact itself:

```bash
rm -rf dist && uv build
python - <<'PY'
import glob, sys, zipfile
wheel = glob.glob("dist/*.whl")[0]
names = zipfile.ZipFile(wheel).namelist()
required = [
    "admin_litestar/py.typed",
    "admin_litestar/static/admin.css",
    "admin_litestar/static/htmx.min.js",
    "admin_litestar/templates/base.html",
    "admin_litestar/templates/nav.html",
]
missing = [r for r in required if r not in names]
# sys.exit(str) prints the string and exits 1, so passing a success message to it
# fails the command. Exit only on the failure path.
if missing:
    sys.exit(f"wheel missing: {missing}")
print(f"{wheel}: all required assets present")
PY
```

CI runs this on every push, but run it before tagging too — a release is the one time the
artifact matters more than the tests.

### 3. Verify the wheel installs and imports somewhere clean

Testing the source tree does not test the wheel. Install the built artifact into a throwaway
environment with none of the development context:

```bash
uv venv /tmp/rel-check && VIRTUAL_ENV=/tmp/rel-check uv pip install dist/*.whl
/tmp/rel-check/bin/python -c "
import admin_litestar as al
from admin_litestar.templates import TEMPLATES
from admin_litestar.static import STATIC
assert (STATIC / 'admin.css').exists(), 'stylesheet missing from the installed wheel'
assert (TEMPLATES / 'base.html').exists(), 'templates missing from the installed wheel'
print(f'{len(al.__all__)} exports, assets resolve')
"
```

This catches the failure mode that matters most here: paths that resolve from a source
checkout but not from `site-packages`.

### 4. TestPyPI first, for a new name or a first release

```bash
uv publish --publish-url https://test.pypi.org/legacy/ dist/*
uv venv /tmp/test-install && VIRTUAL_ENV=/tmp/test-install uv pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ admin-litestar
```

The extra index is needed because TestPyPI does not mirror real dependencies.

### 5. Tag and let CI publish

```bash
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```

`release.yml` builds on the tag and publishes through the trusted publisher. Tagging is the
release trigger, so never move or delete a tag that has published — the version is already
frozen on PyPI, and the tag is the only record of what produced it.

## Consuming an unreleased version

An application that needs changes not yet on PyPI can point at a checkout without changing
its declared dependency:

```toml
dependencies = ["admin-litestar>=0.1.0"]

[tool.uv.sources]
admin-litestar = { path = "../admin-litestar", editable = true }
```

Keep that override out of what CI resolves, so a fresh clone and CI test against the
published artifact while local work stays fast. Do not leave it enabled indefinitely: it
hides the publish-then-bump cost that consumers actually pay.
