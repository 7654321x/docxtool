"""Run the Docxtool web service with ``python -m docxtool``."""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if any(arg in {"-h", "--help"} for arg in args):
        print("Usage: python -m docxtool")
        print("Start the Docxtool web service.")
        print("Configure ADMIN_TOKEN and PROXY_SECRET before starting the service.")
        return

    from docxtool.env import load_dotenv_file

    load_dotenv_file(Path.cwd() / ".env")

    from docxtool.web.app import main as web_main

    web_main()


if __name__ == "__main__":
    main()
