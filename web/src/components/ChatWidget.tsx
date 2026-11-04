import { useCallback, useEffect, useRef, useState } from "react";
import {
  streamChat,
  listProducts,
  reviewCart,
  getGreetingSuggestions,
  type ChatEvent,
  type UiBlock,
  type CartState,
} from "../api";
import { colors, fonts, radius, shadows, space, layout, motion, gradients } from "../theme/tokens";
import MessageList from "./MessageList";
import type { ChatMessage } from "./MessageBubble";
import ProductCard, { ProductCardSkeleton } from "./ProductCard";
import PlateBuilderCard from "./PlateBuilderCard";
import PlateSizeOptionsCard from "./PlateSizeOptionsCard";
import OrderSummaryCard from "./OrderSummaryCard";
import ConfirmCheckoutButton from "./ConfirmCheckoutButton";
import SuggestionChips from "./SuggestionChips";

const STORAGE_KEY = "ladolce_conversation_id";

const GREETING: ChatMessage = {
  id: "greeting",
  role: "assistant",
  text:
    "Welcome to La Dolce Saveur. I'm your concierge — I can help you discover our " +
    "gourmet dates, compose a custom box, or find the perfect gift. What may I tempt you with?",
};

function uid(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
}

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([GREETING]);
  const [blocksByMessage, setBlocksByMessage] = useState<Record<string, UiBlock[]>>({});
  const [thinking, setThinking] = useState(false);
  const [sending, setSending] = useState(false);
  const [input, setInput] = useState("");
  const [productImages, setProductImages] = useState<Record<number, string | null>>({});
  const [cardsLoading, setCardsLoading] = useState<Record<string, boolean>>({});
  const [reviewAvailable, setReviewAvailable] = useState(false);
  const [reviewCart_, setReviewCart_] = useState<CartState | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const inputRef = useRef<HTMLTextAreaElement>(null);
  // The assistant turn currently receiving streamed tokens/blocks.
  const activeAssistantId = useRef<string | null>(null);

  // Restore the persisted conversation (server keeps the transcript; the client
  // list starts fresh, which is fine — context continues server-side).
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) setConversationId(stored);
  }, []);

  // Enrich product cards with real catalog imagery (the chat block has no image).
  useEffect(() => {
    if (!open || Object.keys(productImages).length) return;
    let cancelled = false;
    listProducts()
      .then((products) => {
        if (cancelled) return;
        const map: Record<number, string | null> = {};
        for (const p of products) map[p.id] = p.image_url;
        setProductImages(map);
      })
      .catch(() => {
        /* non-fatal: cards fall back to the branded monogram tile */
      });
    return () => {
      cancelled = true;
    };
  }, [open, productImages]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Fixed opening chips (no conversation yet, so no context to derive follow-
  // ups from) — fetched once, before the guest's first turn.
  useEffect(() => {
    if (!open || messages.length > 1) return;
    let cancelled = false;
    getGreetingSuggestions().then((s) => {
      if (!cancelled) setSuggestions(s);
    });
    return () => {
      cancelled = true;
    };
  }, [open, messages.length]);

  const patchAssistant = useCallback(
    (id: string, patch: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === id ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) } : m))
      );
    },
    []
  );

  const handleEvent = useCallback(
    (event: ChatEvent) => {
      const assistantId = activeAssistantId.current;
      switch (event.type) {
        case "conversation":
          setConversationId(event.conversation_id);
          localStorage.setItem(STORAGE_KEY, event.conversation_id);
          break;
        case "token":
          setThinking(false);
          if (assistantId) patchAssistant(assistantId, (m) => ({ text: m.text + event.text }));
          break;
        case "tool_call":
          // Surface a skeleton while the concierge searches the catalog; the
          // resulting product cards replace it when the ui_block events arrive.
          if (
            assistantId &&
            (event.name === "search_products" || event.name === "recommend_items")
          ) {
            setCardsLoading((prev) => ({ ...prev, [assistantId]: true }));
          }
          break;
        case "ui_block":
          if (event.block.type === "review_order_button") setReviewAvailable(true);
          if (event.block.type === "product_card" && assistantId) {
            setCardsLoading((prev) => ({ ...prev, [assistantId]: false }));
          }
          if (assistantId) {
            setBlocksByMessage((prev) => ({
              ...prev,
              [assistantId]: [...(prev[assistantId] ?? []), event.block],
            }));
          }
          break;
        case "done":
          // The visible reply is complete; only the chips are still to come, so
          // free the composer now instead of waiting for the stream to close.
          setThinking(false);
          setSending(false);
          if (assistantId) {
            setCardsLoading((prev) => ({ ...prev, [assistantId]: false }));
            patchAssistant(assistantId, (m) => ({
              streaming: false,
              error: event.error,
              // If the turn produced only tool output (no streamed text), fall
              // back to the server's final reply_text.
              text: m.text || event.reply_text || "",
            }));
          }
          break;
        case "suggestions_block":
          // Always the last frame of a turn (after "done") — replaces the
          // previous chip set outright, never stacks. An empty list is a
          // legitimate answer (e.g. after order confirmation) and correctly
          // hides the row, since SuggestionChips renders nothing for [].
          setSuggestions(event.suggestions);
          break;
        default:
          break;
      }
    },
    [patchAssistant]
  );

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || sending) return;

      const userMsg: ChatMessage = { id: uid(), role: "user", text: trimmed };
      const assistantId = uid();
      activeAssistantId.current = assistantId;
      setMessages((prev) => [
        ...prev,
        userMsg,
        { id: assistantId, role: "assistant", text: "", streaming: true },
      ]);
      setInput("");
      setSuggestions([]); // no stale chips while the next reply (and its chips) are on the way
      setSending(true);
      setThinking(true);

      try {
        await streamChat(trimmed, conversationId, handleEvent);
      } catch {
        patchAssistant(assistantId, (m) => ({
          streaming: false,
          error: true,
          text: m.text || "My apologies — I couldn't reach the boutique just now. Please try again.",
        }));
      } finally {
        setThinking(false);
        setSending(false);
        patchAssistant(assistantId, { streaming: false });
        inputRef.current?.focus();
      }
    },
    [conversationId, handleEvent, patchAssistant, sending]
  );

  const onReview = useCallback(async () => {
    if (!conversationId) return;
    try {
      const cart = await reviewCart(conversationId);
      setReviewCart_(cart);
      setReviewOpen(true);
    } catch {
      setReviewOpen(true); // still surface the sheet; ConfirmButton re-checks status
    }
  }, [conversationId]);

  const renderBlocks = useCallback(
    (messageId: string) => {
      const blocks = blocksByMessage[messageId];
      const loading = cardsLoading[messageId];
      const hasProductCards = blocks?.some((b) => b.type === "product_card");
      if (!blocks?.length) {
        return loading && !hasProductCards ? (
          <>
            <ProductCardSkeleton />
            <ProductCardSkeleton />
          </>
        ) : null;
      }
      // Each box change emits a fresh box card; only the latest is current.
      const lastPlateIdx = blocks.reduce((acc, b, i) => (b.type === "plate_builder" ? i : acc), -1);
      return blocks.map((block, i) => {
        if (block.type === "plate_builder" && i !== lastPlateIdx) return null;
        if (block.type === "product_card") {
          const pid = block.data.product_id;
          return (
            <ProductCard
              key={`${messageId}-${i}`}
              data={block.data}
              imageUrl={pid != null ? productImages[pid] : null}
              onAdd={(name) => void send(`I'd like to add ${name} to my order, please.`)}
            />
          );
        }
        if (block.type === "plate_size_options") {
          return (
            <PlateSizeOptionsCard
              key={`${messageId}-${i}`}
              sizes={block.data.sizes}
              onChoose={(name) => void send(`I'd like to build a custom box in ${name}.`)}
            />
          );
        }
        if (block.type === "plate_builder") {
          return (
            <PlateBuilderCard
              key={`${messageId}-${i}`}
              data={block.data}
              onRemove={(name) => void send(`Please remove ${name} from my box.`)}
            />
          );
        }
        // review_order_button is surfaced as the persistent footer action, not
        // an inline per-message button, so nothing is rendered inline here.
        return null;
      });
    },
    [blocksByMessage, cardsLoading, productImages, send]
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  };

  return (
    <div className="lds-root" style={{ position: "fixed", bottom: 24, right: 24, zIndex: layout.zWidget }}>
      {open && (
        <section
          role="dialog"
          aria-label="La Dolce Saveur concierge chat"
          style={{
            position: "absolute",
            bottom: layout.launcherSize + 16,
            right: 0,
            width: `min(${layout.panelWidth}px, calc(100vw - 32px))`,
            height: `min(${layout.panelHeight}px, calc(100vh - 120px))`,
            display: "flex",
            flexDirection: "column",
            background: colors.cream,
            borderRadius: radius.xl,
            boxShadow: shadows.panel,
            overflow: "hidden",
            animation: `lds-pop ${motion.panel} both`,
          }}
        >
          <Header onClose={() => setOpen(false)} />

          <MessageList messages={messages} thinking={thinking} renderBlocks={renderBlocks} />

          {reviewAvailable && !reviewOpen && (
            <div style={{ padding: `0 ${space.lg}px ${space.sm}px` }}>
              <button
                type="button"
                onClick={() => void onReview()}
                style={{
                  width: "100%",
                  height: 44,
                  border: "none",
                  borderRadius: radius.pill,
                  background: gradients.gold,
                  color: colors.darkGreen,
                  fontFamily: fonts.body,
                  fontSize: 12,
                  fontWeight: 700,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  cursor: "pointer",
                  boxShadow: shadows.card,
                }}
              >
                Review Order
              </button>
            </div>
          )}

          {reviewOpen && (
            <ReviewSheet
              cart={reviewCart_}
              conversationId={conversationId ?? ""}
              onBack={() => setReviewOpen(false)}
            />
          )}

          {!sending && !reviewOpen && (
            <SuggestionChips suggestions={suggestions} onSelect={(text) => void send(text)} />
          )}

          <Composer
            inputRef={inputRef}
            value={input}
            disabled={sending}
            onChange={setInput}
            onKeyDown={onKeyDown}
            onSend={() => void send(input)}
          />
        </section>
      )}

      <Launcher open={open} onClick={() => setOpen((v) => !v)} />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Sub-parts
// --------------------------------------------------------------------------- //
function Header({ onClose }: { onClose: () => void }) {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: `${space.md}px ${space.lg}px`,
        background: gradients.green,
        color: colors.creamSoft,
      }}
    >
      <div>
        <div
          style={{
            fontFamily: fonts.eyebrow,
            fontSize: 10,
            letterSpacing: "0.24em",
            textTransform: "uppercase",
            color: colors.gold,
          }}
        >
          Concierge
        </div>
        <div style={{ fontFamily: fonts.display, fontSize: 20, letterSpacing: "0.02em" }}>
          La Dolce Saveur
        </div>
      </div>
      <button
        type="button"
        aria-label="Close chat"
        onClick={onClose}
        style={{
          width: 34,
          height: 34,
          borderRadius: radius.pill,
          border: `1px solid ${colors.gold}55`,
          background: "transparent",
          color: colors.creamSoft,
          cursor: "pointer",
          fontSize: 18,
          lineHeight: 1,
        }}
      >
        ×
      </button>
    </header>
  );
}

