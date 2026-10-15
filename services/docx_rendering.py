"""DOCX rendering boundary for format-preserving document workflows."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from docx import Document


class DocxRenderer:
    def render_from_template(self, template_path: str | Path, output_path: str | Path, transform: Any = None) -> Path:
        source = Path(template_path)
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if transform is not None:
            document = Document(destination)
            transform(document)
            document.save(destination)
        return destination
