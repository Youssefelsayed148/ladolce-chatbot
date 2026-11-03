import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConfirmCheckoutButton from "./ConfirmCheckoutButton";

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers });

const CONFIRM = {
  conversation_id: "c1",
  order_id: 7,
  status: "pending_handoff",
  total_price: 100,
  redirect_url: "https://shop.example/checkout",
  handoff_error: null,
  store_api_base: "https://store.example",
  store_lines: [{ kind: "single", variantId: "v1", quantity: 1, name: "Khudri" }],
};

function mockFetch(storeResponse: Response) {
  const calls: string[] = [];
  const f = vi.fn(async (url: string, _init?: RequestInit) => {
    calls.push(url);
    if (url.endsWith("/api/cart/c1")) return json(200, { status: "reviewed", items: [], total_price: 0 });
    if (url.endsWith("/confirm")) return json(200, CONFIRM);
    if (url.startsWith("https://store.example")) return storeResponse;
    if (url.endsWith("/handoff-result")) return json(200, { order_id: 7, status: "sent_to_checkout" });
    return json(404, {});
  });
  vi.stubGlobal("fetch", f);
  return { f, calls };
}

afterEach(() => vi.unstubAllGlobals());

describe("ConfirmCheckoutButton store handoff", () => {
  it("fills the store cart, reports success and shows the checkout button", async () => {
    const { f, calls } = mockFetch(json(201, {}, { "x-cart-token": "t" }));
    render(<ConfirmCheckoutButton conversationId="c1" />);
    await userEvent.click(await screen.findByRole("button", { name: /confirm & checkout/i }));

    const link = await screen.findByRole("link", { name: /continue to checkout/i });
    expect(link).toHaveAttribute("href", "https://shop.example/checkout");
    expect(calls).toContain("https://store.example/api/cart/items");
    const report = f.mock.calls.find((c) => String(c[0]).endsWith("/handoff-result"))!;
    expect(JSON.parse((report[1] as RequestInit).body as string)).toMatchObject({ success: true });
  });

  it("when the store refuses everything, keeps the order saved, hides checkout and says why", async () => {
    const { f } = mockFetch(json(400, { message: "Out of stock" }));
    render(<ConfirmCheckoutButton conversationId="c1" />);
    await userEvent.click(await screen.findByRole("button", { name: /confirm & checkout/i }));

    expect(await screen.findByText(/Your order is saved/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /continue to checkout/i })).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent("Khudri: Out of stock");
    const report = f.mock.calls.find((c) => String(c[0]).endsWith("/handoff-result"))!;
    expect(JSON.parse((report[1] as RequestInit).body as string)).toMatchObject({
      success: false,
      failed_items: ["Khudri"],
    });
  });
});
