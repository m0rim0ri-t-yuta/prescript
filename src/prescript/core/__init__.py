"""The domain-neutral core: what any prescript domain library imports instead of copying.

A domain brings its own IR, loader, mode solver and check routines. The core runs its assertions
across its modes and renders the result, and it reads the domain's design only through
`prescript.core.spec`: a `project` name, the `modes` by name, and `assertions` that each carry an
`id`, a `check`, the `modes` they run in and a `severity`. `prescript.result` is part of the core
too; it lives at the top level because domains already import it from there.

The cooling domain (the rest of this package) is built on it the same way an outside domain is.
"""

from prescript.core.spec import META_MODE, STATIC_MODE, AssertionSpec, DesignSpec

__all__ = ["META_MODE", "STATIC_MODE", "AssertionSpec", "DesignSpec"]
