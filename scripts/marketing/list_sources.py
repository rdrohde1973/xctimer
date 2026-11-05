#!/usr/bin/env python3
"""List every [src: URL] in markdown files as file:line: URL (stdlib only)."""
import re
import sys

PAT = re.compile(r"\[src:\s*(\S+?)\s*\]")


def main(argv):
    if not argv:
        print("usage: list_sources.py FILE.md [FILE.md ...]", file=sys.stderr)
        return 2
    for path in argv:
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                for m in PAT.finditer(line):
                    print(f"{path}:{n}: {m.group(1)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
