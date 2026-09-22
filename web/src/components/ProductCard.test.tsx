import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProductCard from "./ProductCard";

describe("ProductCard weight-tiered pricing", () => {
  it("labels the price with its weight tier for a variant-folded product name", () => {
    render(
      <ProductCard
        data={{
          product_id: 1,
          name: "Golden Sukkari Dates (500g)",
          description: null,
          price: 65,
        }}
      />
    );

    expect(screen.getByRole("heading", { name: "Golden Sukkari Dates" })).toBeInTheDocument();
    expect(screen.getByText("500g — 65 AED")).toBeInTheDocument();
  });

  it("labels the price '/ piece' for a per-piece Individual Dates product", () => {
    render(
      <ProductCard
        data={{
          product_id: 2,
          name: "Ajwa Date",
          description: null,
          price: 6,
          category: "Individual Dates",
        }}
      />
    );

    expect(screen.getByRole("heading", { name: "Ajwa Date" })).toBeInTheDocument();
    expect(screen.getByText("6 AED / piece")).toBeInTheDocument();
  });

  it("renders a plain price with no unit label outside Individual Dates (e.g. a whole gift box)", () => {
    render(
      <ProductCard
        data={{
          product_id: 4,
          name: "The Royal Assortment",
          description: null,
          price: 450,
          category: "Gift Boxes & Trays",
        }}
      />
    );

    expect(screen.getByText("450 AED")).toBeInTheDocument();
  });

  it("still sends the full, variant-qualified name when 'Add to order' is tapped", async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(
      <ProductCard
        data={{
          product_id: 3,
          name: "Golden Sukkari Dates (1kg)",
          description: null,
          price: 120,
        }}
        onAdd={onAdd}
      />
    );

    await user.click(screen.getByRole("button", { name: "Add to order" }));

    expect(onAdd).toHaveBeenCalledWith("Golden Sukkari Dates (1kg)");
  });
});
