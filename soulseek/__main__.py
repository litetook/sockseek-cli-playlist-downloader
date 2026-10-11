"""`py -m soulseek` - the engine without run.py's menu."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
