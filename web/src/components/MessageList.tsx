import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import MessageBubble, { type ChatMessage } from "./MessageBubble";
import { colors, fonts, space } from "../theme/tokens";

/**
 * Scrolling conversation log. It's an ARIA live region so assistant tokens are
 * announced as they stream. Auto-scrolls to the newest content unless the guest
 * has scrolled up to read history (we don't yank them back down).
 *
 * `renderBlocks` lets the parent (ChatWidget) attach the rich UI blocks
 * (product cards, plate builder, review button) to an assistant turn while
 * keeping their wiring — catalog images, add/remove/review callbacks — out of
 * this layout component.
 */
export default function MessageList({
  messages,
  thinking,
  renderBlocks,
}: {
  messages: ChatMessage[];
  thinking: boolean;
  renderBlocks?: (messageId: string) => ReactNode;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);

  // Track whether the view is pinned to the bottom (within a small threshold).
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  };

  const lastText = messages.length ? messages[messages.length - 1].text : "";
  useEffect(() => {
    if (pinnedRef.current) {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [messages.length, lastText, thinking]);

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="lds-scroll"
      role="log"
      aria-live="polite"
      aria-relevant="additions text"
      aria-label="Conversation with the La Dolce Saveur concierge"
      style={{
        flex: 1,
        overflowY: "auto",
        padding: `${space.md}px ${space.lg}px`,
        display: "flex",
        flexDirection: "column",
        gap: 2,
      }}
    >
      {messages.map((m) => (
        <div key={m.id}>
          <MessageBubble message={m} />
          {m.role === "assistant" && renderBlocks && (
            <div style={{ display: "flex", flexDirection: "column", gap: space.sm, margin: `${space.xs}px 0` }}>
              {renderBlocks(m.id)}
            </div>
          )}
        </div>
      ))}

      {thinking && <ThinkingIndicator />}
      <div ref={endRef} />
    </div>
  );
}

function ThinkingIndicator() {
  return (
    <div
      aria-label="The concierge is typing"
      style={{ display: "flex", alignItems: "center", gap: 4, padding: `${space.sm}px 2px` }}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: colors.gold,
            display: "inline-block",
            animation: `lds-dot 1.2s ease-in-out ${i * 0.16}s infinite`,
          }}
        />
      ))}
      <span
        style={{
          marginLeft: 6,
          fontFamily: fonts.body,
          fontSize: 12,
          color: colors.textMuted,
          fontStyle: "italic",
        }}
      >
        composing…
      </span>
    </div>
  );
}
