import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import OrderSummaryCard from "./OrderSummaryCard";
import type { CartState } from "../api";

const cart: CartState = {
  conversation_id: "c",
  cart_draft_id: 1,
  status: "reviewed",
  items: [],
  total_price: 990,
  totals: {
    subtotal: 990,
    vat_rate: 0.05,
    vat: 49.5,
    total_with_vat: 1039.5,
    shipping: "calculated at checkout",
    promo: "promo codes are applied at checkout",
    total_label: "Total before shipping and promo",
  },
};

describe("OrderSummaryCard totals", () => {
  it("reads like the shop checkout: subtotal, VAT, shipping, promo, total", () => {
    render(<OrderSummaryCard cart={cart} />);
    const totals = screen.getByRole("group", { name: "Order totals" });
    expect(within(totals).getByText("Subtotal")).toBeInTheDocument();
    expect(within(totals).getByText("990.00 AED")).toBeInTheDocument();
    expect(within(totals).getByText("VAT (5%)")).toBeInTheDocument();
    expect(within(totals).getByText("49.50 AED")).toBeInTheDocument();
    expect(within(totals).getByText("Shipping")).toBeInTheDocument();
    expect(within(totals).getByText("Calculated at checkout")).toBeInTheDocument();
    expect(within(totals).getByText("Promo code")).toBeInTheDocument();
    expect(within(totals).getByText("Applied at checkout")).toBeInTheDocument();
    expect(within(totals).getByText("Total before shipping and promo")).toBeInTheDocument();
    expect(within(totals).getByText("1039.50 AED")).toBeInTheDocument();
  });

  it("falls back to an honest subtotal label when the server sent no totals", () => {
    render(<OrderSummaryCard cart={{ ...cart, totals: undefined }} />);
    expect(screen.getByText("Subtotal (before VAT, delivery and promo)")).toBeInTheDocument();
    expect(screen.getByText("990.00 AED")).toBeInTheDocument();
  });
});
