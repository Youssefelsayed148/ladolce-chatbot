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

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: "0.75rem",
          fontWeight: 700,
        }}
      >
        <span>Total</span>
        <span>{cart.total_price.toFixed(2)} AED</span>
      </div>
    </div>
  );
}
