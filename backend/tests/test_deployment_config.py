"""Sanity checks for deployment wiring kept in the Render Blueprint."""

from pathlib import Path
from typing import cast

import yaml


def test_render_blueprint_wires_private_redis_and_predeploy_migrations() -> None:
    blueprint_path = Path(__file__).resolve().parents[2] / "render.yaml"
    blueprint = cast(dict[str, object], yaml.safe_load(blueprint_path.read_text()))
    services = cast(list[dict[str, object]], blueprint["services"])
    databases = cast(list[dict[str, object]], blueprint["databases"])
    services_by_name = {cast(str, service["name"]): service for service in services}
    api = services_by_name["payagent-api"]
    redis = services_by_name["payagent-redis"]
    database = databases[0]
    api_env = {
        cast(str, item["key"]): item
        for item in cast(list[dict[str, object]], api["envVars"])
    }
    database_reference = cast(
        dict[str, object], api_env["DATABASE_URL"]["fromDatabase"]
    )
    redis_reference = cast(dict[str, object], api_env["REDIS_URL"]["fromService"])

    assert redis["type"] == "keyvalue"
    assert redis["ipAllowList"] == []
    assert database["ipAllowList"] == []
    assert api["preDeployCommand"] == "python -m alembic upgrade head"
    assert api["healthCheckPath"] == "/ready"
    assert database_reference["property"] == "connectionString"
    assert redis_reference["property"] == "connectionString"
    assert api_env["PAYPAL_ENVIRONMENT"]["value"] == "sandbox"
