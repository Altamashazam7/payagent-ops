"""Insert deterministic synthetic demo records into a non-production database."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence

from sqlalchemy import select

from app.core.settings import get_settings
from app.db.session import Database
from app.demo_data.generator import DEMO_OWNER_EMAIL, DEMO_OWNER_ID, build_demo_dataset
from app.models.user import User

_logger = logging.getLogger("payagent_ops.demo_data")


async def seed_demo_data() -> bool:
    """Seed one complete synthetic tenant; return False when it already exists."""
    settings = get_settings()
    if settings.environment == "production":
        raise RuntimeError("Demo data cannot be written to a production environment")
    database = Database(settings.database_url, echo=settings.database_echo)
    try:
        async with database.session_factory() as session, session.begin():
            existing = await session.get(User, DEMO_OWNER_ID)
            if existing is not None:
                if existing.email != DEMO_OWNER_EMAIL:
                    raise RuntimeError("The deterministic demo identity is occupied")
                _logger.info(
                    "Synthetic demo tenant already exists",
                    extra={"event": "demo_seed_skipped"},
                )
                return False
            duplicate_email = await session.scalar(
                select(User.id).where(User.email == DEMO_OWNER_EMAIL)
            )
            if duplicate_email is not None:
                raise RuntimeError(
                    "The demo email is already used by a different account"
                )
            dataset = build_demo_dataset()
            for group in dataset.groups():
                session.add_all(group)
                await session.flush()
        _logger.info(
            "Synthetic demo dataset inserted",
            extra={
                "event": "demo_seed_completed",
                "tenant_id": str(DEMO_OWNER_ID),
                "vendor_count": 4,
                "transaction_count": 80,
            },
        )
        return True
    finally:
        await database.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    """Require an explicit confirmation before inserting demo records."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-demo-data",
        action="store_true",
        help="confirm that the configured non-production database is disposable/demo",
    )
    args = parser.parse_args(argv)
    if not args.confirm_demo_data:
        parser.error("pass --confirm-demo-data to insert synthetic records")
    logging.basicConfig(level=logging.INFO)
    inserted = asyncio.run(seed_demo_data())
    print("Demo data inserted." if inserted else "Demo data already exists; unchanged.")


if __name__ == "__main__":
    main()
