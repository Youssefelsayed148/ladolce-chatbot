import { useState } from "react";
import type { ProductCardData } from "../api";
import { colors, fonts, radius, shadows, space, motion, gradients } from "../theme/tokens";

// Weight-tiered products (individual dates sold by 500g/1kg pack, per the
// original scrape's `variant` field) don't have a dedicated DB column for
// the tier - the catalog seed folds it into the product name instead, e.g.
// "Golden Sukkari Dates (500g)" and "Golden Sukkari Dates (1kg)" as two
// distinct product rows/cards (see seed_catalog.py's _product_name). Pull
// the tier back out here so the card can label the price with its weight
// ("500g — 65 AED") instead of showing a bare, unexplained number - the
// full folded name (still passed to onAdd) is what keeps "add to order"
// unambiguous between tiers.
const VARIANT_SUFFIX_RE = /^(.*?)\s*\((\d+(?:\.\d+)?\s*(?:g|kg))\)$/i;

function parseVariant(name: string | null): { baseName: string; weight: string } | null {
  if (!name) return null;
  const match = name.match(VARIANT_SUFFIX_RE);
  return match ? { baseName: match[1], weight: match[2] } : null;
}

// The one category genuinely sold per single piece (as opposed to a weighed
// pack, or a whole gift box/tray priced as one indivisible item) - see
// seed_catalog.py. Without this label, "Golden Sukkari Date — 6 AED" sits
// next to "Golden Sukkari Dates (500g) — 65 AED" with no unit on the
// cheaper card, reading as inconsistent/wrong even though both are correct.
const PER_PIECE_CATEGORY = "Individual Dates";

/**
 * A single recommended/searched product. The chat `product_card` block carries
 * name/description/price but no image; the widget enriches `imageUrl` from the
 * catalog (GET /api/products) when it can, and we fall back to a branded gold
 * monogram tile otherwise. `onAdd`, when provided, is the "add to plate"
 * affordance — it asks the concierge to add the item (the assistant drives all
 * cart mutations server-side, so there's no fake client-side add).
 */
export default function ProductCard({
  data,
  imageUrl,
  onAdd,
}: {
  data: ProductCardData;
  imageUrl?: string | null;
  onAdd?: (name: string) => void;
}) {
  const [hover, setHover] = useState(false);
  const variant = parseVariant(data.name);
  const displayName = variant ? variant.baseName : data.name;
  const priceLabel =
    data.price != null
      ? variant
        ? `${variant.weight} — ${Number(data.price).toFixed(0)} AED`
        : data.category === PER_PIECE_CATEGORY
          ? `${Number(data.price).toFixed(0)} AED / piece`
          : `${Number(data.price).toFixed(0)} AED`
      : null;

  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "flex",
        gap: space.md,
        padding: space.md,
        background: colors.ivory,
        border: `1px solid ${colors.border}`,
        borderRadius: radius.lg,
        boxShadow: hover ? shadows.card : "none",
        transform: hover ? "translateY(-2px)" : "translateY(0)",
        transition: `box-shadow ${motion.base}, transform ${motion.base}`,
        maxWidth: 320,
      }}
    >
      <div
        aria-hidden={!imageUrl}
        style={{
          flex: "0 0 64px",
          width: 64,
          height: 64,
          borderRadius: radius.md,
          overflow: "hidden",
          background: imageUrl ? colors.creamDeep : gradients.gold,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {imageUrl ? (
          <img
            src={imageUrl}
            alt={displayName ?? "Product"}
            loading="lazy"
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          <span
            style={{
              fontFamily: fonts.display,
              color: colors.darkGreen,
              fontSize: 24,
              lineHeight: 1,
            }}
          >
            L
          </span>
        )}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: space.sm,
            alignItems: "baseline",
          }}
        >
          <h4
            style={{
              margin: 0,
              fontFamily: fonts.heading,
              fontSize: 17,
              fontWeight: 600,
              color: colors.darkGreen,
              lineHeight: 1.2,
            }}
          >
            {displayName ?? "Untitled"}
          </h4>
          {priceLabel && (
            <span
              style={{
                fontFamily: fonts.body,
                fontSize: 13,
                fontWeight: 600,
                color: colors.green,
                whiteSpace: "nowrap",
              }}
            >
              {priceLabel}
            </span>
          )}
        </div>

        {data.description && (
          <p
            style={{
              margin: `${space.xs}px 0 0`,
              fontFamily: fonts.body,
              fontSize: 13,
              lineHeight: 1.45,
              color: colors.textMuted,
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
            }}
          >
            {data.description}
          </p>
        )}

        {onAdd && data.name && (
          <button
            type="button"
            onClick={() => onAdd(data.name as string)}
            style={{
              marginTop: space.sm,
              padding: "6px 14px",
              fontFamily: fonts.body,
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: colors.darkGreen,
              background: "transparent",
              border: `1px solid ${colors.gold}`,
              borderRadius: radius.pill,
              cursor: "pointer",
              transition: `background ${motion.fast}, color ${motion.fast}`,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = colors.gold;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
            }}
          >
            Add to order
          </button>
        )}
      </div>
    </div>
  );
}

/** Skeleton placeholder shown while catalog/recommendations stream in. */
export function ProductCardSkeleton() {
  const shimmer: React.CSSProperties = {
    background: `linear-gradient(90deg, ${colors.creamDeep} 25%, ${colors.divider} 37%, ${colors.creamDeep} 63%)`,
    backgroundSize: "320px 100%",
    animation: "lds-shimmer 1.3s ease-in-out infinite",
    borderRadius: radius.sm,
  };
  return (
    <div
      aria-hidden
      style={{
        display: "flex",
        gap: space.md,
        padding: space.md,
        background: colors.ivory,
        border: `1px solid ${colors.border}`,
        borderRadius: radius.lg,
        maxWidth: 320,
      }}
    >
      <div style={{ ...shimmer, width: 64, height: 64, borderRadius: radius.md }} />
      <div style={{ flex: 1 }}>
        <div style={{ ...shimmer, height: 16, width: "70%" }} />
        <div style={{ ...shimmer, height: 12, width: "100%", marginTop: 10 }} />
        <div style={{ ...shimmer, height: 12, width: "45%", marginTop: 6 }} />
      </div>
    </div>
  );
}
