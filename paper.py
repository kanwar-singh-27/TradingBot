"""Fixed paper-only entry point; usable with Python isolated mode (-I)."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nifty_paper.cli import main

if __name__ == '__main__':
    raise SystemExit(main())