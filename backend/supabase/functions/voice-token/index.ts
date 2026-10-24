import { handle } from "./handler.ts";

Deno.serve((req) => handle(req, { env: (name) => Deno.env.get(name), fetch }));
