import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import AdminClubs from "./AdminClubs";
import {
  adminClubsApi as api,
  type ClubDetail,
} from "../services/adminClubsApi";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ i18n: { resolvedLanguage: "en" } }),
}));
const refresh = vi.fn();
vi.mock("../contexts/AuthContext", () => ({ useAuth: () => ({ refresh }) }));
vi.mock("../services/adminUsersApi", () => ({
  listUsers: vi.fn().mockResolvedValue({ users: [] }),
}));
vi.mock("../services/adminClubsApi", () => ({
  adminClubsApi: {
    list: vi.fn(),
      bulk: vi.fn(),
      candidates: vi.fn(),
    detail: vi.fn(),
    create: vi.fn(),
    createGroup: vi.fn(),
    addMember: vi.fn(),
    updateMember: vi.fn(),
    removeMember: vi.fn(),
    assign: vi.fn(),
    bundles: vi.fn(),
    preview: vi.fn(),
    apply: vi.fn(),
    activate: vi.fn(),
  },
}));

const club = {
  id: 1,
  slug: "kcpm",
  name: "KCPM Montreuil",
  short_name: "KCPM",
  timezone: "Europe/Paris",
  self_join_enabled: false,
};
let detail: ClubDetail;
beforeEach(() => {
  vi.clearAllMocks();
  detail = {
    club,
    groups: [
      { id: 1, club_id: 1, slug: "beginners", name: "Beginners" },
      { id: 2, club_id: 1, slug: "advanced", name: "Advanced" },
    ],
    members: [],
    next_cursor: null,
    calendar_enabled: false,
    readiness: {
      managers: 1,
      groups: 2,
      unassigned_members: 0,
      occurrences: 116,
      scheduled_checks: 0,
      last_check_at: null,
      worker_ready: false,
      problems: ["scheduled_checks_missing"],
    },
  };
  vi.mocked(api.list).mockResolvedValue({
    items: [club],
    next_cursor: null,
    calendar_enabled: false,
  });
  vi.mocked(api.detail).mockImplementation(async () => structuredClone(detail));
  vi.mocked(api.bundles).mockResolvedValue({
    items: [{ id: "season", label: "Season sources" }],
  });
});
async function openClub() {
  render(<AdminClubs />);
  fireEvent.click(
    await screen.findByRole("button", { name: /KCPM Montreuil/ }),
  );
  await screen.findByRole("button", { name: "Calendar opening" });
}

it("never offers opening without worker readiness, even after every manual check", async () => {
  await openClub();
  fireEvent.click(screen.getByRole("button", { name: "Calendar opening" }));
  for (const input of screen.getAllByRole("checkbox")) fireEvent.click(input);
  expect(screen.getByRole("button", { name: "Open calendar" })).toBeDisabled();
  expect(api.activate).not.toHaveBeenCalled();
  expect(screen.getByText(/all signed-in users/)).toBeInTheDocument();
});

it("requires explicit confirmation to open and refreshes authentication features", async () => {
  detail.readiness.problems = [];
  detail.readiness.scheduled_checks = 2;
  vi.spyOn(window, "confirm")
    .mockReturnValueOnce(false)
    .mockReturnValueOnce(true);
  await openClub();
  fireEvent.click(screen.getByRole("button", { name: "Calendar opening" }));
  const button = screen.getByRole("button", { name: "Open calendar" });
  expect(button).toBeDisabled();
  for (const input of screen.getAllByRole("checkbox")) fireEvent.click(input);
  fireEvent.click(button);
  expect(api.activate).not.toHaveBeenCalled();
  fireEvent.click(button);
  await waitFor(() =>
    expect(api.activate).toHaveBeenCalledWith(
      1,
      true,
      expect.objectContaining({ timer_verified: true, device_tested: true }),
    ),
  );
  expect(refresh).toHaveBeenCalled();
});

it("pauses an open calendar even when readiness has failed", async () => {
  detail.calendar_enabled = true;
  vi.spyOn(window, "confirm").mockReturnValue(true);
  await openClub();
  fireEvent.click(screen.getByRole("button", { name: "Calendar opening" }));
  fireEvent.click(screen.getByRole("button", { name: "Close calendar" }));
  await waitFor(() =>
    expect(api.activate).toHaveBeenCalledWith(1, false, expect.anything()),
  );
});

