"""Read and write Markdown cards with JSON-compatible YAML frontmatter."""

from dataclasses import asdict
from datetime import date
import json
from pathlib import Path

from .models import Card


def write_card(path: Path, card: Card) -> None:
    """Atomically write one card using a JSON frontmatter document."""
    data = asdict(card)
    data.pop("body")
    for key in ("created_at", "updated_at", "next_review"):
        data[key] = data[key].isoformat()
    data["tags"] = list(data["tags"])
    data["confusions"] = list(data["confusions"])
    content = "---\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n---\n\n" + card.body + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def read_card(path: Path) -> Card:
    """Load a card and validate its structured frontmatter."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path} has no frontmatter")
    try:
        metadata_text, body = text[4:].split("\n---\n\n", 1)
        metadata = json.loads(metadata_text)
    except (ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} has invalid frontmatter") from error
    for key in ("created_at", "updated_at", "next_review"):
        metadata[key] = date.fromisoformat(metadata[key])
    metadata["tags"] = tuple(metadata.get("tags", []))
    metadata["confusions"] = tuple(metadata.get("confusions", []))
    return Card(body=body.rstrip("\n"), **metadata)
