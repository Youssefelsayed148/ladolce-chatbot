import { beforeEach, describe, expect, it, vi } from "vitest";
import { addToStoreCart, type StoreLine } from "./storeCart";

const BASE = "https://store.example";

function resp(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers });
}

const single: StoreLine = { kind: "single", variantId: "v1", quantity: 2, name: "Khudri" };
const box: StoreLine = {
  kind: "bespoke",
  canvasId: "c1",
  finishId: "f1",
  items: [{ dateId: "d1", quantity: 5 }],
  giftMessage: "Eid",
  name: "Classic box",
};

describe("addToStoreCart", () => {
  beforeEach(() => window.localStorage.clear());

  it("posts each line to the right endpoint and stores the returned cart token", async () => {
    const f = vi
      .fn()
      .mockResolvedValueOnce(resp(201, {}, { "x-cart-token": "tok-1" }))
      .mockResolvedValueOnce(resp(201, {}, { "x-cart-token": "tok-2" }));
    const res = await addToStoreCart([single, box], BASE + "/", f as unknown as typeof fetch);

    expect(res).toEqual({ ok: true, added: 2, failed: [] });
    expect(f.mock.calls[0][0]).toBe(`${BASE}/api/cart/items`);
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ variantId: "v1", quantity: 2 });
    expect(f.mock.calls[1][0]).toBe(`${BASE}/api/cart/bespoke`);
    expect(JSON.parse(f.mock.calls[1][1].body)).toEqual({
      canvasId: "c1",
      finishId: "f1",
      items: [{ dateId: "d1", quantity: 5 }],
      giftMessage: "Eid",
    });
    // The first call's token is reused for the second line, then replaced.
    expect(f.mock.calls[1][1].headers["X-Cart-Token"]).toBe("tok-1");
    expect(window.localStorage.getItem("cartToken")).toBe("tok-2");
  });

  it("sends the guest's existing cart token and access token", async () => {
    window.localStorage.setItem("cartToken", "mine");
    window.localStorage.setItem("accessToken", "jwt");
    const f = vi.fn().mockResolvedValue(resp(201, {}));
    await addToStoreCart([single], BASE, f as unknown as typeof fetch);
    expect(f.mock.calls[0][1].headers["X-Cart-Token"]).toBe("mine");
    expect(f.mock.calls[0][1].headers["Authorization"]).toBe("Bearer jwt");
    expect(window.localStorage.getItem("cartToken")).toBe("mine");
  });

  it("reports failed lines (stock error, network) and still adds the rest", async () => {
    const f = vi
      .fn()
      .mockResolvedValueOnce(resp(400, { message: "Only 1 left in stock" }))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(resp(201, {}));
    const res = await addToStoreCart([single, box, single], BASE, f as unknown as typeof fetch);
    expect(res.ok).toBe(false);
    expect(res.added).toBe(1);
    expect(res.failed).toEqual([
      { name: "Khudri", reason: "Only 1 left in stock" },
      { name: "Classic box", reason: "offline" },
    ]);
  });

  it("omits giftMessage when there is none", async () => {
    const f = vi.fn().mockResolvedValue(resp(201, {}));
    await addToStoreCart([{ ...box, giftMessage: undefined }], BASE, f as unknown as typeof fetch);
    expect("giftMessage" in JSON.parse(f.mock.calls[0][1].body)).toBe(false);
  });
});
