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

    async def get_live_deals(self) -> list[dict[str, Any]]:
        """Active deals with what they pair with (for "deals that go with your list")."""
        return await self._get("deals", {"select": "id,product_id,label,pairs_with,ends_at", "active": "eq.true"})

    async def get_feature_defaults(self) -> dict[str, bool]:
        """Each feature flag's enabled_default; a cart's own carts.features entry overrides it."""
        return {row["name"]: bool(row.get("enabled_default")) for row in
                await self._get("feature_flags", {"select": "name,enabled_default"})}

    async def get_transcript(self, cart_id: str, trip_id: str | None) -> list[dict[str, Any]]:
        """The trip's captions, oldest first (the last 16), for a call that rejoins a trip."""
        params = {"cart_id": f"eq.{cart_id}", "select": "role,text", "order": "id.desc", "limit": "16"}
        if trip_id:
            params["trip_id"] = f"eq.{trip_id}"
        return list(reversed(await self._get("transcript", params)))

    async def get_nearby_stores(self) -> list[dict[str, Any]]:
        """Other stores nearby (store_info.nearby: name, distance, kind, good_for), for things this store doesn't sell."""
        rows = await self._get("store_info", {"select": "nearby", "limit": "1"})
        nearby = rows[0].get("nearby") if rows else None
        return nearby if isinstance(nearby, list) else []

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
