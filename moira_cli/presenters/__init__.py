"""Base presenter for output formatting."""

from __future__ import annotations

from moira_cli.ui import get_ui


class BasePresenter:
    """Base presenter with UI access."""

    def __init__(self) -> None:
        """Initialize presenter with UI."""
        self.ui = get_ui()
