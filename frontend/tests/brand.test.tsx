import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Brand, BrandIcon } from "../app/brand";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import logoUrl from "../app/assets/lazy-accountant-logo.svg?url";
import iconUrl from "../app/assets/lazy-accountant-icon.svg?url";

describe("approved product branding", () => {
  it("keeps the bundled assets identical to the approved README originals", () => {
    for (const name of ["lazy-accountant-logo.svg", "lazy-accountant-icon.svg"]) {
      const original = readFileSync(resolve("../docs/brand", name), "utf8");
      const bundled = readFileSync(resolve("app/assets", name), "utf8");
      expect(bundled).toBe(original);
    }
  });
  it("uses the shared README wordmark with an accessible name", () => {
    render(<Brand />);
    const image = screen.getByRole("img", { name: "Lazy Accountant" });
    expect(image).toHaveAttribute("src", logoUrl);
    expect(image).toHaveAttribute("width", "760");
    expect(image).toHaveAttribute("height", "224");
    expect(image).toHaveStyle({ maxWidth: "100%", height: "auto" });
  });

  it("allows the login to display a larger wordmark", () => {
    render(<Brand width={280} />);
    expect(screen.getByRole("img", { name: "Lazy Accountant" })).toHaveStyle({
      width: "280px",
    });
  });

  it("uses the shared standalone icon for the mobile header", () => {
    render(<BrandIcon />);
    // JSDOM does not evaluate responsive media queries; visibility is browser-checked.
    const image = screen.getByAltText("Lazy Accountant");
    expect(image).toHaveAttribute("src", iconUrl);
    expect(image).toHaveAttribute("width", "32");
    expect(image).toHaveAttribute("height", "32");
  });
});
