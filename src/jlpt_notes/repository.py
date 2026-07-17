"""Filesystem layout management for a JLPT notes repository."""

from pathlib import Path


class Repository:
    """Own the persistent directory layout for learner data."""

    REQUIRED_DIRECTORIES = (
        "grammar", "vocabulary", "reading", "drafts", "reviews", "quizzes",
        "analytics", "history", "schemas", "backups",
    )

    def __init__(self, root: Path) -> None:
        self.root = root

    def init_layout(self) -> None:
        """Create every required top-level directory."""
        for name in self.REQUIRED_DIRECTORIES:
            (self.root / name).mkdir(parents=True, exist_ok=True)
