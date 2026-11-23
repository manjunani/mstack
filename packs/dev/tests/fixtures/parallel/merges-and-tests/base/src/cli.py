import argparse

VERSION = "0.4.2"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="quay")
    parser.add_argument("berth", nargs="?", default="A1")
    args = parser.parse_args(argv)
    print(f"berth {args.berth}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
