"""Compatibility entry point for running the Docxtool web service."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from docxtool.env import load_dotenv_file  # noqa: E402

load_dotenv_file(ROOT / ".env")

from docxtool.web.app import main  # noqa: E402


if __name__ == "__main__":
    main()
