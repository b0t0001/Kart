// deno test backend/supabase/functions/voice-token/
import { assertEquals } from "jsr:@std/assert@1.0.13";
import { CARTESIA_VERSION, type Deps, handle } from "./handler.ts";

const ENV: Record<string, string> = {
  SUPABASE_URL: "https://proj.supabase.co",
  CARTESIA_API_KEY: "sk_car_test",
  CARTESIA_AGENT_ID: "agent_123",
};

function deps(opts: { carts?: string[]; cartesia?: Response | Error; env?: Record<string, string> } = {}) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const env = opts.env ?? ENV;
  const d: Deps = {
    env: (k) => env[k],
    now: () => Date.parse("2026-10-24T12:00:00Z"),
    fetch: (async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (url.startsWith(ENV.SUPABASE_URL)) {
        const id = decodeURIComponent(url.match(/cart_id=eq\.([^&]*)/)![1]);
        const rows = (opts.carts ?? ["7"]).includes(id) ? [{ cart_id: id }] : [];
        return new Response(JSON.stringify(rows), { status: 200 });
      }
      if (opts.cartesia instanceof Error) throw opts.cartesia;
      return opts.cartesia ?? new Response(JSON.stringify({ token: "tok_abc" }), { status: 200 });
    }) as typeof fetch,
  };
  return { d, calls };
}

const post = (body: unknown) =>
  new Request("http://localhost/voice-token", {
    method: "POST",
    headers: { apikey: "anon", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

Deno.test("returns a token for a known cart", async () => {
  const { d, calls } = deps();
  const r = await handle(post({ cart_id: "7" }), d);
  assertEquals(r.status, 200);
  assertEquals(await r.json(), {
    token: "tok_abc",
    expires_at: "2026-10-24T13:00:00.000Z",
    agent_id: "agent_123",
    ws_url: "wss://api.cartesia.ai/agents/stream/agent_123",
    cartesia_version: CARTESIA_VERSION,
  });
  const upstream = calls.find((c) => c.url === "https://api.cartesia.ai/access-token")!;
  const h = upstream.init!.headers as Record<string, string>;
  assertEquals(h.Authorization, "Bearer sk_car_test");
  assertEquals(h["Cartesia-Version"], "2026-08-14");
  assertEquals(JSON.parse(upstream.init!.body as string), { grants: { agent: true }, expires_in: 3600 });
});

Deno.test("unknown or missing cart_id is a 400", async () => {
  for (const body of [{ cart_id: "99" }, {}, { cart_id: 7 }]) {
    const r = await handle(post(body), deps().d);
    assertEquals(r.status, 400);
    assertEquals(await r.json(), { error: "unknown cart_id" });
  }
});

Deno.test("upstream failure is a 502 with the status", async () => {
  const r = await handle(post({ cart_id: "7" }), deps({ cartesia: new Response("no", { status: 401 }) }).d);
  assertEquals(r.status, 502);
  assertEquals(await r.json(), { error: "cartesia token failed", detail: 401 });
});

Deno.test("network error and missing key are 502s", async () => {
  let r = await handle(post({ cart_id: "7" }), deps({ cartesia: new Error("dns") }).d);
  assertEquals(r.status, 502);
  r = await handle(post({ cart_id: "7" }), deps({ env: { SUPABASE_URL: ENV.SUPABASE_URL } }).d);
  assertEquals((await r.json()).detail, "CARTESIA_API_KEY is not set");
});

Deno.test("the API key never appears in a response", async () => {
  for (const cartesia of [undefined, new Response("x", { status: 500 }), new Error("boom")]) {
    const r = await handle(post({ cart_id: "7" }), deps({ cartesia }).d);
    assertEquals((await r.text()).includes("sk_car_test"), false);
  }
});
