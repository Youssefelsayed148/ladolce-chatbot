import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatWidget from "./ChatWidget";

type SSEEvent = Record<string, unknown>;

/** A ReadableStream of SSE frames, one per microtask tick so tests can
 * observe intermediate UI state (e.g. "still streaming") between frames. */
function sseBody(events: SSEEvent[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    async start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        // A real macrotask gap (not just a microtask) so tests can observe
        // intermediate "still streaming" UI state between frames.
        await new Promise((resolve) => setTimeout(resolve, 10));
      }
      controller.close();
    },
  });
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function installFetchMock(opts: { greeting: string[]; chatEvents: SSEEvent[] }) {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });

    if (url.startsWith("/api/chat/suggestions/greeting")) {
      return jsonResponse({ suggestions: opts.greeting });
    }
    if (url.startsWith("/api/products")) {
      return jsonResponse([]);
    }
    if (url === "/api/chat") {
      return new Response(sseBody(opts.chatEvents), {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      });
    }
    throw new Error(`unmocked fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

async function openWidget() {
  const user = userEvent.setup();
  render(<ChatWidget />);
  await user.click(screen.getByRole("button", { name: "Open concierge chat" }));
  return user;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChatWidget suggestion chips", () => {
  it("shows the curated greeting suggestions on open, with no prior conversation", async () => {
    installFetchMock({
      greeting: ["What are your bestsellers?", "Do you ship internationally?", "Build me a custom box"],
      chatEvents: [],
    });

    await openWidget();

    expect(await screen.findByRole("button", { name: "What are your bestsellers?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Do you ship internationally?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build me a custom box" })).toBeInTheDocument();
  });

  it("tapping a suggestion sends it exactly like typing and pressing send", async () => {
    const { fetchMock } = installFetchMock({
      greeting: ["Build me a custom box"],
      chatEvents: [
        { type: "conversation", conversation_id: "conv-1" },
        { type: "token", text: "Of course!" },
        { type: "done", reply_text: "Of course!", ui_blocks: [] },
        { type: "suggestions_block", suggestions: [] },
      ],
    });

    const user = await openWidget();
    const chip = await screen.findByRole("button", { name: "Build me a custom box" });
    await user.click(chip);

    // Same send path as typing: a user bubble with the chip's exact text.
    expect(await screen.findByText("Build me a custom box")).toBeInTheDocument();

    const chatCall = fetchMock.mock.calls.find(([u]) => u === "/api/chat");
    expect(chatCall).toBeTruthy();
    const body = JSON.parse((chatCall![1] as RequestInit).body as string);
    expect(body.message).toBe("Build me a custom box");

    await screen.findByText("Of course!");
  });

  it("hides chips while a response is streaming and swaps in new ones once it completes", async () => {
    installFetchMock({
      greeting: ["Build me a custom box"],
      chatEvents: [
        { type: "conversation", conversation_id: "conv-1" },
        { type: "token", text: "One moment." },
        { type: "done", reply_text: "One moment.", ui_blocks: [] },
        { type: "suggestions_block", suggestions: ["What flavours do you have?", "Show me gift boxes"] },
      ],
    });

    const user = await openWidget();
    const chip = await screen.findByRole("button", { name: "Build me a custom box" });
    await user.click(chip);

    // Mid-stream: the old chip set is gone and the new one hasn't arrived yet.
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Build me a custom box" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "What flavours do you have?" })).not.toBeInTheDocument();
    });

    // Once the turn (including its trailing suggestions_block) finishes, the
    // new chips replace the old set.
    expect(await screen.findByRole("button", { name: "What flavours do you have?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show me gift boxes" })).toBeInTheDocument();
  });
});
