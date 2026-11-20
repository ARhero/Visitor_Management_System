"""Languages the app speaks. Adding one: see docs/adding-a-language.md.

``Locale`` is used in request schemas, so an unsupported language is rejected with a
clear error instead of silently falling back.
"""

from typing import Literal

Locale = Literal["en", "hi"]
LOCALES: tuple[str, ...] = ("en", "hi")
