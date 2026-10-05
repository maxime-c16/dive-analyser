import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ProfileV1Classic from "./ProfileV1Classic";
import ProfileV2Sidebar from "./ProfileV2Sidebar";
import ProfileV3Diver from "./ProfileV3Diver";
import ProfilePreview from "./ProfilePreview";

function renderWithRouter(ui: React.ReactElement, initial = "/profile-preview") {
  return render(<MemoryRouter initialEntries={[initial]}>{ui}</MemoryRouter>);
}

describe("profile prototypes", () => {
  it("V1 renders tabs and switches to Security", () => {
    renderWithRouter(<ProfileV1Classic />);
    expect(screen.getByRole("tab", { name: /profile/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /security/i }));
    expect(screen.getAllByText(/change password/i).length).toBeGreaterThan(0);
  });

  it("V2 renders sidebar and switches section", () => {
    renderWithRouter(<ProfileV2Sidebar />);
    fireEvent.click(screen.getByRole("button", { name: /privacy/i }));
    expect(screen.getByText(/public profile/i)).toBeInTheDocument();
  });

  it("V3 renders diver stats", () => {
    renderWithRouter(<ProfileV3Diver />);
    expect(screen.getByText(/view public profile/i)).toBeInTheDocument();
    expect(screen.getByText("148")).toBeInTheDocument();
  });

  it("Preview switcher defaults to V1 and switches to V3", () => {
    renderWithRouter(<ProfilePreview />, "/profile-preview");
    expect(screen.getByRole("tab", { name: /profile/i })).toBeInTheDocument();
    renderWithRouter(<ProfilePreview />, "/profile-preview?v=3");
    expect(screen.getByText(/view public profile/i)).toBeInTheDocument();
  });
});
