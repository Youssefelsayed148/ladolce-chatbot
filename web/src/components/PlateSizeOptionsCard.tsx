import { useState } from "react";
import type { PlateSizeOption } from "../api";
import { colors, fonts, radius, shadows, space, motion } from "../theme/tokens";

function formatWeight(grams: number | null): string | null {
  if (grams == null) return null;
  return grams >= 1000 ? `${+(grams / 1000).toFixed(2)}kg` : `${grams}g`;
}

/**
 * Box/tray size picker: one tappable row per size with capacity (pieces and
 * weight) and price. Tapping asks the concierge to start that box - the
 * assistant drives all cart changes server-side, like every other card.
 */
export default function PlateSizeOptionsCard({
  sizes,
  onChoose,
}: {
  sizes: PlateSizeOption[];
  onChoose?: (name: string) => void;
}) {
  return (
    <div
      role="list"
      aria-label="Custom box and tray sizes"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: space.xs,
        padding: space.sm,
        background: colors.ivory,
        border: `1px solid ${colors.border}`,
        borderRadius: radius.lg,
        maxWidth: 340,
      }}
    >
      {sizes.map((s) => (
        <SizeRow key={s.plate_size_id} size={s} onChoose={onChoose} />
      ))}
    </div>
  );
}

function SizeRow({ size, onChoose }: { size: PlateSizeOption; onChoose?: (name: string) => void }) {
  const [hover, setHover] = useState(false);
  const weight = formatWeight(size.capacity_grams);
  const capacity = [`up to ${size.max_pieces} pieces`, weight && `up to ${weight}`]
    .filter(Boolean)
    .join(" · ");

  return (
    <button
      type="button"
      role="listitem"
      onClick={() => onChoose?.(size.name)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-label={`${size.name}, ${capacity}, ${Number(size.price).toFixed(0)} AED`}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: space.md,
        padding: `${space.sm}px ${space.md}px`,
        textAlign: "left",
        cursor: onChoose ? "pointer" : "default",
        background: hover ? colors.creamDeep : "transparent",
        border: `1px solid ${hover ? colors.gold : colors.divider}`,
        borderRadius: radius.md,
        boxShadow: hover ? shadows.card : "none",
        transition: `background ${motion.fast}, border-color ${motion.fast}, box-shadow ${motion.fast}`,
      }}
    >
      <span style={{ minWidth: 0 }}>
        <span
          style={{
            display: "block",
            fontFamily: fonts.heading,
            fontSize: 16,
            fontWeight: 600,
            color: colors.darkGreen,
            lineHeight: 1.2,
          }}
        >
          {size.name}
        </span>
        <span style={{ display: "block", fontFamily: fonts.body, fontSize: 12, color: colors.textMuted, marginTop: 2 }}>
          {capacity}
        </span>
      </span>
      <span
        style={{
          flex: "0 0 auto",
          fontFamily: fonts.body,
          fontSize: 13,
          fontWeight: 700,
          color: colors.darkGreen,
          whiteSpace: "nowrap",
        }}
      >
        {Number(size.price).toFixed(0)} AED
      </span>
    </button>
  );
}
