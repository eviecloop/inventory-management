"""
Tests for restocking order API endpoints.
"""
from datetime import datetime, timedelta

import pytest

import main


@pytest.fixture(autouse=True)
def clear_restocking_orders():
    """Reset the in-memory restocking orders so tests stay independent."""
    main.restocking_orders.clear()
    yield
    main.restocking_orders.clear()


class TestRestockingEndpoints:
    """Test suite for restocking-related endpoints."""

    def test_demand_forecasts_include_restock_fields(self, client):
        """Test that demand forecasts expose cost, stock, and lead time."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0
        for forecast in data:
            assert isinstance(forecast["unit_cost"], (int, float))
            assert isinstance(forecast["quantity_on_hand"], int)
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["unit_cost"] > 0
            assert forecast["quantity_on_hand"] >= 0
            assert forecast["lead_time_days"] > 0

    def test_get_restocking_orders_empty(self, client):
        """Test that no restocking orders exist initially."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restocking_order(self, client):
        """Test creating a restocking order with multiple items."""
        payload = {"items": [
            {"sku": "WDG-001", "quantity": 10},
            {"sku": "GSK-203", "quantity": 4},
        ]}
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == 2
        for item in order["items"]:
            assert "name" in item
            assert "line_total" in item

    def test_restocking_order_total_cost_calculation(self, client):
        """Test that totals use server-side unit costs."""
        forecasts = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        payload = {"items": [
            {"sku": "WDG-001", "quantity": 10},
            {"sku": "GSK-203", "quantity": 4},
        ]}
        order = client.post("/api/restocking-orders", json=payload).json()

        expected = (10 * forecasts["WDG-001"]["unit_cost"]
                    + 4 * forecasts["GSK-203"]["unit_cost"])
        assert abs(order["total_cost"] - expected) < 0.01

    def test_restocking_order_lead_time_calculation(self, client):
        """Test that lead time is the slowest item and sets expected delivery."""
        forecasts = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        payload = {"items": [
            {"sku": "GSK-203", "quantity": 1},
            {"sku": "CTL-330", "quantity": 1},
        ]}
        order = client.post("/api/restocking-orders", json=payload).json()

        expected_lead = max(forecasts["GSK-203"]["lead_time_days"],
                            forecasts["CTL-330"]["lead_time_days"])
        assert order["lead_time_days"] == expected_lead

        order_date = datetime.fromisoformat(order["order_date"])
        expected_delivery = datetime.fromisoformat(order["expected_delivery"])
        assert expected_delivery - order_date == timedelta(days=expected_lead)

    def test_created_orders_listed_newest_first(self, client):
        """Test that submitted orders appear in GET, newest first."""
        first = client.post("/api/restocking-orders",
                            json={"items": [{"sku": "WDG-001", "quantity": 1}]}).json()
        second = client.post("/api/restocking-orders",
                             json={"items": [{"sku": "FLT-405", "quantity": 2}]}).json()

        data = client.get("/api/restocking-orders").json()
        assert [o["id"] for o in data] == [second["id"], first["id"]]
        assert first["order_number"] != second["order_number"]

    def test_create_restocking_order_unknown_sku(self, client):
        """Test that an unknown SKU is rejected."""
        response = client.post("/api/restocking-orders",
                               json={"items": [{"sku": "NOPE-999", "quantity": 1}]})
        assert response.status_code == 400
        assert "NOPE-999" in response.json()["detail"]

    def test_create_restocking_order_invalid_quantity(self, client):
        """Test that zero and negative quantities are rejected."""
        for quantity in (0, -5):
            response = client.post("/api/restocking-orders",
                                   json={"items": [{"sku": "WDG-001", "quantity": quantity}]})
            assert response.status_code == 400

    def test_create_restocking_order_empty_items(self, client):
        """Test that an order with no items is rejected and not stored."""
        response = client.post("/api/restocking-orders", json={"items": []})
        assert response.status_code == 400
        assert client.get("/api/restocking-orders").json() == []
