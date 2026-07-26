"""Phase 8 explanation package."""

from backend.app.explanation.generator import generate_explanation
from backend.app.explanation.templates import render_explanation

__all__ = ["generate_explanation", "render_explanation"]
