// Minimal typed API client for the cart/order endpoints. The reverse proxy
// serves the API under /api on the same origin as the SPA.

import type { StoreLine } from "./storeCart";

export interface CartItem {
  type: "single_product" | "custom_plate";
  cart_item_id: number;
  name?: string | null;
  product_id?: number | null;
  quantity?: number;
  unit_price: number;
  line_total: number;
  variant_label?: string;
  finish?: string | null;
  gift_message?: string | null;
  pieces_used?: number;
  pieces_total?: number;
  grams_used?: number;
  grams_total?: number;
  plate_size?: string | null;
  capacity_used?: number | null;
  capacity_total?: number | null;
  contents?: Array<{
    product_id: number;
    name: string | null;
    quantity: number;
    slots_used: number;
  }>;
}

export interface CartState {
  conversation_id: string;
  cart_draft_id: number | null;
  status: "building" | "reviewed" | "confirmed" | "abandoned";
  items: CartItem[];
  total_price: number;
}

export interface ConfirmResult {
  conversation_id: string;
  order_id: number;
  status: "pending_handoff" | "sent_to_checkout";
  total_price: number;
  // Populated by the checkout adapter in Phase 4 when a redirect is available.
  redirect_url?: string | null;
  // Set when the handoff didn't complete; the order is still safely saved.
  handoff_error?: string | null;
  // What the widget replays into the store's own cart, and where that API lives.
  store_lines?: StoreLine[];
  store_api_base?: string;
}

export async function reportHandoff(
  conversationId: string,
  orderId: number,
  report: { success: boolean; failed_items: string[]; error?: string }
): Promise<{ order_id: number; status: string }> {
  return asJson(
    await fetch(
      `/api/order/${encodeURIComponent(conversationId)}/${orderId}/handoff-result`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(report),
      }
    )
  );
}

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export async function getCart(conversationId: string): Promise<CartState> {
  return asJson<CartState>(await fetch(`/api/cart/${encodeURIComponent(conversationId)}`));
}

export async function reviewCart(conversationId: string): Promise<CartState> {
  return asJson<CartState>(
    await fetch(`/api/cart/${encodeURIComponent(conversationId)}/review`, { method: "POST" })
  );
}

export async function confirmOrder(conversationId: string): Promise<ConfirmResult> {
  return asJson<ConfirmResult>(
    await fetch(`/api/order/${encodeURIComponent(conversationId)}/confirm`, { method: "POST" })
  );
}

// --------------------------------------------------------------------------- //
// Catalog
// --------------------------------------------------------------------------- //
export interface Product {
  id: number;
  name: string;
  description: string | null;
  price: number | null;
  image_url: string | null;
  category: string | null;
  is_single_item: boolean;
}

export interface PlateSize {
  id: number;
  name: string;
  capacity: number;
  base_price: number;
  image_url: string | null;
}

export async function listProducts(category?: string): Promise<Product[]> {
  const q = category ? `?category=${encodeURIComponent(category)}` : "";
  return asJson<Product[]>(await fetch(`/api/products${q}`));
}

export async function listPlateSizes(): Promise<PlateSize[]> {
  return asJson<PlateSize[]>(await fetch("/api/plate-sizes"));
}

// --------------------------------------------------------------------------- //
// Streaming chat (SSE over fetch)
// --------------------------------------------------------------------------- //
// UI-block shapes mirror the backend exactly (tools.py / cart.py). The plate
// builder's `price` is the authoritative base_price + Σ(filling unit_price × qty)
// computed server-side — the client only displays it, never recomputes capacity.
export interface ProductCardData {
  product_id: number | null;
  name: string | null;
  description: string | null;
  price: number | null;
  category?: string | null;
}

export interface PlateBuilderItem {
  product_id: number;
  name: string | null;
  quantity: number;
  slots_used: number;
  unit_price: number;
  line_total: number;
}

export interface PlateBuilderData {
  cart_item_id: number;
  plate_size: string | null;
  capacity_used: number;
  capacity_total: number | null;
  items: PlateBuilderItem[];
  base_price: number;
  price: number;
}

export interface ReviewButtonData {
  cart_draft_id: number;
}

export type UiBlock =
  | { type: "product_card"; data: ProductCardData }
  | { type: "plate_builder"; data: PlateBuilderData }
  | { type: "review_order_button"; data: ReviewButtonData };

export type ChatEvent =
  | { type: "conversation"; conversation_id: string }
  | { type: "token"; text: string }
  | { type: "tool_call"; name: string; arguments: Record<string, unknown> }
  | { type: "ui_block"; block: UiBlock }
  | { type: "done"; reply_text?: string; ui_blocks?: UiBlock[]; error?: boolean }
  // Always the final frame of a turn, streamed after "done" - the visible
  // reply is already complete by the time this arrives (see api/app/services/chat.py).
  | { type: "suggestions_block"; suggestions: string[] };

/**
 * The fixed opening suggestions shown before any conversation exists (no
 * context yet to derive follow-ups from). Backend-owned so wording stays in
 * one place; falls back to [] (hides the chip row) if the request fails.
 */
export async function getGreetingSuggestions(): Promise<string[]> {
  try {
    const data = await asJson<{ suggestions: string[] }>(
      await fetch("/api/chat/suggestions/greeting")
    );
    return data.suggestions ?? [];
  } catch {
    return [];
  }
}

/**
 * POST /api/chat and dispatch each Server-Sent Event to `onEvent` as it
 * arrives, so the UI can render tokens incrementally. Resolves when the stream
 * ends; rejects on network error or abort.
 */
export async function streamChat(
  message: string,
  conversationId: string | null,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const resp = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  });

  if (!resp.ok || !resp.body) {
    throw new Error(resp.statusText || "Chat request failed.");
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  // SSE frames are separated by a blank line; each frame's payload is on
  // `data:` lines. We buffer partial frames across chunk boundaries.
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const dataLine = frame
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim())
        .join("");
      if (!dataLine) continue;
      try {
        onEvent(JSON.parse(dataLine) as ChatEvent);
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}
