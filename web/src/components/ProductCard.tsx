import { useState } from "react";
import type { ProductCardData, ProductVariantOption } from "../api";
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
  onAdd?: (name: string, variant?: ProductVariantOption) => void;
}) {
  const [hover, setHover] = useState(false);
  const options = data.variants ?? [];
  const [pickedId, setPickedId] = useState<number | null>(
    options.length === 1 ? options[0].variant_id : null
  );
  const picked = options.find((v) => v.variant_id === pickedId) ?? null;
  const needsPick = options.length > 0 && !picked;
  const variant = options.length ? null : parseVariant(data.name);
  const displayName = variant ? variant.baseName : data.name;
  const aed = (n: number) => `${Number(n).toFixed(0)} AED`;
  const priceLabel = options.length
    ? picked
      ? aed(picked.price)
      : `From ${aed(data.price_from ?? Math.min(...options.map((v) => v.price)))}`
    : data.price != null && Number(data.price) <= 0
    ? null // a box filling has no price of its own
    : data.price != null
    ? variant
      ? `${variant.weight} — ${aed(data.price)}`
      : aed(data.price)
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

        {options.length > 1 && (
          <div
            role="radiogroup"
            aria-label="Size and weight"
            style={{ display: "flex", flexWrap: "wrap", gap: space.xs, marginTop: space.sm }}
          >
            {options.map((v) => {
              const on = v.variant_id === pickedId;
              return (
                <button
                  key={v.variant_id}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  aria-label={`${v.label} ${aed(v.price)}`}
                  onClick={() => setPickedId(v.variant_id)}
                  style={{
                    padding: "4px 10px",
                    fontFamily: fonts.body,
                    fontSize: 12,
                    color: colors.darkGreen,
                    background: on ? colors.gold : "transparent",
                    border: `1px solid ${colors.gold}`,
                    borderRadius: radius.pill,
                    cursor: "pointer",
                  }}
                >
                  {v.label} · {aed(v.price)}
                </button>
              );
            })}
          </div>
        )}

        {onAdd && data.name && (
          <button
            type="button"
            disabled={needsPick}
            title={needsPick ? "Choose a size or weight first" : undefined}
            onClick={() => onAdd(data.name as string, picked ?? undefined)}
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
              cursor: needsPick ? "not-allowed" : "pointer",
              opacity: needsPick ? 0.5 : 1,
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
