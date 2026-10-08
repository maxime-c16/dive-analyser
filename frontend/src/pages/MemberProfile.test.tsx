import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, Link } from "react-router-dom";
import { I18nProvider } from "../i18n/I18nProvider";
import Account from "./Account";
import MemberProfile from "./MemberProfile";

vi.mock("../contexts/AuthContext", () => ({
  useAuth: () => ({
    user: {
      user_id: 7,
      email: "alex.moreau@example.com",
      display_name: "Alex Moreau",
      role: "friend",
      is_admin: false,
      divers: [],
    },
    checking: false,
    refresh: vi.fn(),
    signOut: vi.fn(),
  }),
}));

const pageOne = {
  items: [
    {
      key: "comment:5:u9:12",
      kind: "comment",
      direction: "received",
      created_at: "2026-10-05T10:00:00Z",
      actor: { user_id: 9, guest_id: null, display_name: "Bob Marlin" },
      dive: { id: 5, dive_code: "103B", dive_number: null, height: "3m", dive_datetime: "2026-10-05T09:00:00Z", diver_name: "Alex" },
      comment: { id: 12, body: "Great entry!" },
    },
    {
      key: "dive_like:6:g3:0",
      kind: "dive_like",
      direction: "received",
      created_at: null,
      actor: { user_id: null, guest_id: 3, display_name: "Nemo" },
      dive: { id: 6, dive_code: "201C", dive_number: null, height: "5m", dive_datetime: "2026-10-04T09:00:00Z", diver_name: "Alex" },
      comment: null,
    },
  ],
  next_before: null,
};

function fetchJson(payload: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(payload),
  } as Response)
}

function renderAt(path: string) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/account" element={<Account />} />
          <Route path="/users/:userId" element={<MemberProfile />} />
          <Route path="/dives" element={<p>Library</p>} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe("Account activity section", () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists received activity with profile and clip links", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/users/me/activity")) return fetchJson(pageOne);
      return fetchJson({}, false, 404);
    });
    const user = userEvent.setup();
    renderAt("/account");
    await user.click(screen.getByRole("button", { name: "Activity" }));
    await waitFor(() => expect(screen.getByText("Bob Marlin")).toBeInTheDocument());
    const profileLink = screen.getByRole("link", { name: "Bob Marlin" });
    expect(profileLink).toHaveAttribute("href", "/users/9");
    const guestName = screen.getByText("Nemo");
    expect(guestName.closest("a")).toBeNull();
    const clipLinks = screen.getAllByRole("link", { name: /103B/ });
    expect(clipLinks[0]).toHaveAttribute("href", "/dives?clip=5&scope=all");
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/users/me/activity"), { credentials: "same-origin" });
  });

  it("switching to the Sent tab re-queries with the direction filter", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/users/me/activity")) return fetchJson({ items: [], next_before: null });
      return fetchJson({}, false, 404);
    });
    const user = userEvent.setup();
    renderAt("/account");
    await user.click(screen.getByRole("button", { name: "Activity" }));
    await waitFor(() => expect(screen.getByText(/No activity/)).toBeInTheDocument());
    await user.click(screen.getByRole("radio", { name: "Sent" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("direction=sent"), { credentials: "same-origin" }),
    );
  });
});

