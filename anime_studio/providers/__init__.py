"""Provider layer — swappable model workers behind common interfaces."""
from .base import FailoverTextProvider, ProviderError, TextProvider  # noqa: F401
from .router import build_text_provider  # noqa: F401
