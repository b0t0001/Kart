"""The Supabase backend as the agent sees it: REST with the anon key, writes only through the contract's RPCs."""

from __future__ import annotations

from typing import Any

import httpx


class SupabaseBackend:
    def __init__(self, url: str, anon_key: str, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(base_url=url.rstrip("/") + "/rest/v1/", timeout=8.0)
        self._headers = {"apikey": anon_key, "Authorization": f"Bearer {anon_key}", "Content-Type": "application/json"}

    async def get_cart(self, cart_id: str) -> dict[str, Any]:
        rows = await self._get("carts", {"cart_id": f"eq.{cart_id}"})
        return rows[0] if rows else {}

    async def get_catalog(self) -> list[dict[str, Any]]:
        """Live products with their best deal (`product_catalog` view: sale_price, deal_label, aisle, in_stock)."""
        return await self._get("product_catalog", {"select": "*"})

    async def unresolved_events(self, cart_id: str, trip_id: str | None) -> list[dict[str, Any]]:
        params = {"cart_id": f"eq.{cart_id}", "type": "eq.added", "source": "eq.vision", "applied": "is.false",
                  "resolved_at": "is.null", "order": "id"}
        if trip_id:
            params["trip_id"] = f"eq.{trip_id}"
        return await self._get("cart_events", params)

    async def rpc(self, name: str, **params: Any) -> Any:
        response = await self._client.post(f"rpc/{name}", json=params, headers=self._headers)
        response.raise_for_status()
        return response.json() if response.content else None

    async def _get(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        response = await self._client.get(table, params=params, headers=self._headers)
        response.raise_for_status()
        return response.json()
