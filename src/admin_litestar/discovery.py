"""Discovery of hand-written spec modules across a package's subpackages.

This is discovery, not generation: nothing here infers a ``ModelSpec`` from a
model. It only imports modules a host already wrote and collects what they
declared. Building the import target from a name found at runtime is
unavoidable for that, which is why this module — and only this module — is
exempted from the package's ban on dynamic imports; see
``tests/test_boundary.py`` for the scope of that exemption.
"""

from __future__ import annotations

import pkgutil
from importlib import import_module
from typing import TYPE_CHECKING

from .constants import DEFAULT_SPECS_ATTRIBUTE, DEFAULT_SPECS_MODULE_NAME
from .spec import ModelSpec

if TYPE_CHECKING:
    from types import ModuleType


def discover_specs(
    package: str,
    *,
    module_name: str = DEFAULT_SPECS_MODULE_NAME,
    attribute: str = DEFAULT_SPECS_ATTRIBUTE,
) -> tuple[ModelSpec, ...]:
    """Collect hand-written ``ModelSpec`` objects from a package's subpackages.

    Imports ``package``, then walks its immediate subpackages and, for each
    one, attempts to import ``<subpackage>.<module_name>``. A subpackage with
    no such module is skipped: a domain module may legitimately have no admin
    surface. A module that exists but does not define ``attribute``, or whose
    ``attribute`` is not an iterable of :class:`ModelSpec`, is an error —
    someone created the file meaning to declare something, and silently
    ignoring it would reintroduce the fail-open behaviour this package exists
    to avoid.

    Args:
        package: Dotted name of the package to walk. It is imported first, so
            it must itself be importable.
        module_name: Name of the module looked for inside each subpackage.
        attribute: Name of the module-level attribute expected to hold the
            specs.

    Returns:
        The collected specs as a tuple. Subpackages are visited in name
        order, so the result does not depend on filesystem iteration order;
        specs declared within one module keep their declaration order.

    Raises:
        AttributeError: A discovered module does not define ``attribute``.
        TypeError: A discovered ``attribute`` is not an iterable of
            ``ModelSpec``.
        ValueError: Two discovered modules declare the same slug.
    """
    root = import_module(package)
    subpackage_names = sorted(
        info.name for info in pkgutil.iter_modules(root.__path__) if info.ispkg
    )

    collected: list[ModelSpec] = []
    declared_in: dict[str, str] = {}
    for name in subpackage_names:
        target = f"{package}.{name}.{module_name}"
        module = _import_optional(target)
        if module is None:
            continue

        specs = _specs_from(module, target, attribute)
        for spec in specs:
            if spec.slug in declared_in:
                raise ValueError(
                    f"duplicate slug {spec.slug!r}: declared in "
                    f"{declared_in[spec.slug]} and {target}"
                )
            declared_in[spec.slug] = target
        collected.extend(specs)

    return tuple(collected)


def _import_optional(target: str) -> ModuleType | None:
    """Import ``target``, returning ``None`` if that exact module is absent.

    A ``ModuleNotFoundError`` raised while importing something ``target``
    itself depends on is not "absent" and must propagate — only the case
    where ``target`` could not be found at all is silent.
    """
    try:
        return import_module(target)
    except ModuleNotFoundError as exc:
        if exc.name == target:
            return None
        raise


def _specs_from(
    module: ModuleType, target: str, attribute: str
) -> tuple[ModelSpec, ...]:
    """Validate and return the specs declared as ``attribute`` on ``module``."""
    if not hasattr(module, attribute):
        raise AttributeError(f"{target} does not define {attribute!r}")

    value = getattr(module, attribute)
    try:
        items = tuple(value)
    except TypeError as exc:
        raise TypeError(
            f"{target}.{attribute} must be an iterable of ModelSpec, "
            f"found {type(value).__name__!r}"
        ) from exc

    invalid = [item for item in items if not isinstance(item, ModelSpec)]
    if invalid:
        raise TypeError(
            f"{target}.{attribute} must be an iterable of ModelSpec, "
            f"found a {type(invalid[0]).__name__!r} element"
        )
    return items
