import type { PlateBuilderData } from "../api";
import { colors, fonts, radius, shadows, space, motion, gradients } from "../theme/tokens";

/**
 * Live custom-plate builder. Everything shown here is server-authoritative:
 * capacity (used/total) and the running total (base_price + Σ filling
 * unit_price × qty) come straight from the API — the client never computes
 * capacity or price. `onRemove` asks the concierge to remove a filling (the
 * assistant owns all cart mutations), keeping this component presentational.
 */
export default function PlateBuilderCard({
  data,
  onRemove,
}: {
  data: PlateBuilderData;
  onRemove?: (name: string) => void;
}) {
  const total = data.capacity_total ?? 0;
  const used = data.capacity_used ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const full = total > 0 && used >= total;

  return (
    <div
      role="group"
      aria-label={`Custom ${data.plate_size ?? "plate"} builder`}
      style={{
        background: colors.ivory,
        border: `1px solid ${colors.border}`,
        borderRadius: radius.lg,
        boxShadow: shadows.card,
        overflow: "hidden",
        maxWidth: 340,
      }}
    >
      {/* Header */}
      <div style={{ background: gradients.green, padding: `${space.md}px ${space.lg}px` }}>
        <div
          style={{
            fontFamily: fonts.eyebrow,
            fontSize: 10,
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            color: colors.gold,
          }}
        >
          Your Custom Creation
        </div>
        <div
          style={{
            fontFamily: fonts.heading,
            fontSize: 20,
            fontWeight: 600,
            color: colors.creamSoft,
            marginTop: 2,
          }}
        >
          {data.plate_size ?? "Custom Box"}
        </div>
      </div>

      <div style={{ padding: space.lg }}>
        {/* Capacity meter */}
        <div
          role="meter"
          aria-valuenow={used}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label="Slots filled"
          style={{ marginBottom: space.md }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontFamily: fonts.body,
              fontSize: 12,
              color: colors.textMuted,
              marginBottom: 6,
            }}
          >
            <span>{full ? "Box is full" : "Slots filled"}</span>
            <span style={{ fontWeight: 600, color: colors.darkGreen }}>
              {used} / {total}
            </span>
          </div>
          <div
            style={{
              height: 8,
              borderRadius: radius.pill,
              background: colors.creamDeep,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${pct}%`,
                height: "100%",
                borderRadius: radius.pill,
                background: full ? gradients.gold : colors.greenBright,
                transition: `width ${motion.base}`,
              }}
            />
          </div>
        </div>

        {/* Fillings */}
        {data.items.length === 0 ? (
          <p
            style={{
              margin: `${space.sm}px 0`,
              fontFamily: fonts.body,
              fontSize: 13,
              color: colors.textMuted,
              fontStyle: "italic",
            }}
          >
            No fillings yet — ask me to add your favourites.
          </p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {data.items.map((it) => (
              <li
                key={it.product_id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: space.sm,
                  padding: "8px 0",
                  borderBottom: `1px solid ${colors.divider}`,
                  fontFamily: fonts.body,
                  fontSize: 13,
                }}
              >
                <span style={{ flex: 1, color: colors.darkGreen }}>
                  {it.name ?? `#${it.product_id}`}
                  <span style={{ color: colors.textMuted }}> × {it.quantity}</span>
                </span>
                {it.unit_price > 0 ? (
                  <>
                    <span style={{ color: colors.textMuted, fontSize: 12 }}>
                      {it.unit_price.toFixed(0)} ea
                    </span>
                    <span style={{ fontWeight: 600, color: colors.darkGreen, minWidth: 52, textAlign: "right" }}>
                      {it.line_total.toFixed(0)} AED
                    </span>
                  </>
                ) : (
                  // Store boxes are priced by size only - the dates inside are free.
                  <span style={{ color: colors.textMuted, fontSize: 12, fontStyle: "italic" }}>included</span>
                )}
                {onRemove && it.name && (
                  <button
                    type="button"
                    aria-label={`Remove ${it.name}`}
                    onClick={() => onRemove(it.name as string)}
                    style={{
                      width: 22,
                      height: 22,
                      borderRadius: radius.pill,
                      border: `1px solid ${colors.border}`,
                      background: "transparent",
                      color: colors.textMuted,
                      cursor: "pointer",
                      lineHeight: 1,
                      fontSize: 14,
                      padding: 0,
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = colors.danger;
                      e.currentTarget.style.color = colors.creamSoft;
                      e.currentTarget.style.borderColor = colors.danger;
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "transparent";
                      e.currentTarget.style.color = colors.textMuted;
                      e.currentTarget.style.borderColor = colors.border;
                    }}
                  >
                    ×
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {/* Totals */}
        <div
          style={{
            marginTop: space.md,
            paddingTop: space.md,
            borderTop: `1px solid ${colors.divider}`,
          }}
        >
          <Row label={`Base (${data.plate_size ?? "box"})`} value={`${data.base_price.toFixed(0)} AED`} muted />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              marginTop: 6,
            }}
          >
            <span
              style={{
                fontFamily: fonts.eyebrow,
                fontSize: 11,
                letterSpacing: "0.16em",
                textTransform: "uppercase",
                color: colors.darkGreen,
              }}
            >
              Total
            </span>
            <span
              style={{
                fontFamily: fonts.heading,
                fontSize: 24,
                fontWeight: 700,
                color: colors.green,
              }}
            >
              {data.price.toFixed(0)} AED
            </span>
          </div>
        </div>

        {full && (
          <p
            style={{
              margin: `${space.sm}px 0 0`,
              fontFamily: fonts.body,
              fontSize: 12,
              color: colors.goldMuted,
            }}
          >
            This box is at capacity. Remove a filling or choose a larger size to add more.
          </p>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        fontFamily: fonts.body,
        fontSize: 13,
        color: muted ? colors.textMuted : colors.darkGreen,
      }}
    >
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}
