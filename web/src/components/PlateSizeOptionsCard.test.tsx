import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import PlateSizeOptionsCard from "./PlateSizeOptionsCard";
import MessageBubble from "./MessageBubble";

const sizes = [
  { plate_size_id: 1, name: "The Classic Petite", kind: "BOX", max_pieces: 18, capacity_grams: 350, price: 60, image_url: null },
  { plate_size_id: 2, name: "Small Round Tray", kind: "TRAY", max_pieces: 120, capacity_grams: 2000, price: 200, image_url: null },
];

describe("PlateSizeOptionsCard", () => {
  it("shows pieces, weight and price per size and reports the tapped one", async () => {
    const onChoose = vi.fn();
    render(<PlateSizeOptionsCard sizes={sizes} onChoose={onChoose} />);
    expect(screen.getByText("up to 18 pieces · up to 350g")).toBeInTheDocument();
    expect(screen.getByText("up to 120 pieces · up to 2kg")).toBeInTheDocument();
    expect(screen.getByText("200 AED")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("listitem", { name: /Small Round Tray/ }));
    expect(onChoose).toHaveBeenCalledWith("Small Round Tray");
  });
});

describe("MessageBubble markdown tables", () => {
  it("renders a GFM table as a real table, not raw pipes", () => {
    const text = "| Size | Price |\n|---|---|\n| Petite | 60 AED |";
    render(<MessageBubble message={{ id: "m", role: "assistant", text }} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Size" })).toBeInTheDocument();
    expect(screen.queryByText(/\|---\|/)).toBeNull();
  });
});
