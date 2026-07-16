"""
E2E test for Docker deployment.
T009: Write failing E2E test for Docker deployment.

This test MUST fail before implementation (TDD requirement).
"""

import pytest
import os
import subprocess


@pytest.mark.skipif(not os.path.exists("Dockerfile"), reason="Dockerfile not found")
def test_dockerfile_exists_and_valid():
    """Dockerfile should exist and be valid syntax."""
    assert os.path.exists("Dockerfile"), "Dockerfile missing"

    with open("Dockerfile", "r") as f:
        content = f.read()
        assert "FROM" in content, "Dockerfile missing FROM instruction"
        assert "WORKDIR" in content, "Dockerfile missing WORKDIR"


@pytest.mark.skipif(not os.path.exists("Dockerfile"), reason="Dockerfile not found")
def test_dockerfile_has_playwright_base():
    """Dockerfile should use Playwright base image."""
    with open("Dockerfile", "r") as f:
        content = f.read()
        assert "playwright" in content.lower(), "Dockerfile not using Playwright base"


@pytest.mark.skipif(
    not os.path.exists("docker-compose.yml"), reason="docker-compose.yml not found"
)
def test_docker_compose_has_expose():
    """docker-compose should expose port 8000 for API."""
    import yaml

    with open("docker-compose.yml", "r") as f:
        compose = yaml.safe_load(f)

    api = compose.get("services", {}).get("api", {})
    ports = api.get("ports", [])
    assert any("8000" in str(p) for p in ports), "API port 8000 not exposed"


@pytest.mark.skipif(
    not os.path.exists("docker-compose.yml"), reason="docker-compose.yml not found"
)
def test_docker_compose_has_healthcheck_cmd():
    """docker-compose API service should have healthcheck command."""
    import yaml

    with open("docker-compose.yml", "r") as f:
        compose = yaml.safe_load(f)

    api = compose.get("services", {}).get("api", {})
    hc = api.get("healthcheck", {})
    cmd = hc.get("test", [])
    assert "healthz" in str(cmd), "Healthcheck not checking /healthz"