function Composer({
  inputRef,
  value,
  disabled,
  onChange,
  onKeyDown,
  onSend,
}: {
  inputRef: React.RefObject<HTMLTextAreaElement>;
  value: string;
  disabled: boolean;
  onChange: (v: string) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-end",
        gap: space.sm,
        padding: space.md,
        borderTop: `1px solid ${colors.divider}`,
        background: colors.ivory,
      }}
    >
      <textarea
        ref={inputRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        rows={1}
        placeholder="Ask about our dates, gifts, or build a box…"
        aria-label="Message the concierge"
        style={{
          flex: 1,
          resize: "none",
          maxHeight: 96,
          padding: "10px 12px",
          border: `1px solid ${colors.border}`,
          borderRadius: radius.md,
          fontFamily: fonts.body,
          fontSize: 14,
          lineHeight: 1.4,
          color: colors.darkGreen,
          background: colors.cream,
          outline: "none",
        }}
      />
      <button
        type="button"
        aria-label="Send message"
        onClick={onSend}
        disabled={disabled || !value.trim()}
        style={{
          flex: "0 0 auto",
          width: 44,
          height: 44,
          borderRadius: radius.pill,
          border: "none",
          cursor: disabled || !value.trim() ? "not-allowed" : "pointer",
          background: value.trim() && !disabled ? colors.darkGreen : colors.border,
          color: colors.creamSoft,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transition: `background ${motion.fast}`,
        }}
      >
        <SendIcon />
      </button>
    </div>
  );
}

