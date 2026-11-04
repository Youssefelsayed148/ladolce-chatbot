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
    shipping_fee: 0,
    free_shipping_min: 150,
    promo_code: "DOLCE",
    promo_percent: 15,
    total_estimated: 1040,
    total_label: "Estimated total",
  },
};

describe("OrderSummaryCard totals", () => {
  it("reads like the shop checkout: subtotal, VAT, shipping, promo, total", () => {
    render(<OrderSummaryCard cart={cart} />);
    const totals = screen.getByRole("group", { name: "Order totals" });
    expect(within(totals).getByText("Subtotal")).toBeInTheDocument();
    expect(within(totals).getByText("990.00 AED")).toBeInTheDocument();
    expect(within(totals).getByText("VAT (5%)")).toBeInTheDocument();
    expect(within(totals).getByText("49.5 AED")).toBeInTheDocument();
    expect(within(totals).getByText("Shipping")).toBeInTheDocument();
    expect(within(totals).getByText("Free")).toBeInTheDocument();
    expect(within(totals).getByText("Estimated total")).toBeInTheDocument();
    expect(within(totals).getByText("1040 AED")).toBeInTheDocument();
    expect(
      within(totals).getByText("DOLCE: 15% off, enter it at checkout")
    ).toBeInTheDocument();
  });

  it("shows the flat shipping fee under the free-shipping minimum", () => {
    render(
      <OrderSummaryCard
        cart={{ ...cart, totals: { ...cart.totals!, subtotal: 100, vat: 5, shipping_fee: 20, total_estimated: 125 } }}
      />
    );
    expect(screen.getByText("20 AED")).toBeInTheDocument();
    expect(screen.getByText("125 AED")).toBeInTheDocument();
  });

  it("falls back to an honest subtotal label when the server sent no totals", () => {
    render(<OrderSummaryCard cart={{ ...cart, totals: undefined }} />);
    expect(screen.getByText("Subtotal (before VAT, delivery and promo)")).toBeInTheDocument();
    expect(screen.getByText("990.00 AED")).toBeInTheDocument();
  });
});
