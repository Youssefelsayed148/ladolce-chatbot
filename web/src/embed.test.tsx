import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "@testing-library/react";
import { mountWidget } from "./embed";

function scriptTag(attrs: Record<string, string>): HTMLScriptElement {
  const s = document.createElement("script");
  Object.entries(attrs).forEach(([k, v]) => s.setAttribute(k, v));
  return s;
}

afterEach(() => {
  document.getElementById("lds-chat-host")?.remove();
  document.head.replaceChildren();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("embeddable widget loader", () => {
  it("mounts once inside a shadow root with scoped styles and no host-page CSS", async () => {
    let host: HTMLElement | null = null;
    await act(async () => {
      host = mountWidget(scriptTag({ "data-api": "https://chat.example" }));
    });
    expect(host).not.toBeNull();
    const shadow = host!.shadowRoot!;
    expect(shadow.querySelector("style")!.textContent).toContain(".lds-root");
    expect(shadow.querySelector("style")!.textContent).not.toContain(":root");
    expect(shadow.querySelector("style")!.textContent).toContain(":host");
    // Only the font link touches the host document - no <style> leaks out.
    expect(document.head.querySelectorAll("style").length).toBe(0);
    // Second call is a no-op (one script tag, one widget).
    await act(async () => {
      mountWidget(null);
    });
    expect(document.querySelectorAll("#lds-chat-host").length).toBe(1);
  });

  it("renders right-to-left when the store language is Arabic", async () => {
    window.localStorage.setItem("lang", "ar");
    let host: HTMLElement | null = null;
    await act(async () => {
      host = mountWidget(scriptTag({ "data-api": "https://chat.example" }));
    });
    expect(host!.shadowRoot!.querySelector("[dir]")!.getAttribute("dir")).toBe("rtl");
  });

  it("sends API calls to the data-api base", async () => {
    const f = vi.fn(async (_u: string) => new Response(JSON.stringify({ suggestions: [] }), { status: 200 }));
    vi.stubGlobal("fetch", f);
    await act(async () => {
      mountWidget(scriptTag({ "data-api": "https://chat.example/" }));
    });
    const { getGreetingSuggestions } = await import("./api");
    await getGreetingSuggestions();
    expect(String(f.mock.calls[f.mock.calls.length - 1][0])).toBe("https://chat.example/api/chat/suggestions/greeting");
  });
});
