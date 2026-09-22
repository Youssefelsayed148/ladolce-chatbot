import { useCallback, useEffect, useState } from "react";
import { confirmOrder, getCart, type ConfirmResult } from "../api";

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
      // Phase 4: if the checkout adapter returns a redirect, go there. Until
      // then the stub returns no redirect and the order is safely saved.
      if (res.redirect_url) {
        window.location.assign(res.redirect_url);
      }
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
    if (result.redirect_url) {
      return <p>Taking you to checkout…</p>;
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
