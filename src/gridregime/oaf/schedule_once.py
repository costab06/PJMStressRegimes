"""Launch one scheduled OAF acquisition cycle; suitable for cron/systemd.

Example:
  python -m gridregime.oaf.schedule_once --ba PJM --redis-url redis://localhost:6379/0

The command queues work; independent OAF agent workers must be running.
"""
from __future__ import annotations

import argparse
import asyncio
import json

import pandas as pd
from redis.asyncio import Redis
from shared.correlation.registry import CorrelationRegistry

from gridregime.oaf.cycle_scheduler import submit_cycle


async def _run(args):
    redis = Redis.from_url(args.redis_url, decode_responses=True)
    try:
        as_of = args.as_of or pd.Timestamp.now(tz="UTC").floor("h").isoformat()
        result = await submit_cycle(
            redis=redis, correlation_registry=CorrelationRegistry(redis),
            ba=args.ba, as_of=as_of,
            lookback_hours=args.lookback_hours,
            publication_lag_hours=args.publication_lag_hours,
            require_pjm=args.require_pjm,
        )
        print(json.dumps(result, sort_keys=True))
    finally:
        await redis.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--ba", default="PJM")
    parser.add_argument("--as-of", help="UTC cycle hour; default current completed hour")
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--publication-lag-hours", type=int, default=2)
    parser.add_argument("--require-pjm", action="store_true",
                        help="Also dispatch PJM live Emergency Procedures acquisition")
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