it("clears the reviewed import when its target mapping changes", async () => {
  vi.mocked(api.preview).mockResolvedValue({
    batch_id: "b".repeat(32),
    plan_hash: "a".repeat(64),
    summary: {
      training: {
        create: 1,
        update: 0,
        unchanged: 0,
        conflict: 0,
        missing_from_source: 0,
      },
      competitions: {},
    },
    plan: {
      training: [
        {
          group_key: "beginners",
          create: [
            {
              key: "kcpm:2026:beginners:2026-11-01",
              starts_at: "2026-11-01T17:00:00",
              ends_at: "2026-11-01T19:00:00",
              venue_name: "INSEP",
              provenance: {
                local_date: "2026-11-01",
                start_local: "18:00",
                end_local: "20:00",
              },
            },
          ],
          update: [],
          conflict: [],
          missing_from_source: [],
        },
      ],
    },
  });
  await openClub();
  fireEvent.click(
    screen.getByRole("button", { name: "Calendars and imports" }),
  );
  await screen.findByRole("option", { name: "Season sources" });
  fireEvent.change(screen.getByLabelText("Prepared sources"), {
    target: { value: "season" },
  });
  fireEvent.change(screen.getByLabelText("Season start"), {
    target: { value: "2026-09-01" },
  });
  fireEvent.change(screen.getByLabelText("Beginners source group"), {
    target: { value: "1" },
  });
  fireEvent.change(screen.getByLabelText("Advanced source group"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview" }));
  const table = await screen.findByRole("table");
  expect(within(table).getByText("INSEP")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Apply this import" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(
    screen.getByRole("button", { name: "Apply this import" }),
  ).toBeEnabled();
  fireEvent.change(screen.getByLabelText("Beginners source group"), {
    target: { value: "2" },
  });
  expect(
    screen.queryByRole("button", { name: "Apply this import" }),
  ).not.toBeInTheDocument();
  expect(api.apply).not.toHaveBeenCalled();
});

it("retains the import form after a failed preview and shows an actionable error", async () => {
  vi.mocked(api.preview).mockRejectedValue(
    new Error("Source changed: preview again"),
  );
  await openClub();
  fireEvent.click(
    screen.getByRole("button", { name: "Calendars and imports" }),
  );
  await screen.findByRole("option", { name: "Season sources" });
  fireEvent.change(screen.getByLabelText("Prepared sources"), {
    target: { value: "season" },
  });
  fireEvent.change(screen.getByLabelText("Season start"), {
    target: { value: "2026-09-01" },
  });
  fireEvent.change(screen.getByLabelText("Beginners source group"), {
    target: { value: "1" },
  });
  fireEvent.change(screen.getByLabelText("Advanced source group"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Source changed");
  expect(screen.getByLabelText("Season start")).toHaveValue("2026-09-01");
});

it("applies one group action to the explicit page selection", async () => {
  detail.members = [1, 2].map(id => ({ display_name: `Member ${id}`, email: `${id}@example.test`, membership: { id, user_id: id, role: 'member', can_publish: false, can_assign_groups: false }, assignment: null }))
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  await openClub()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select this page (2)' }))
  const toolbar = screen.getByRole('form', { name: 'Apply to selection' })
  fireEvent.change(within(toolbar).getByLabelText('Group'), { target: { value: '1' } })
  fireEvent.click(within(toolbar).getByRole('button', { name: 'Apply to selection (2)' }))
  await waitFor(() => expect(api.bulk).toHaveBeenCalledWith(1, expect.objectContaining({ action: 'group', ids: [1, 2], group_id: 1 })))
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('Beginners'))
  await waitFor(() => expect(screen.queryByRole('form', { name: 'Apply to selection' })).not.toBeInTheDocument())
})

it("keeps the selection after a refused batch so it can be corrected", async () => {
  detail.members = [{ display_name: 'Manager', email: 'manager@example.test', membership: { id: 9, user_id: 9, role: 'manager', can_publish: true, can_assign_groups: true }, assignment: null }]
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.mocked(api.bulk).mockRejectedValue(new Error('Appoint another manager first'))
  await openClub()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select this page (1)' }))
  const toolbar = screen.getByRole('form', { name: 'Apply to selection' })
  fireEvent.change(within(toolbar).getByLabelText('Action'), { target: { value: 'remove' } })
  fireEvent.click(within(toolbar).getByRole('button', { name: 'Apply to selection (1)' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Appoint another manager')
  expect(screen.getByRole('checkbox', { name: 'Select this page (1)' })).toBeChecked()
})

it('attaches accounts selected across multiple searches in one request', async () => {
  vi.mocked(api.candidates).mockImplementation(async (_id, q) => ({ items: [{ user_id: q === 'Morgan' ? 4 : 5, display_name: q, email: `${q}@example.test` }] }))
  vi.mocked(api.bulk).mockResolvedValue({ changed: 2 })
  await openClub()
  fireEvent.click(screen.getByText('Add an existing account'))
  fireEvent.change(screen.getByLabelText('Search name or email'), { target: { value: 'Morgan' } })
  fireEvent.click(await screen.findByRole('checkbox', { name: /Morgan Morgan@example.test/ }))
  fireEvent.change(screen.getByLabelText('Search name or email'), { target: { value: 'Robin' } })
  fireEvent.click(await screen.findByRole('checkbox', { name: /Robin Robin@example.test/ }))
  fireEvent.change(screen.getByLabelText('Role'), { target: { value: 'coach' } })
  fireEvent.click(screen.getByRole('button', { name: 'Attach accounts (2)' }))
  await waitFor(() => expect(api.bulk).toHaveBeenCalledWith(1, { action: 'add', ids: [4, 5], role: 'coach' }))
  expect(api.bulk).toHaveBeenCalledTimes(1)
})
