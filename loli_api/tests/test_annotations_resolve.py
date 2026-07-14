"""Guard: every annotation in the package must actually RESOLVE.

Why this exists (prod incident 2026-07-14): the dev venv runs Python 3.14,
where PEP 649 makes annotations lazy — a name used only in an annotation
(e.g. ``Optional`` without its import) never evaluates locally, so the whole
suite stays green. Production runs Python 3.13, which evaluates annotations
eagerly at def time — the same module crashes the app at import
(``NameError: name 'Optional' is not defined`` in head_mask.py took prod
down in a healthcheck bootloop).

This test walks every module under loli_api (excluding tests/scripts/
migrations), imports it, and forces annotation evaluation for the module and
every contained function/class via ``typing.get_type_hints`` — reproducing
3.13's eager semantics on any interpreter, so this bug class can never hide
behind a lazy-annotation interpreter again.
"""
import importlib
import inspect
import pkgutil
import sys
import typing
from pathlib import Path

_LOLI_DIR = Path(__file__).resolve().parent.parent
if str(_LOLI_DIR) not in sys.path:
    sys.path.insert(0, str(_LOLI_DIR))

_SKIP_PREFIXES = ("tests", "scripts", "migrations")


def _iter_module_names():
    for pkg in ("services", "workers", "models", "api"):
        pkg_path = _LOLI_DIR / pkg
        if not pkg_path.is_dir():
            continue
        yield pkg
        for info in pkgutil.walk_packages([str(pkg_path)], prefix=f"{pkg}."):
            if not info.name.startswith(_SKIP_PREFIXES):
                yield info.name
    yield "config"


def _force_annotations(obj, failures, where):
    try:
        typing.get_type_hints(obj)
    except NameError as e:
        failures.append(f"{where}: {e}")
    except Exception:
        # Non-NameError resolution issues (e.g. optional deps in TYPE_CHECKING
        # blocks) are not the prod-crash class this guard exists for.
        pass


def test_every_annotation_resolves_like_python_313():
    failures = []
    for name in _iter_module_names():
        try:
            mod = importlib.import_module(name)
        except Exception as e:  # a module that cannot import at all IS a failure
            failures.append(f"import {name}: {type(e).__name__}: {e}")
            continue
        for attr_name, attr in vars(mod).items():
            if getattr(attr, "__module__", None) != mod.__name__:
                continue
            if inspect.isfunction(attr):
                _force_annotations(attr, failures, f"{name}.{attr_name}")
            elif inspect.isclass(attr):
                _force_annotations(attr, failures, f"{name}.{attr_name}")
                for m_name, m in vars(attr).items():
                    if inspect.isfunction(m):
                        _force_annotations(
                            m, failures, f"{name}.{attr_name}.{m_name}"
                        )
    assert not failures, (
        "Annotations that crash eager-evaluation interpreters (prod = 3.13):\n"
        + "\n".join(failures)
    )


if __name__ == "__main__":
    test_every_annotation_resolves_like_python_313()
    print("OK: all annotations resolve")