describe("MemberProfile", () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const profile = {
    user_id: 9,
    display_name: "Bob Marlin",
    role: "diver",
    is_admin: false,
    is_self: false,
    joined_at: "2025-01-15T00:00:00Z",
    divers: [{ diver_id: 3, display_name: "Bob" }],
    handle: "bob_marlin", bio: "Diving together", avatar_url: null,
  };

  it("renders the member identity and their visible activity timeline", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/users/9")) return fetchJson(profile);
      if (url.includes("/users/9/dives")) return fetchJson({ items: [], next_before: null });
      if (url.includes("/users/9/activity")) return fetchJson(pageOne);
      return fetchJson({}, false, 404);
    });
    renderAt("/users/9");
    await waitFor(() => expect(screen.getByRole("heading", { name: "Bob Marlin" })).toBeInTheDocument());
    expect(screen.getByText(/Diver:/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("tab", { name: "Activity" }));
    expect(await screen.findByText("Great entry!")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /103B/ })[0]).toHaveAttribute("href", "/dives?clip=5&scope=all");
  });

  it("opens on the dive grid and links tiles to the existing player", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(input => {
      const url = String(input);
      if (url.endsWith("/users/9")) return fetchJson(profile);
      if (url.includes("/users/9/dives")) return fetchJson({ items: [{ id: 42, dive_code: "105B", height: "3m", dive_datetime: "2026-10-08T12:00:00Z", visibility: "public", poster_url: "/poster.jpg" }], next_before: null });
      return fetchJson({ items: [], next_before: null });
    });
    renderAt("/users/9");
    const tile = await screen.findByRole("link", { name: "Watch 105B · 3m" });
    expect(tile).toHaveAttribute("href", "/dives?clip=42&scope=all");
    expect(screen.getByRole("tab", { name: "Dives" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("@bob_marlin")).toBeInTheDocument();
    expect(screen.getByText("Diving together")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit profile" })).not.toBeInTheDocument();
  });

  it("lets the owner edit their bio and keeps the form after a handle conflict", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, options) => {
      const url = String(input);
      if (url.endsWith("/users/9")) return fetchJson({ ...profile, is_self: true });
      if (url.endsWith("/me/profile")) return fetchJson({}, false, 409);
      return fetchJson({ items: [], next_before: null });
    });
    const user = userEvent.setup();
    renderAt("/users/9");
    await user.click(await screen.findByRole("button", { name: "Edit profile" }));
    await user.clear(screen.getByRole("textbox", { name: "Bio" }));
    await user.type(screen.getByRole("textbox", { name: "Bio" }), "New bio");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already taken");
    expect(screen.getByRole("textbox", { name: "Bio" })).toHaveValue("New bio");
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/users/me/profile", expect.objectContaining({ method: "PUT", body: JSON.stringify({ display_name: "Bob Marlin", handle: "bob_marlin", bio: "New bio" }) }));
  });

  it("shows a recoverable error instead of loading forever", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => fetchJson({}, false, 500)).mockImplementation(input => String(input).endsWith("/users/9") ? fetchJson(profile) : fetchJson({ items: [], next_before: null }));
    renderAt("/users/9");
    await screen.findByRole("alert");
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Bob Marlin" })).toBeInTheDocument();
  });

  it("shows the not-found state for an unknown member", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (String(input).endsWith("/users/9")) return fetchJson(profile);
      if (url.includes("/users/9/dives")) return fetchJson({ items: [], next_before: null });
      if (url.includes("/users/9/activity")) return fetchJson(pageOne);
      return fetchJson({ detail: "User not found" }, false, 404);
    });
    renderAt("/users/999");
    await waitFor(() => expect(screen.getByText("Member not found")).toBeInTheDocument());
  });

  it("recovers from a not-found profile when navigating to a valid one", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/users/9")) return fetchJson(profile);
      if (url.includes("/users/9/dives")) return fetchJson({ items: [], next_before: null });
      if (url.includes("/users/9/activity")) return fetchJson(pageOne);
      return fetchJson({ detail: "User not found" }, false, 404);
    });
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <MemoryRouter initialEntries={["/users/999"]}>
          <Routes>
            <Route path="/users/:userId" element={<MemberProfile />} />
          </Routes>
          <Link to="/users/9">goto valid profile</Link>
        </MemoryRouter>
      </I18nProvider>,
    );
    await waitFor(() => expect(screen.getByText("Member not found")).toBeInTheDocument());
    await user.click(screen.getByText("goto valid profile"));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Bob Marlin" })).toBeInTheDocument());
  });
});
