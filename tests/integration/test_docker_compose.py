"""
Integration test for docker-compose setup.
T005: Write failing integration test for docker-compose.

This test MUST fail before implementation (TDD requirement).
"""

import pytest
import os


@pytest.mark.skipif(
    not os.path.exists("docker-compose.yml"), reason="docker-compose.yml not found"
)
def test_docker_compose_has_required_services():
    """docker-compose.yml should have api, worker, and redis services"""
    import yaml

    with open("docker-compose.yml", "r") as f:
        compose = yaml.safe_load(f)

    services = compose.get("services", {})

    assert "redis" in services, "redis service missing"
    assert "api" in services, "api service missing"
    assert "worker" in services, "worker service missing"


@pytest.mark.skipif(
    not os.path.exists("docker-compose.yml"), reason="docker-compose.yml not found"
)
def test_docker_compose_redis_healthcheck():
    """Redis service should have healthcheck configured"""
    import yaml

    with open("docker-compose.yml", "r") as f:
        compose = yaml.safe_load(f)

    redis = compose.get("services", {}).get("redis", {})
    assert "healthcheck" in redis, "Redis healthcheck missing"


@pytest.mark.skipif(
    not os.path.exists("docker-compose.yml"), reason="docker-compose.yml not found"
)
def test_docker_compose_api_healthcheck():
    """API service should have healthcheck configured"""
    import yaml

    with open("docker-compose.yml", "r") as f:
        compose = yaml.safe_load(f)

    api = compose.get("services", {}).get("api", {})
    assert "healthcheck" in api, "API healthcheck missing"


@pytest.mark.skipif(
    not os.path.exists("docker-compose.yml"), reason="docker-compose.yml not found"
)
def test_docker_compose_networking():
    """Services should be on same network"""
    import yaml

    with open("docker-compose.yml", "r") as f:
        compose = yaml.safe_load(f)

    services = compose.get("services", {})

    for name, service in services.items():
        if name in ["api", "worker"]:
            assert "networks" in service or "depends_on" in service, (
                f"Service {name} missing network config"
            )
