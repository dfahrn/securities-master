import sys


def main() -> int:
    print("usage: python -m securities_master.cli seed-edgar", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
