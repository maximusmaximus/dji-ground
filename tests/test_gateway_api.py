"""Tests for FastAPI Gateway REST endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from dji_ground.gateway import app


@pytest.mark.asyncio
async def test_gateway_status_and_emergency_stop():
    """Test gateway status endpoint and emergency stop trigger."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Status
        res = await ac.get("/api/status")
        assert res.status_code == 200
        data = res.json()
        assert "state" in data
        assert "battery_percent" in data

        # Emergency Stop
        stop_res = await ac.post("/api/emergency_stop")
        assert stop_res.status_code == 200
        assert stop_res.json()["status"] == "emergency_stop_triggered"

        # Preflight
        pf_res = await ac.get("/api/preflight")
        assert pf_res.status_code == 200
        assert "passed" in pf_res.json()

        # Web UI
        ui_res = await ac.get("/")
        assert ui_res.status_code == 200
        assert "DJI Ground Station" in ui_res.text
