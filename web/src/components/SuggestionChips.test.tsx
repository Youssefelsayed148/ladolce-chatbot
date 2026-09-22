import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SuggestionChips from "./SuggestionChips";

describe("SuggestionChips", () => {
  it("renders nothing for an empty suggestion list", () => {
    const { container } = render(<SuggestionChips suggestions={[]} onSelect={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders each suggestion as a focusable button", () => {
    render(
      <SuggestionChips
        suggestions={["What are your bestsellers?", "Do you ship internationally?"]}
        onSelect={vi.fn()}
      />
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveTextContent("What are your bestsellers?");
    expect(buttons[1]).toHaveTextContent("Do you ship internationally?");
  });

  it("calls onSelect with the chip's text when tapped", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<SuggestionChips suggestions={["Build me a custom box"]} onSelect={onSelect} />);

    await user.click(screen.getByRole("button", { name: "Build me a custom box" }));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("Build me a custom box");
  });
});
