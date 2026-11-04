import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { colors, fonts, radius, space, motion } from "../theme/tokens";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
  error?: boolean;
}

/**
 * One conversation turn. User turns sit right on deep brand green; assistant
 * turns sit left on cream. While an assistant turn streams, a gold caret blinks
 * after the latest token.
 */
export default function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div
      className="lds-rise"
      style={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        alignItems: "flex-start",
        gap: space.xs,
        padding: `${space.xs}px 0`,
      }}
    >
      {!isUser && <AssistantAvatar />}
      <div
        style={{
          maxWidth: "82%",
          padding: `${space.sm + 2}px ${space.md + 2}px`,
          borderRadius: isUser
            ? `${radius.lg}px ${radius.lg}px 4px ${radius.lg}px`
            : `${radius.lg}px ${radius.lg}px ${radius.lg}px 4px`,
          background: isUser ? colors.darkGreen : colors.cream,
          color: isUser ? colors.creamSoft : colors.darkGreen,
          border: isUser ? "none" : `1px solid ${colors.divider}`,
          fontFamily: fonts.body,
          fontSize: 14,
          lineHeight: 1.5,
          textAlign: "left",
          // User turns are the guest's own literal typed text (never parsed as
          // markdown) so single newlines must render as-is; assistant turns
          // render through Markdown below, whose <p>/<li> elements provide
          // their own block spacing instead.
          whiteSpace: isUser ? "pre-wrap" : undefined,
          wordBreak: "break-word",
          transition: `background ${motion.fast}`,
        }}
      >
        {isUser ? (
          message.text
        ) : (
          <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{message.text}</Markdown>
        )}
        {message.streaming && <span className="lds-caret" aria-hidden />}
        {message.error && message.text === "" && (
          <span style={{ color: colors.danger }}>Something went wrong.</span>
        )}
      </div>
    </div>
  );
}

// The concierge's replies arrive as markdown (bold product names, numbered/
// bulleted enumerations of flavours or gift options) - previously rendered as
// a raw text node, so guests saw literal "**...**" asterisks and "1. " list
// markers instead of styled text. These overrides just fit react-markdown's
// default elements to the bubble's typography/spacing; they carry no markup
// of their own beyond what the message text already contains.
const markdownComponents: Components = {
  p: ({ children }) => (
    <p style={{ margin: `${space.xs}px 0`, textAlign: "left" }}>{children}</p>
  ),
  strong: ({ children }) => <strong style={{ fontWeight: 700 }}>{children}</strong>,
  ul: ({ children }) => (
    <ul style={{ margin: `${space.xs}px 0`, paddingLeft: space.lg, textAlign: "left" }}>
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol style={{ margin: `${space.xs}px 0`, paddingLeft: space.lg, textAlign: "left" }}>
      {children}
    </ol>
  ),
  li: ({ children }) => <li style={{ margin: `${space.xs / 2}px 0` }}>{children}</li>,
  // Safety net: if the model still emits a GFM table, show it as a compact
  // scrollable table instead of raw pipe characters.
  table: ({ children }) => (
    <div style={{ overflowX: "auto", margin: `${space.xs}px 0` }}>
      <table style={{ borderCollapse: "collapse", fontSize: 12, width: "100%" }}>{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th
      style={{
        textAlign: "left",
        padding: "4px 8px",
        borderBottom: `1px solid ${colors.border}`,
        fontWeight: 700,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td style={{ padding: "4px 8px", borderBottom: `1px solid ${colors.divider}` }}>{children}</td>
  ),
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" style={{ color: colors.darkGreen }}>
      {children}
    </a>
  ),
};

/** Small flat date-fruit-and-leaf mark, gold-toned, beside each assistant turn. */
function AssistantAvatar() {
  return (
    <svg
      width="26"
      height="26"
      viewBox="0 0 26 26"
      fill="none"
      aria-hidden
      style={{ flexShrink: 0, marginTop: space.sm }}
    >
      <ellipse cx="13" cy="15.5" rx="7.5" ry="8.5" fill={colors.gold} />
      <path d="M6.5 13 Q13 15.5 19.5 13" stroke={colors.goldMuted} strokeWidth="0.75" fill="none" opacity={0.6} />
      <path d="M6.5 17 Q13 19.5 19.5 17" stroke={colors.goldMuted} strokeWidth="0.75" fill="none" opacity={0.6} />
      <path d="M13 7.5 V4" stroke={colors.goldMuted} strokeWidth="1" strokeLinecap="round" />
      <path d="M13 5.5 C15 3.5 18 4 19 6 C17 7 14.5 7 13 5.5 Z" fill={colors.goldLight} />
    </svg>
  );
}
