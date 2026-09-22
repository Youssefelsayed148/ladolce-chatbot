import ChatWidget from "./components/ChatWidget";
import { colors, fonts, gradients, space } from "./theme/tokens";

// Host page for the embeddable concierge widget. On the live site the widget
// mounts onto ladolcesaveur.com itself; here it sits on a brand-matched backdrop
// so the floating launcher + panel can be exercised end to end. ChatWidget
// composes MessageList / ProductCard / PlateBuilderCard internally, and the
// OrderSummaryCard + ConfirmCheckoutButton within its review sheet.
export default function App() {
  return (
    <main
      style={{
        minHeight: "100vh",
        background: gradients.green,
        color: colors.creamSoft,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: space.xl,
        textAlign: "center",
      }}
    >
      <div style={{ maxWidth: 620 }}>
        <div
          style={{
            fontFamily: fonts.eyebrow,
            fontSize: 12,
            letterSpacing: "0.34em",
            textTransform: "uppercase",
            color: colors.gold,
            marginBottom: space.md,
          }}
        >
          Maison de Dattes · Est. Riyadh
        </div>
        <h1
          style={{
            fontFamily: fonts.display,
            fontSize: "clamp(2.4rem, 6vw, 4rem)",
            fontWeight: 400,
            margin: 0,
            lineHeight: 1.05,
            letterSpacing: "0.02em",
          }}
        >
          La Dolce Saveur
        </h1>
        <p
          style={{
            fontFamily: fonts.heading,
            fontSize: "clamp(1.1rem, 2.4vw, 1.5rem)",
            fontStyle: "italic",
            color: colors.cream,
            margin: `${space.md}px 0 ${space.xl}px`,
            opacity: 0.9,
          }}
        >
          Gourmet dates, exquisite pastries, and luxury gifts — curated by our concierge.
        </p>
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: space.sm,
            fontFamily: fonts.body,
            fontSize: 14,
            color: colors.goldLight,
            border: `1px solid ${colors.gold}55`,
            borderRadius: 999,
            padding: `${space.sm}px ${space.lg}px`,
          }}
        >
          <span aria-hidden style={{ fontSize: 16 }}>↘</span>
          Tap the concierge to begin your order
        </div>
      </div>

      <ChatWidget />
    </main>
  );
}
