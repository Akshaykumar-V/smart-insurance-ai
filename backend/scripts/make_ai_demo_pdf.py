"""Generate only fictional health wording in a unique OS temporary file."""

import tempfile
from pathlib import Path

import pymupdf


def main():
    with tempfile.NamedTemporaryFile(prefix="fictional-health-", suffix=".pdf", delete=False) as f:
        path = Path(f.name)
    with pymupdf.open() as document:
        for text in (
            "Fictional Indian indemnity health insurance wording.\n"
            "Health insurance: A co-payment of 20% of admissible expenses applies "
            "to age 60 and above.",
            "Fictional Indian indemnity health insurance wording.\n"
            "Cataract treatment is limited to INR 40,000 per eye per policy year.",
        ):
            page = document.new_page()
            page.insert_textbox(pymupdf.Rect(50, 50, 540, 750), text, fontsize=11)
        document.save(path)
    print(path)


if __name__ == "__main__":
    main()
