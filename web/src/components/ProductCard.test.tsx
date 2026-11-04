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

  it("never labels a price '/ piece' on a shop card", () => {
    render(
      <ProductCard
        data={{ product_id: 2, name: "Ajwa Date", description: null, price: 6, category: "Individual Dates" }}
      />
    );
    expect(screen.queryByText(/piece/i)).not.toBeInTheDocument();
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

    expect(onAdd).toHaveBeenCalledWith("Golden Sukkari Dates (1kg)", undefined);
  });
});

describe("ProductCard variants", () => {
  const data = {
    product_id: 9,
    name: "Khudri Dates with Almond",
    description: null,
    price: 110,
    price_from: 110,
    variants: [
      { variant_id: 1, label: "500g / S", price: 110 },
      { variant_id: 2, label: "500g / M", price: 120 },
      { variant_id: 3, label: "1kg / L", price: 245 },
    ],
  };

  it("shows every option with its own price and 'From' until one is picked", () => {
    render(<ProductCard data={data} onAdd={vi.fn()} />);
    expect(screen.getByText("From 110 AED")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "500g / M 120 AED" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "1kg / L 245 AED" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add to order" })).toBeDisabled();
  });

  it("adds the chosen variant at its price", async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(<ProductCard data={data} onAdd={onAdd} />);
    await user.click(screen.getByRole("radio", { name: "500g / M 120 AED" }));
    expect(screen.getByText("120 AED")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add to order" }));
    expect(onAdd).toHaveBeenCalledWith("Khudri Dates with Almond", {
      variant_id: 2,
      label: "500g / M",
      price: 120,
    });
  });

  it("preselects the only option", async () => {
    const onAdd = vi.fn();
    const user = userEvent.setup();
    render(
      <ProductCard data={{ ...data, variants: [data.variants[0]] }} onAdd={onAdd} />
    );
    await user.click(screen.getByRole("button", { name: "Add to order" }));
    expect(onAdd).toHaveBeenCalledWith("Khudri Dates with Almond", data.variants[0]);
  });
});
