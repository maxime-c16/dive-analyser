import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { I18nProvider } from "../i18n/I18nProvider";
import Account, { initials } from "./Account";

const signOut = vi.fn();

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
    signOut,
  }),
}));

function renderAccount(initial = "/account") {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/account" element={<Account />} />
          <Route path="/login" element={<p>Login page</p>} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  // fetch is undefined in jsdom unless stubbed per-test
});

describe("initials", () => {
  it("uses first and last name parts", () => {
    expect(initials("Alex Moreau")).toBe("AM");
  });
  it("trims surrounding whitespace", () => {
    expect(initials("  Alex   Moreau  ")).toBe("AM");
  });
  it("handles single names", () => {
    expect(initials("Madonna")).toBe("MA");
  });
  it("falls back to the email local part", () => {
    expect(initials("", "alex.moreau@example.com")).toBe("AL");
  });
});

describe("Account (final V2)", () => {
  it("shows identity and switches sections via the sidebar", () => {
    renderAccount();
    expect(screen.getByText("Alex Moreau")).toBeInTheDocument();
    expect(screen.getByText("alex.moreau@example.com")).toBeInTheDocument();
    expect(screen.getByText("Diver")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Security" }));
    expect(screen.getByLabelText(/current password/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(screen.getByRole("switch", { name: "Email notifications" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Profile" }));
    expect(screen.getByText(/managed by your administrator/i)).toBeInTheDocument();
  });

  it("rejects mismatched passwords without calling the API", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderAccount();
    fireEvent.click(screen.getByRole("button", { name: "Security" }));
    fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "old-password-1" } });
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "new-password-123" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "different-12345" } });
    fireEvent.click(screen.getByRole("button", { name: /change password/i }));
    expect(screen.getByRole("alert")).toHaveTextContent("New passwords do not match");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rejects short passwords without calling the API", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderAccount();
    fireEvent.click(screen.getByRole("button", { name: "Security" }));
    fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "old-password-1" } });
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "short" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: /change password/i }));
    expect(screen.getByRole("alert")).toHaveTextContent("at least 10 characters");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("changes the password and clears the form on success", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    renderAccount();
    fireEvent.click(screen.getByRole("button", { name: "Security" }));
    fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "old-password-1" } });
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "brand-new-password" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "brand-new-password" } });
    fireEvent.click(screen.getByRole("button", { name: /^change password/i }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Password changed")
    );
    expect(screen.getByLabelText(/current password/i)).toHaveValue("");
  });

  it("reports a wrong current password on 401", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 401 }));
    renderAccount();
    fireEvent.click(screen.getByRole("button", { name: "Security" }));
    fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: "wrong-password" } });
    fireEvent.change(screen.getByLabelText(/^new password/i), { target: { value: "brand-new-password" } });
    fireEvent.change(screen.getByLabelText(/confirm new password/i), { target: { value: "brand-new-password" } });
    fireEvent.click(screen.getByRole("button", { name: /^change password/i }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Current password is incorrect")
    );
  });

  it("persists notification prefs on this device", () => {
    renderAccount();
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    const weekly = screen.getByRole("switch", { name: "Weekly digest" });
    expect(weekly).toHaveAttribute("aria-checked", "false");
    fireEvent.click(weekly);
    expect(weekly).toHaveAttribute("aria-checked", "true");
    expect(JSON.parse(localStorage.getItem("dive-analyser.prefs.v1") ?? "{}")).toMatchObject({
      weeklyDigest: true,
    });
  });

  it("loads server alert toggles and persists them via PUT", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push({ url, init });
      if (url === "/api/v1/notification-prefs" && init?.method === "PUT") {
        const body = JSON.parse(init.body as string);
        return new Response(JSON.stringify({ type: body.type, enabled: body.enabled }), { status: 200 });
      }
      return new Response(
        JSON.stringify({
          prefs: {
            new_video: true,
            video_ready: true,
            new_comment: true,
            comment_reply: true,
            milestone: true,
            sync_error: true,
            guest_activity: false,
          },
        }),
        { status: 200 },
      );
    });
    renderAccount();
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    const guest = await screen.findByRole("switch", { name: "Guest activity alerts" });
    expect(guest).toHaveAttribute("aria-checked", "false");
    fireEvent.click(guest);
    await waitFor(() => expect(guest).toHaveAttribute("aria-checked", "true"));
    const put = calls.find(call => call.init?.method === "PUT");
    expect(put?.url).toBe("/api/v1/notification-prefs");
    expect(JSON.parse(put?.init?.body as string)).toEqual({ type: "guest_activity", enabled: true });
  });

  it("falls back to the legacy milestone toggle when the API is down", async () => {
    localStorage.setItem("dive-analyser.prefs.v1", JSON.stringify({ milestoneAlerts: false }));
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("down"));
    renderAccount();
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    const milestones = await screen.findByRole("switch", { name: "Milestone alerts" });
    expect(milestones).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("alert")).toHaveTextContent(/last known values/i);
  });

  it("pushes legacy milestoneAlerts=false to the server once on first sync", async () => {
    localStorage.setItem("dive-analyser.prefs.v1", JSON.stringify({ milestoneAlerts: false }));
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push({ url, init });
      if (url === "/api/v1/notification-prefs" && init?.method === "PUT") {
        const body = JSON.parse(init.body as string);
        return new Response(JSON.stringify({ type: body.type, enabled: body.enabled }), { status: 200 });
      }
      return new Response(
        JSON.stringify({
          prefs: {
            new_video: true,
            video_ready: true,
            new_comment: true,
            comment_reply: true,
            milestone: true,
            sync_error: true,
            guest_activity: false,
          },
        }),
        { status: 200 },
      );
    });
    const first = renderAccount();
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    const milestones = await screen.findByRole("switch", { name: "Milestone alerts" });
    await waitFor(() => expect(milestones).toHaveAttribute("aria-checked", "false"));
    const puts = calls.filter(call => call.url === "/api/v1/notification-prefs" && call.init?.method === "PUT");
    expect(puts).toHaveLength(1);
    expect(JSON.parse(puts[0].init?.body as string)).toEqual({ type: "milestone", enabled: false });
    expect(JSON.parse(localStorage.getItem("dive-analyser.prefs.v1") ?? "{}")).toMatchObject({
      milestoneMigrated: true,
    });
    first.unmount();
    calls.length = 0;
    renderAccount();
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    await screen.findByRole("switch", { name: "Milestone alerts" });
    // Let the GET settle, then a tick for any spurious migration PUT.
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    await new Promise(resolve => setTimeout(resolve, 50));
    expect(
      calls.filter(call => call.url === "/api/v1/notification-prefs" && call.init?.method === "PUT"),
    ).toHaveLength(0);
  });

  it("warns that opt-in never publishes history and toggles the global switch", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ enabled: false }), { status: 200 }),
    );
    renderAccount();
    fireEvent.click(screen.getByRole("button", { name: "Fediverse" }));
    expect(
      await screen.findByText(/turning this on does not publish anything yet/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/poster \+ caption only/i)).toBeInTheDocument();
    expect(screen.getByText(/never paste a share link/i)).toBeInTheDocument();
    expect(screen.getByText(/works the same on phones, tablets, and desktop/i)).toBeInTheDocument();
    const toggle = screen.getByRole("switch", { name: "Fediverse sharing" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ enabled: true }), { status: 200 }),
    );
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  });

  it("signs out and returns to login", async () => {
    signOut.mockResolvedValue(undefined);
    renderAccount();
    fireEvent.click(screen.getAllByRole("button", { name: /sign out/i })[0]);
    await waitFor(() => expect(signOut).toHaveBeenCalled());
    expect(await screen.findByText("Login page")).toBeInTheDocument();
  });
});
