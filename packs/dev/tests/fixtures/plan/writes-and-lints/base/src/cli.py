import argparse

from src.status import collect


def cmd_status(args):
    info = collect()
    print(f"harbour: {info['harbour']}")
    print(f"free berths: {info['free_berths']}")
    print(f"tide: {info['tide']}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="moorings")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="show harbour status")
    status.set_defaults(func=cmd_status)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
