import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { APIError } from "../app/api";
import { ErrorAlert, Status } from "../app/components";

describe("deutsche Prüf- und Versandzustände", () => {
  it("bezeichnet SMTP-Annahme nicht als Zustellung", () => {
    render(<Status status="accepted" />);
    expect(screen.getByText("SMTP angenommen")).toBeInTheDocument();
    expect(screen.queryByText("Zugestellt")).not.toBeInTheDocument();
  });
  it("macht einen unbekannten Ausgang sichtbar", () => {
    render(<Status status="unknown" />);
    expect(screen.getByText("Ausgang unbekannt")).toBeInTheDocument();
  });
  it("zeigt Versionskonflikte samt Details, statt sie zu verbergen", () => {
    render(
      <ErrorAlert
        error={
          new APIError("Dokument wurde inzwischen geändert", 409, {
            current_version: 3,
          })
        }
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Dokument wurde inzwischen geändert",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("current_version");
  });
});
