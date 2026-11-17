"""CLI entry point."""
from __future__ import annotations

import argparse


def main():
    parser = argparse.ArgumentParser(description="WorkLedger - local work assistant")
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="Start the web server")
    serve_p.add_argument("--host", default=None)
    serve_p.add_argument("--port", type=int, default=None)

    sub.add_parser("init-db", help="Initialize or migrate the database")

    backup_p = sub.add_parser("backup", help="Backup the database")
    backup_p.add_argument("dest", help="Destination file path")

    restore_p = sub.add_parser("restore", help="Restore database from backup")
    restore_p.add_argument("src", help="Backup file path")

    args = parser.parse_args()

    from .config import settings

    if args.command == "serve":
        import uvicorn
        uvicorn.run(
            "workledger.app:app",
            host=args.host or settings.workledger_host,
            port=args.port or settings.workledger_port,
        )
    elif args.command == "init-db":
        from .db import init_db
        init_db(settings.db_path)
        print(f"Database ready: {settings.db_path}")
    elif args.command == "backup":
        from .backup import backup_db
        backup_db(settings.db_path, args.dest)
    elif args.command == "restore":
        from .backup import restore_db
        restore_db(settings.db_path, args.src)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()