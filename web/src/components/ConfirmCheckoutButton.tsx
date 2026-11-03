import { useCallback, useEffect, useState } from "react";
import { confirmOrder, getCart, type ConfirmResult } from "../api";

// Only ever link to http(s) URLs (never javascript:, data:, etc).
function isHttpUrl(value: string): boolean {
  try {
    const { protocol } = new URL(value);
    return protocol === "https:" || protocol === "http:";
  } catch {
    return false;
  }
}

// The one persistent, non-per-message checkout action (design doc section 6).
// It is enabled ONLY when the server reports the cart_draft is in 'reviewed'
// state - we verify against the API, not local state alone, so a cart modified
// after review (which the backend reverts to 'building') correctly re-disables
// the button.
export default function ConfirmCheckoutButton({
  conversationId,
}: {
  conversationId: string;
}) {
  const [status, setStatus] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ConfirmResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const cart = await getCart(conversationId);
      setStatus(cart.status);
    } catch {
      setStatus(null);
    }
  }, [conversationId]);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const onConfirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await confirmOrder(conversationId);
      setResult(res);
      // The checkout link (if any) is shown as a button rather than an
      // automatic redirect: the guest chooses when to leave the chat, and a
      // long URL is never shown or silently navigated to.
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      // A failed confirm may mean the review lapsed - re-check the real status.
      void refreshStatus();
    } finally {
      setSubmitting(false);
    }
  };

  // Outcome view: order captured (stub) or redirecting (future).
  if (result) {
    if (result.redirect_url && isHttpUrl(result.redirect_url)) {
      return (
        <div style={{ padding: "0.75rem 1rem", background: "#eef6ec", borderRadius: 10 }}>
          <strong>Your order is saved (#{result.order_id}).</strong>
          <p style={{ margin: "0.25rem 0 0.75rem", color: "#3f5136" }}>
            Continue to checkout to complete your order.
          </p>
          <a
            href={result.redirect_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: "inline-block",
              padding: "0.7rem 1.5rem",
              borderRadius: 999,
              background: "#1d2f15",
              color: "#faf7f2",
              fontWeight: 700,
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              fontSize: 12,
              textDecoration: "none",
            }}
          >
            Continue to checkout
          </a>
        </div>
      );
    }
    return (
      <div style={{ padding: "0.75rem 1rem", background: "#eef6ec", borderRadius: 10 }}>
        <strong>Your order is saved.</strong>
        <p style={{ margin: "0.25rem 0 0", color: "#3f5136" }}>
          Thank you — we've captured your order (#{result.order_id}) and our boutique will
          be in touch to finalise it.
        </p>
      </div>
    );
  }

  const reviewed = status === "reviewed";

  return (
    <div>
      <button
        onClick={onConfirm}
        disabled={!reviewed || submitting}
        style={{
          height: 44,
          padding: "0 1.5rem",
          borderRadius: 999,
          border: "none",
          cursor: reviewed && !submitting ? "pointer" : "not-allowed",
          background: reviewed ? "#1d2f15" : "#c9c3b8",
          color: "#faf7f2",
          fontWeight: 700,
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          fontSize: 12,
        }}
      >
        {submitting ? "Confirming…" : "Confirm & Checkout"}
      </button>
      {!reviewed && (
        <p style={{ margin: "0.5rem 0 0", color: "#6d7081", fontSize: 13 }}>
          Review your order to enable checkout.
        </p>
      )}
      {error && (
        <p style={{ margin: "0.5rem 0 0", color: "#a33", fontSize: 13 }}>{error}</p>
      )}
    </div>
  );
}
