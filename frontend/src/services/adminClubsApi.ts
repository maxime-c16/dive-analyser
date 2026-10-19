import type { Group, Role } from "../calendar/api";

export interface Club {
  id: number;
  slug: string;
  name: string;
  short_name: string | null;
  timezone: string;
  self_join_enabled: boolean;
}
export interface Member {
  display_name: string;
  email: string;
  membership: {
    id: number;
    user_id: number;
    role: Role;
    can_publish: boolean;
    can_assign_groups: boolean;
  };
  assignment: { group_id: number; effective_from: string } | null;
}
export interface Readiness {
  managers: number;
  groups: number;
  unassigned_members: number;
  occurrences: number;
  scheduled_checks: number;
  last_check_at: string | null;
  worker_ready: boolean;
  problems: string[];
}
export interface ClubDetail {
  club: Club;
  groups: Group[];
  members: Member[];
  next_cursor: number | null;
  readiness: Readiness;
  calendar_enabled: boolean;
}
export interface ImportInput {
  bundle_id: string;
  season_start: string;
  groups: Record<string, number>;
  plan_hash?: string;
  batch_id?: string;
}
export interface ImportPreview {
  batch_id: string;
  plan_hash: string;
  summary: {
    training: {
      create: number;
      update: number;
      unchanged: number;
      conflict: number;
      missing_from_source: number;
    };
    competitions: Record<string, number>;
    resources?: Record<string, number>;
    link_sources?: Record<string, number>;
  };
  plan: {
    training: {
      group_key: string;
      key?: string;
      create: ImportSlot[];
      update: ImportSlot[];
      conflict: unknown[];
      missing_from_source: string[];
    }[];
  };
}
export interface ImportSlot {
  key: string;
  starts_at: string;
  ends_at: string;
  venue_name: string;
  provenance?: { local_date: string; start_local: string; end_local: string };
}

async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api/v1/admin/clubs${path}`, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* use status */
    }
    throw new Error(
      typeof detail === "string"
        ? detail
        : (detail as { message?: string })?.message ||
          `Request failed (${response.status})`,
    );
  }
  return response.json();
}
export const adminClubsApi = {
  candidates: (id: number, q: string) => request<{ items: { user_id: number; display_name: string; email: string }[] }>(`/${id}/candidates?q=${encodeURIComponent(q)}`),
  bulk: (
    id: number,
    body: {
      action: "add" | "role" | "group" | "remove";
      ids: number[];
      role?: Role;
      group_id?: number | null;
      effective_from?: string;
      can_publish?: boolean;
      can_assign_groups?: boolean;
    },
  ) => request<{ changed: number }>(`/${id}/members/bulk`, "POST", body),
  list: (after = 0) =>
    request<{
      items: Club[];
      next_cursor: number | null;
      calendar_enabled: boolean;
    }>(`?after=${after}`),
  create: (body: Omit<Club, "id">) => request<Club>("", "POST", body),
  detail: (id: number, after = 0) =>
    request<ClubDetail>(`/${id}?after=${after}`),
  addMember: (id: number, user_id: number, role: Role) =>
    request(`/${id}/memberships`, "POST", { user_id, role }),
  updateMember: (id: number, membership: number, body: object) =>
    request(`/${id}/memberships/${membership}`, "PATCH", body),
  removeMember: (id: number, membership: number) =>
    request(`/${id}/memberships/${membership}/end`, "POST"),
  createGroup: (id: number, slug: string, name: string) =>
    request(`/${id}/groups`, "POST", { slug, name }),
  assign: (
    id: number,
    user_id: number,
    group_id: number | null,
    effective_from: string,
  ) =>
    request(`/${id}/group-assignment`, "PUT", {
      user_id,
      group_id,
      effective_from,
    }),
  bundles: (id: number) =>
    request<{ items: { id: string; label: string }[] }>(`/${id}/imports`),
  preview: (id: number, body: ImportInput) =>
    request<ImportPreview>(`/${id}/imports/preview`, "POST", body),
  apply: (id: number, body: ImportInput) =>
    request(`/${id}/imports/apply`, "POST", body),
  activate: (id: number, enabled: boolean, checks: Record<string, boolean>) =>
    request(`/${id}/activation`, "PUT", { enabled, ...checks }),
};
