// Embeddable entry: one <script> tag on the store page mounts the floating
// concierge inside a shadow root so neither side's CSS can leak into the other.
//
//   <script src="https://CHAT_DOMAIN/widget.js" data-api="https://CHAT_DOMAIN" async></script>
import React from "react";
import ReactDOM from "react-dom/client";
import ChatWidget from "./components/ChatWidget";
import { setApiBase } from "./api";
import css from "./theme/global.css?raw";

const FONTS_HREF =
  "https://fonts.googleapis.com/css2?family=Aboreto&family=Cinzel:wght@400;500;600;700&family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Space+Grotesk:wght@300;400;500;600;700&family=Montserrat:wght@300;400;500;600;700&display=swap";
const HOST_ID = "lds-chat-host";

function currentLang(): string {
  try {
    return (
      window.localStorage.getItem("la_dolce_lang") ?? // the store's own key
      window.localStorage.getItem("lang") ??
      (document.documentElement.lang || "en")
    );
  } catch {
    return document.documentElement.lang || "en";
  }
}

export function mountWidget(script: HTMLScriptElement | null): HTMLElement | null {
  if (document.getElementById(HOST_ID)) return document.getElementById(HOST_ID);

  // data-api defaults to the origin the script was served from.
  let api = script?.dataset.api;
  if (!api && script?.src) {
    try {
      api = new URL(script.src, window.location.href).origin;
    } catch {
      /* fall through to same origin */
    }
  }
  setApiBase(api ?? "");

  // @font-face declared inside a shadow tree is ignored by browsers, so the
  // brand fonts are loaded once on the host document.
  if (!document.querySelector(`link[href="${FONTS_HREF}"]`)) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = FONTS_HREF;
    document.head.appendChild(link);
  }

  // A custom-element tag so host-page rules aimed at `div` never match it.
  const host = document.createElement("lds-chat");
  host.id = HOST_ID;
  document.body.appendChild(host);
  const shadow = host.attachShadow({ mode: "open" });

  const style = document.createElement("style");
  // `:root` variables must target the shadow host instead.
  // `all: initial` stops inherited host-page properties (letter-spacing, font...)
  // from crossing into the shadow tree.
  style.textContent = ":host{all:initial}" + css.replace(/:root/g, ":host");
  shadow.appendChild(style);

  const rtl = /^ar/i.test(currentLang());
  const mount = document.createElement("div");
  mount.dir = rtl ? "rtl" : "ltr";
  mount.lang = rtl ? "ar" : "en";
  shadow.appendChild(mount);

  ReactDOM.createRoot(mount).render(
    <React.StrictMode>
      <ChatWidget />
    </React.StrictMode>
  );
  return host;
}

// Auto-mount when loaded as a script (not when imported by tests).
if (typeof document !== "undefined" && !import.meta.env.VITEST) {
  const script = document.currentScript as HTMLScriptElement | null;
  const run = () => mountWidget(script);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
}
