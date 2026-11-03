// Fills the store's own cart from the browser, using the guest's own cart
// token (the same one the store site keeps in localStorage.cartToken). The
// store's server computes every price; this module never handles payment.

export type StoreLine =
  | { kind: "single"; variantId: string; quantity: number; name?: string | null }
  | {
      kind: "bespoke";
      canvasId: string;
      finishId: string;
      items: Array<{ dateId: string; quantity: number }>;
      giftMessage?: string;
      name?: string | null;
    };

export interface StoreCartResult {
  ok: boolean; // every line was added
  added: number;
  failed: Array<{ name: string; reason: string }>;
}

const TOKEN_KEY = "cartToken";
const ACCESS_KEY = "accessToken";

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage blocked - the cart still works for this page load */
  }
}

async function reasonFrom(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    const m = body?.message ?? body?.detail;
    if (Array.isArray(m)) return m.join("; ");
    if (typeof m === "string") return m;
  } catch {
    /* ignore */
  }
  return resp.statusText || `HTTP ${resp.status}`;
}

export async function addToStoreCart(
  lines: StoreLine[],
  storeApiBase: string,
  fetchImpl: typeof fetch = fetch
): Promise<StoreCartResult> {
  const base = storeApiBase.replace(/\/+$/, "");
  const result: StoreCartResult = { ok: true, added: 0, failed: [] };

  for (const line of lines) {
    const name = line.name || (line.kind === "single" ? "Product" : "Custom box");
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const token = readStorage(TOKEN_KEY);
    if (token) headers["X-Cart-Token"] = token;
    const access = readStorage(ACCESS_KEY);
    if (access) headers["Authorization"] = `Bearer ${access}`;

    const path = line.kind === "single" ? "/api/cart/items" : "/api/cart/bespoke";
    const body =
      line.kind === "single"
        ? { variantId: line.variantId, quantity: line.quantity }
        : {
            canvasId: line.canvasId,
            finishId: line.finishId,
            items: line.items,
            ...(line.giftMessage ? { giftMessage: line.giftMessage } : {}),
          };

    try {
      const resp = await fetchImpl(base + path, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
      const newToken = resp.headers.get("x-cart-token");
      if (newToken) writeStorage(TOKEN_KEY, newToken);
      if (!resp.ok) {
        result.failed.push({ name, reason: await reasonFrom(resp) });
        continue;
      }
      result.added += 1;
    } catch (e) {
      result.failed.push({
        name,
        reason: e instanceof Error ? e.message : "Network error",
      });
    }
  }
  result.ok = result.failed.length === 0;
  return result;
}
