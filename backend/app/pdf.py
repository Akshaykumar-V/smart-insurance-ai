import json
import subprocess
import sys
from pathlib import Path

from app.config import Settings
from app.errors import ApiError
from app.models import ParsedPdf


def parse_isolated(data: bytes, settings: Settings, *, extract: bool) -> ParsedPdf:
    """Keep MuPDF out of the web process and bound parser wall-clock time."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.pdf_worker",
                str(settings.max_pdf_pages),
                str(settings.max_extracted_characters),
                "extract" if extract else "inspect",
                str(settings.max_upload_bytes),
            ],
            input=data,
            capture_output=True,
            timeout=settings.pdf_timeout_seconds,
            cwd=Path(__file__).resolve().parent.parent,
        )
        if result.returncode:
            raise ValueError("Parser exited unsuccessfully")
        payload = json.loads(result.stdout)
        if "error" in payload:
            raise ApiError(**payload["error"])
        return ParsedPdf.model_validate(payload)
    except subprocess.TimeoutExpired:
        raise ApiError(400, "PDF_TIMEOUT", "The PDF took too long to read safely.") from None
    except ApiError:
        raise
    except Exception:
        raise ApiError(400, "INVALID_PDF", "The PDF could not be read safely.") from None
