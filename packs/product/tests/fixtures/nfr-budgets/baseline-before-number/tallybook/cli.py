"""Command line: print report rows, or ask for a password reset link."""
import argparse

from tallybook import accounts, ledger


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tallybook")
    sub = parser.add_subparsers(dest="action", required=True)
    rep = sub.add_parser("reports", help="print the ledger rows the reports page would show")
    rep.add_argument("--client", help="only this client")
    rep.add_argument("--month", help="only this month, as YYYY-MM")
    reset = sub.add_parser("reset-password", help="print a reset link for a team member")
    reset.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    if args.action == "reports":
        rows = ledger.filter_rows(ledger.load_rows(), args.client, args.month)
        for row in rows:
            print(f"{row['date']}  {row['client']:<18} {row['account']:<10} {row['amount']:>9.2f}")
        print(f"{len(rows)} rows, total {ledger.total(rows):.2f}")
    else:
        link = accounts.request_reset(args.email, {"robin@tallybook.test": "x"})
        print(link or "no account with that address")


if __name__ == "__main__":
    main()
