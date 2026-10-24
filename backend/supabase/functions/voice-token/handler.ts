// P7 (CONTRACT §5a): a short-lived Cartesia token so the iPad can open the Line agent
// WebSocket without ever holding CARTESIA_API_KEY.
//
//   POST /functions/v1/voice-token  {"cart_id": "7"}
//   200 {token, expires_at, agent_id, ws_url, cartesia_version}
//   400 {"error": "unknown cart_id"}
//   502 {"error": "cartesia token failed", "detail": ...}

export const CARTESIA_VERSION = "2026-08-14";
const TOKEN_TTL_S = 3600; // Cartesia's maximum

export interface Deps {
  env: (name: string) => string | undefined;
  fetch: typeof fetch;
  now?: () => number;
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

async function cartExists(cartId: string, apikey: string, deps: Deps): Promise<boolean> {
  const base = deps.env("SUPABASE_URL");
  const url = `${base}/rest/v1/carts?cart_id=eq.${encodeURIComponent(cartId)}&select=cart_id`;
  const r = await deps.fetch(url, { headers: { apikey, Authorization: `Bearer ${apikey}` } });
  if (!r.ok) throw new Error(`carts lookup ${r.status}`);
  const rows = await r.json();
  return Array.isArray(rows) && rows.length > 0;
}

export async function handle(req: Request, deps: Deps): Promise<Response> {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
  if (req.method !== "POST") return json(400, { error: "unknown cart_id" });

  let cartId: unknown;
  try {
    cartId = (await req.json())?.cart_id;
  } catch {
    cartId = undefined;
  }
  // Read carts with the caller's own anon key (anon can read carts); fall back to ours.
  const apikey = req.headers.get("apikey") ?? deps.env("SUPABASE_ANON_KEY") ?? "";
  if (typeof cartId !== "string" || cartId === "" || !(await cartExists(cartId, apikey, deps))) {
    return json(400, { error: "unknown cart_id" });
  }

  const key = deps.env("CARTESIA_API_KEY");
  const agentId = deps.env("CARTESIA_AGENT_ID") ?? "";
  if (!key) return json(502, { error: "cartesia token failed", detail: "CARTESIA_API_KEY is not set" });

  let upstream: Response;
  try {
    upstream = await deps.fetch("https://api.cartesia.ai/access-token", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "Cartesia-Version": CARTESIA_VERSION,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ grants: { agent: true }, expires_in: TOKEN_TTL_S }),
    });
  } catch (e) {
    return json(502, { error: "cartesia token failed", detail: String(e) });
  }
  if (!upstream.ok) {
    return json(502, { error: "cartesia token failed", detail: upstream.status });
  }
  const { token } = await upstream.json();
  if (typeof token !== "string") {
    return json(502, { error: "cartesia token failed", detail: "no token in response" });
  }

  const now = deps.now?.() ?? Date.now();
  return json(200, {
    token,
    expires_at: new Date(now + TOKEN_TTL_S * 1000).toISOString(),
    agent_id: agentId,
    ws_url: `wss://api.cartesia.ai/agents/stream/${agentId}`,
    cartesia_version: CARTESIA_VERSION,
  });
}
