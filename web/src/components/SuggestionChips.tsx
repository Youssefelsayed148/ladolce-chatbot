import { useState } from "react";
import { colors, fonts, motion, radius, shadows, space } from "../theme/tokens";

/**
 * Tappable follow-up questions shown above the composer (Phase 6). The set is
 * entirely backend-driven — this component just renders whatever list it's
 * given and reports taps back via `onSelect`; ChatWidget decides when that
 * list is the fixed greeting set vs. a turn's generated suggestions, and when
 * to hide the row (empty list, or a response still streaming).
 */
export default function SuggestionChips({
  suggestions,
  onSelect,
}: {
  suggestions: string[];
  onSelect: (text: string) => void;
}) {
  if (!suggestions.length) return null;

  return (
    <div
      role="group"
      aria-label="Suggested questions"
      className="lds-scroll"
      style={{
        display: "flex",
        flexWrap: "nowrap",
        overflowX: "auto",
        gap: space.sm,
        padding: `0 ${space.lg}px ${space.sm}px`,
      }}
    >
      {suggestions.map((text, i) => (
        <Chip key={`${i}-${text}`} text={text} onClick={() => onSelect(text)} />
      ))}
    </div>
  );
}

function Chip({ text, onClick }: { text: string; onClick: () => void }) {
  const [focused, setFocused] = useState(false);

  return (
    <button
      type="button"
      onClick={onClick}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{
        flex: "0 0 auto",
        whiteSpace: "nowrap",
        padding: "8px 14px",
        borderRadius: radius.pill,
        border: `1px solid ${colors.border}`,
        background: colors.ivory,
        color: colors.darkGreen,
        fontFamily: fonts.body,
        fontSize: 12,
        fontWeight: 600,
        cursor: "pointer",
        boxShadow: focused ? shadows.focusRing : "none",
        outline: "none",
        transition: `box-shadow ${motion.fast}`,
      }}
    >
      {text}
    </button>
  );
}
