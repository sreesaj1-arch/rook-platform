"""Explicit schema initialization or one real evaluation; not a worker loop."""

import argparse
import asyncio
import sys

from pydantic import ValidationError

from rook_backend.config import Settings
from rook_backend.database import Database
from rook_backend.incident_store import PostgresIncidentStore
from rook_backend.incidents import Rules, evaluate_service
from rook_backend.telemetry import Prometheus, Unavailable
from rook_backend.telemetry_profiles import validate_identity


async def run(command: str, service: str, rules: Rules, settings: Settings) -> int:
    database = Database(settings)
    try:
        store = PostgresIncidentStore(database)
        if command == "init-db":
            await store.initialize()
            print('Incident schema initialized.')
            return 0
        validate_identity(service, settings.prometheus_namespace)
        source = Prometheus(settings)
        try:
            result = await evaluate_service(service, source, store, rules)
            print(result.model_dump_json())
            return 0 if result.status == "evaluated" else 1
        finally:
            await source.close()
    finally:
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init-db", "evaluate"])
    parser.add_argument("--service", default="frontend")
    parser.add_argument("--error-ratio", type=float)
    parser.add_argument("--p95-seconds", type=float)
    args = parser.parse_args()
    try:
        rules = Rules(error_ratio=args.error_ratio, p95_latency=args.p95_seconds)
        settings = Settings()
        return asyncio.run(run(args.command, args.service, rules, settings),
                           loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)
    except (Unavailable, ValidationError, ValueError):
        print('Incident command unavailable or invalid configuration.', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