function ReviewSheet({
  cart,
  conversationId,
  onBack,
}: {
  cart: CartState | null;
  conversationId: string;
  onBack: () => void;
}) {
  return (
    <div
      style={{
        borderTop: `1px solid ${colors.divider}`,
        background: colors.cream,
        padding: space.lg,
        maxHeight: "58%",
        overflowY: "auto",
      }}
      className="lds-scroll"
    >
      <button
        type="button"
        onClick={onBack}
        style={{
          background: "transparent",
          border: "none",
          color: colors.textMuted,
          fontFamily: fonts.body,
          fontSize: 12,
          cursor: "pointer",
          padding: 0,
          marginBottom: space.sm,
        }}
      >
        ‹ Back to chat
      </button>
      {cart ? (
        <div style={{ display: "grid", gap: space.md }}>
          <OrderSummaryCard cart={cart} />
          <ConfirmCheckoutButton conversationId={conversationId} />
        </div>
      ) : (
        <p style={{ fontFamily: fonts.body, fontSize: 13, color: colors.textMuted }}>
          Preparing your order…
        </p>
      )}
    </div>
  );
}

function Launcher({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={open ? "Close concierge chat" : "Open concierge chat"}
      aria-expanded={open}
      onClick={onClick}
      style={{
        width: layout.launcherSize,
        height: layout.launcherSize,
        borderRadius: radius.pill,
        border: `2px solid ${colors.gold}`,
        background: gradients.green,
        boxShadow: shadows.launcher,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        transition: `transform ${motion.base}`,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "scale(1.05)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "scale(1)";
      }}
    >
      {open ? <span style={{ color: colors.gold, fontSize: 22, lineHeight: 1 }}>×</span> : <ChatGlyph />}
    </button>
  );
}

function ChatGlyph() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 3C6.98 3 3 6.36 3 10.5c0 2.02.98 3.86 2.6 5.2-.13 1.2-.6 2.3-1.3 3.1-.2.24-.03.6.28.56 1.7-.2 3.1-.78 4.1-1.5.98.28 2.02.44 3.02.44 5.02 0 9-3.36 9-7.5S17.02 3 12 3Z"
        fill={colors.gold}
      />
      <circle cx="8.5" cy="10.5" r="1.1" fill={colors.darkGreen} />
      <circle cx="12" cy="10.5" r="1.1" fill={colors.darkGreen} />
      <circle cx="15.5" cy="10.5" r="1.1" fill={colors.darkGreen} />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M3.4 20.4 21 12 3.4 3.6 3 10l12 2-12 2 .4 6.4Z" fill="currentColor" />
    </svg>
  );
}
