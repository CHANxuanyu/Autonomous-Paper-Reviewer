"""One-off schema migration for multimodal vector chunk image links."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db import engine


def main() -> None:
    """Add the linked_image_path column if it does not already exist."""

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE vector_chunks ADD COLUMN IF NOT EXISTS linked_image_path TEXT"))

    print("Ensured vector_chunks.linked_image_path exists.")


if __name__ == "__main__":
    main()
