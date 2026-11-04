import type { CartState } from "../api";

// Itemized final view of the order (design doc section 6). Purely presentational
// - it renders whatever server-computed cart/summary state it's given.
export default function OrderSummaryCard({ cart }: { cart: CartState }) {
  return (
    <div
      style={{
        border: "1px solid #d9cbb8",
        borderRadius: 12,
        padding: "1rem 1.25rem",
        background: "#faf7f2",
        maxWidth: 460,
      }}
    >
      <h3 style={{ margin: "0 0 0.75rem", fontFamily: "'Cormorant Garamond', serif" }}>
        Your Order
      </h3>

      {cart.items.length === 0 && <p style={{ color: "#6d7081" }}>Your cart is empty.</p>}

      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {cart.items.map((item) => (
          <li
            key={item.cart_item_id}
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: "1rem",
              padding: "0.5rem 0",
              borderBottom: "1px solid #ece3d5",
            }}
          >
            <div>
              {item.type === "single_product" ? (
                <span>
                  {item.name}
                  {item.variant_label ? ` (${item.variant_label})` : ""} × {item.quantity}
                </span>
              ) : (
                <span>
                  {item.plate_size} (custom box ·{" "}
                  {item.pieces_total != null
                    ? `${item.pieces_used}/${item.pieces_total} pieces · ${item.grams_used}/${item.grams_total}g`
                    : `${item.capacity_used}/${item.capacity_total} slots`}
                  )
                  {item.finish && (
                    <div style={{ color: "#6d7081" }}>Ribbon: {item.finish}</div>
                  )}
                  {item.gift_message && (
                    <div style={{ color: "#6d7081" }}>Gift message: “{item.gift_message}”</div>
                  )}
                  {item.contents && item.contents.length > 0 && (
                    <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1rem", color: "#6d7081" }}>
                      {item.contents.map((c) => (
                        <li key={c.product_id}>
                          {c.name} × {c.quantity}
                        </li>
                      ))}
                    </ul>
                  )}
                </span>
              )}
            </div>
            <strong>{item.line_total.toFixed(2)} AED</strong>
          </li>
        ))}
      </ul>

      {cart.totals ? (
        <div role="group" aria-label="Order totals" style={{ marginTop: "0.75rem" }}>
          <TotalRow label="Subtotal" value={`${cart.totals.subtotal.toFixed(2)} AED`} />
          <TotalRow
            label={`VAT (${Math.round(cart.totals.vat_rate * 100)}%)`}
            value={`${cart.totals.vat.toFixed(1)} AED`}
          />
          <TotalRow
            label="Shipping"
            value={cart.totals.shipping_fee ? `${cart.totals.shipping_fee.toFixed(0)} AED` : "Free"}
          />
          <TotalRow
            label={cart.totals.total_label}
            value={`${cart.totals.total_estimated.toFixed(0)} AED`}
            bold
          />
          <TotalRow
            label="Promo code"
            value={`${cart.totals.promo_code}: ${cart.totals.promo_percent}% off, enter it at checkout`}
            muted
          />
        </div>
      ) : (
        <TotalRow
          label="Subtotal (before VAT, delivery and promo)"
          value={`${cart.total_price.toFixed(2)} AED`}
          bold
        />
      )}
    </div>
  );
}

function TotalRow({
  label,
  value,
  bold,
  muted,
}: {
  label: string;
  value: string;
  bold?: boolean;
  muted?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: "1rem",
        marginTop: "0.25rem",
        fontWeight: bold ? 700 : 400,
        color: muted ? "#6d7081" : undefined,
      }}
    >
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}
