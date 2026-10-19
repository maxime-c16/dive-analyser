import { useEffect, useRef, useState } from "react";
import {
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  Plus,
  RefreshCw,
  Users,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../contexts/AuthContext";
import {
  adminClubsApi as api,
  type Club,
  type ClubDetail,
  type ImportPreview,
  type Member,
} from "../services/adminClubsApi";
type ClubCandidate = { user_id: number; display_name: string; email: string };
import type { Role } from "../calendar/api";
import { keepFocusOnPress } from "../calendar/useStrings";
import "./AdminClubs.css";

const copy = {
  fr: {
    title: "Clubs",
    intro:
      "Préparez les clubs et leurs calendriers, même avant leur ouverture aux membres.",
    create: "Créer un club",
    name: "Nom du club",
    slug: "Identifiant",
    short: "Nom court",
    timezone: "Fuseau horaire",
    selfJoin: "Permettre aux nouveaux inscrits de sélectionner ce club",
    selfJoinNote:
      "La sélection accorde immédiatement une affiliation déclarée, sans vérification.",
    save: "Enregistrer",
    cancel: "Annuler",
    loading: "Chargement…",
    refresh: "Actualiser",
    back: "Tous les clubs",
    empty:
      "Aucun club. Créez le premier club pour préparer ses membres et ses groupes.",
    selectPage: "Sélectionner cette page",
    selected: "sélectionnés",
    clearSelection: "Vider la sélection",
    bulkGroup: "Affecter un groupe",
    bulkRole: "Changer le rôle",
    bulkRemove: "Retirer du club",
    applySelection: "Appliquer à la sélection",
    bulkConfirm: "Appliquer cette action à ces membres ?",
    editMember: "Modifier",
    selectAccount: "Sélectionner les résultats",
    attachAccounts: "Rattacher les comptes",
    searchHint:
      "20 résultats maximum par recherche ; affinez le nom pour retrouver un autre compte.",
    members: "Membres",
    groups: "Groupes",
    imports: "Calendriers et imports",
    launch: "Ouverture du calendrier",
    memberNote:
      "Comptes de l’application uniquement. Un responsable gère le club ; un coach dispose des autorisations choisies ci-dessous.",
    addMember: "Rattacher un compte existant",
    search: "Rechercher un nom ou un email",
    choose: "Choisir un compte",
    role: "Rôle",
    member: "Membre",
    coach: "Coach",
    manager: "Responsable",
    add: "Ajouter",
    next: "Page suivante",
    previous: "Page précédente",
    none: "Non affecté",
    group: "Groupe",
    from: "À partir du",
    assign: "Affecter",
    publish: "Publier des événements",
    assignGrant: "Affecter les groupes",
    remove: "Retirer du club",
    removeConfirm: "Retirer ce membre du club ? Son historique sera conservé.",
    groupsNote:
      "Les membres voient les entraînements du groupe qui leur est affecté. Les coachs voient les deux groupes.",
    createGroup: "Créer un groupe",
    groupName: "Nom du groupe",
    noGroups:
      "Créez les groupes avant de répartir les membres et d’importer les séances.",
    bundles: "Sources préparées",
    noBundles:
      "Aucune source préparée sur le serveur. Les documents privés doivent être déposés une fois par un opérateur ; ils ne sont jamais publiés dans la bibliothèque.",
    importNote:
      "Prévisualisez les changements avant de les appliquer. Les compétitions importées restent en brouillon. Les séances sont publiées dans leur groupe et seront visibles à l’ouverture du calendrier.",
    season: "Début de saison",
    beginners: "Groupe de la source débutants",
    advanced: "Groupe de la source confirmés",
    preview: "Prévisualiser",
    apply: "Appliquer cet import",
    drafts: "Compétitions en brouillon",
    resources: "Nouvelles ressources",
    sourceLinks: "Nouvelles références de sources",
    alertProblem:
      "Le traitement des alertes nécessite une vérification sur le serveur.",
    created: "À créer",
    updated: "À modifier",
    unchanged: "Inchangées",
    conflicts: "Conflits",
    missing: "Absentes de la source",
    review: "Séances à créer ou modifier",
    date: "Date et heure",
    venue: "Lieu",
    action: "Action",
    conflictNote:
      "Les conflits et les séances absentes ne sont pas écrasés ni annulés automatiquement.",
    confirmImport:
      "J’ai vérifié les dates, les horaires, les lieux et les groupes de cette prévisualisation.",
    noChanges: "Aucune séance à créer ou modifier.",
    applied:
      "Import appliqué. Prévisualisez à nouveau pour vérifier le résultat.",
    saved: "Modifications enregistrées.",
    off: "Calendrier fermé",
    on: "Calendrier ouvert",
    global:
      "Ce réglage ouvre ou ferme l’onglet Calendrier pour tous les utilisateurs connectés. Les droits des clubs et des groupes continuent de limiter les événements visibles.",
    preparation: "Préparation du pilote",
    managers: "Responsable nommé",
    readyGroups: "Groupes créés",
    assigned: "Membres affectés",
    events: "Séances publiées",
    worker: "Deux passages récents du traitement programmé",
    operator:
      "L’installation du traitement programmé reste une opération serveur. Le compteur ci-dessous constate ses passages ; il ne prouve pas à lui seul que le timer est installé.",
    sources_reviewed: "J’ai vérifié les sources et les événements du pilote.",
    roles_reviewed:
      "J’ai vérifié les responsables, coachs et groupes des membres.",
    device_tested:
      "J’ai testé le parcours sur iPhone, VoiceOver et l’export vers une application calendrier.",
    retention_reviewed:
      "Le stockage privé, la sauvegarde et la conservation des sources sont validés.",
    timer_verified:
      "L’installation du timer serveur et deux passages programmés sont vérifiés.",
    enable: "Ouvrir le calendrier",
    pause: "Fermer le calendrier",
    enableConfirm:
      "Ouvrir le calendrier à tous les utilisateurs connectés ? Les notifications pourront être traitées selon leurs préférences.",
    pauseConfirm:
      "Fermer le calendrier et suspendre les prochains traitements ? Les données seront conservées. Un envoi déjà en cours peut se terminer.",
    unavailable:
      "Impossible de charger les clubs. Vérifiez votre connexion et l’installation de la migration d’administration.",
    noResults: "Aucun compte trouvé.",
  },
  en: {
    title: "Clubs",
    intro: "Prepare clubs and their calendars before opening them to members.",
    create: "Create club",
    name: "Club name",
    slug: "Identifier",
    short: "Short name",
    timezone: "Time zone",
    selfJoin: "Let new accounts select this club",
    selfJoinNote:
      "Selecting the club immediately grants a self-declared membership, without verification.",
    save: "Save changes",
    cancel: "Cancel",
    loading: "Loading…",
    refresh: "Refresh",
    back: "All clubs",
    empty: "No clubs yet. Create a club to prepare its members and groups.",
    selectPage: "Select this page",
    selected: "selected",
    clearSelection: "Clear selection",
    bulkGroup: "Assign a group",
    bulkRole: "Change role",
    bulkRemove: "Remove from club",
    applySelection: "Apply to selection",
    bulkConfirm: "Apply this action to these members?",
    editMember: "Edit",
    selectAccount: "Select search results",
    attachAccounts: "Attach accounts",
    searchHint:
      "Up to 20 results per search; narrow the name to find another account.",
    members: "Members",
    groups: "Groups",
    imports: "Calendars and imports",
    launch: "Calendar opening",
    memberNote:
      "App accounts only. Managers administer the club; coaches have the permissions selected below.",
    addMember: "Add an existing account",
    search: "Search name or email",
    choose: "Choose an account",
    role: "Role",
    member: "Member",
    coach: "Coach",
    manager: "Manager",
    add: "Add",
    next: "Next page",
    previous: "Previous page",
    none: "Unassigned",
    group: "Group",
    from: "Effective from",
    assign: "Assign",
    publish: "Publish events",
    assignGrant: "Assign groups",
    remove: "Remove from club",
    removeConfirm:
      "Remove this member from the club? Their history will be kept.",
    groupsNote:
      "Members see training for their assigned group. Coaches see both groups.",
    createGroup: "Create group",
    groupName: "Group name",
    noGroups: "Create groups before assigning members and importing sessions.",
    bundles: "Prepared sources",
    noBundles:
      "No prepared sources on the server. An operator must stage private documents once; they are never published in the video library.",
    importNote:
      "Preview changes before applying them. Imported competitions stay as drafts. Training sessions are published to their groups and become visible when the calendar opens.",
    season: "Season start",
    beginners: "Beginners source group",
    advanced: "Advanced source group",
    preview: "Preview",
    apply: "Apply this import",
    drafts: "Draft competitions",
    resources: "New resources",
    sourceLinks: "New source references",
    alertProblem: "The alerts worker needs a server check.",
    created: "To create",
    updated: "To update",
    unchanged: "Unchanged",
    conflicts: "Conflicts",
    missing: "Missing from source",
    review: "Sessions to create or update",
    date: "Date and time",
    venue: "Venue",
    action: "Action",
    conflictNote:
      "Conflicts and missing sessions are never automatically overwritten or cancelled.",
    confirmImport:
      "I have checked the dates, times, venues and groups in this preview.",
    noChanges: "No sessions to create or update.",
    applied: "Import applied. Preview again to verify the result.",
    saved: "Changes saved.",
    off: "Calendar closed",
    on: "Calendar open",
    global:
      "This setting opens or closes the Calendar tab for all signed-in users. Club and group permissions still restrict which events they can see.",
    preparation: "Pilot preparation",
    managers: "Manager appointed",
    readyGroups: "Groups created",
    assigned: "Members assigned",
    events: "Published sessions",
    worker: "Two recent scheduled worker observations",
    operator:
      "Installing the scheduled worker remains a server operation. The counter below observes its runs; it does not by itself prove the timer is installed.",
    sources_reviewed: "I have reviewed the pilot sources and events.",
    roles_reviewed: "I have reviewed managers, coaches and member groups.",
    device_tested:
      "I have tested iPhone, VoiceOver and export to a calendar app.",
    retention_reviewed:
      "Private storage, backups and source retention are approved.",
    timer_verified:
      "The server timer installation and two scheduled runs are verified.",
    enable: "Open calendar",
    pause: "Close calendar",
    enableConfirm:
      "Open the calendar to all signed-in users? Notifications may be processed according to their preferences.",
    pauseConfirm:
      "Close the calendar and pause subsequent processing? Data will be kept. A send already in progress may finish.",
    unavailable:
      "Unable to load clubs. Check your connection and the club administration migration.",
    noResults: "No accounts found.",
  },
};
type Copy = typeof copy.en;
type Run = (fn: () => Promise<unknown>, message?: string) => Promise<void>;
const checksInitial = {
  sources_reviewed: false,
  roles_reviewed: false,
  device_tested: false,
  retention_reviewed: false,
  timer_verified: false,
};
const slugify = (value: string) =>
  value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64);

export default function AdminClubs() {
  const { i18n } = useTranslation();
  const t = copy[i18n.resolvedLanguage?.startsWith("fr") ? "fr" : "en"];
  const { refresh: refreshAuth } = useAuth();
  const [clubs, setClubs] = useState<Club[]>([]);
  const [clubCursor, setClubCursor] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<ClubDetail | null>(null);
  const [cursors, setCursors] = useState([0]);
  const [section, setSection] = useState<
    "members" | "groups" | "imports" | "launch"
  >("members");
  const [creating, setCreating] = useState(false);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const lock = useRef(false);
  const cursor = cursors[cursors.length - 1];
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    const load =
      selected === null
        ? api.list().then((data) => {
            if (live) {
              setClubs(data.items);
              setClubCursor(data.next_cursor);
            }
          })
        : api.detail(selected, cursor).then((data) => {
            if (live) setDetail(data);
          });
    load
      .catch(() => {
        if (live) setError(t.unavailable);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [selected, cursor, revision, t.unavailable]);
  const run: Run = async (fn, message = t.saved) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(message);
      if (message) setRevision((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : t.unavailable);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  return (
    <section className="admin-clubs" aria-label={t.title}>
      <div className="clubs-heading">
        <div>
          {selected !== null && (
            <button
              className="clubs-back"
              disabled={busy}
              onClick={() => {
                setSelected(null);
                setDetail(null);
                setCursors([0]);
                setNotice(null);
              }}
            >
              <ChevronLeft size={16} />
              {t.back}
            </button>
          )}
          <h2>{detail?.club.name || t.title}</h2>
          <p>{t.intro}</p>
        </div>
        <button
          disabled={busy || loading}
          onClick={() => setRevision((v) => v + 1)}
        >
          <RefreshCw size={16} />
          {t.refresh}
        </button>
      </div>
      {error && (
        <p role="alert" className="clubs-error">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="clubs-notice">
          {notice}
        </p>
      )}
      {loading && <p role="status">{t.loading}</p>}
      <fieldset disabled={busy || loading} className="clubs-fieldset">
        {selected === null && !loading && (
          <>
            {!creating ? (
              <button onClick={() => setCreating(true)}>
                <Plus size={16} />
                {t.create}
              </button>
            ) : (
              <ClubForm
                t={t}
                cancel={() => setCreating(false)}
                create={(body) =>
                  run(async () => {
                    const club = await api.create(body);
                    setCreating(false);
                    setSelected(club.id);
                  })
                }
              />
            )}
            {!clubs.length && !creating && (
              <p className="clubs-empty">{t.empty}</p>
            )}
            <div className="clubs-list">
              {clubs.map((c) => (
                <button
                  key={c.id}
                  onClick={() => {
                    setDetail(null);
                    setSelected(c.id);
                    setSection("members");
                    setCursors([0]);
                  }}
                >
                  <Users size={20} />
                  <span>
                    <strong>{c.name}</strong>
                    <small>{c.timezone}</small>
                  </span>
                  <span aria-hidden>›</span>
                </button>
              ))}
            </div>
            {clubCursor !== null && (
              <button
                onClick={() =>
                  void run(async () => {
                    const data = await api.list(clubCursor);
                    setClubs((old) => [...old, ...data.items]);
                    setClubCursor(data.next_cursor);
                  }, "")
                }
              >
                {t.next}
              </button>
            )}
          </>
        )}
        {detail && (
          <>
            <nav aria-label={detail.club.name} className="clubs-sections">
              {(["members", "groups", "imports", "launch"] as const).map(
                (key) => (
                  <button
                    key={key}
                    aria-current={section === key ? "page" : undefined}
                    onClick={() => setSection(key)}
                  >
                    {t[key]}
                  </button>
                ),
              )}
            </nav>
            {section === "members" && (
              <>
                <p>{t.memberNote}</p>
                <AddMember t={t} clubId={detail.club.id} run={run} />
                <MemberList
                  key={detail.club.id}
                  t={t}
                  detail={detail}
                  revision={revision}
                  run={run}
                />
                <div className="clubs-actions">
                  <button
                    disabled={cursors.length === 1}
                    onClick={() => setCursors((old) => old.slice(0, -1))}
                  >
                    {t.previous}
                  </button>
                  <button
                    disabled={detail.next_cursor === null}
                    onClick={() =>
                      setCursors((old) => [...old, detail.next_cursor!])
                    }
                  >
                    {t.next}
                  </button>
                </div>
              </>
            )}
            {section === "groups" && (
              <>
                <p>{t.groupsNote}</p>
                {detail.groups.length ? (
                  <ul>
                    {detail.groups.map((g) => (
                      <li key={g.id}>{g.name}</li>
                    ))}
                  </ul>
                ) : (
                  <p>{t.noGroups}</p>
                )}
                <GroupForm
                  t={t}
                  create={(slug, name) =>
                    run(() => api.createGroup(detail.club.id, slug, name))
                  }
                />
              </>
            )}
            {section === "imports" && (
              <ImportPanel
                key={detail.club.id}
                t={t}
                detail={detail}
                run={run}
              />
            )}
            {section === "launch" && (
              <LaunchPanel
                t={t}
                detail={detail}
                run={run}
                refreshAuth={refreshAuth}
              />
            )}
          </>
        )}
      </fieldset>
    </section>
  );
}

function ClubForm({
  t,
  cancel,
  create,
}: {
  t: Copy;
  cancel: () => void;
  create: (body: Omit<Club, "id">) => Promise<void>;
}) {
  const [name, setName] = useState(""),
    [slug, setSlug] = useState(""),
    [short, setShort] = useState(""),
    [timezone, setTimezone] = useState("Europe/Paris"),
    [join, setJoin] = useState(false);
  return (
    <form
      className="clubs-panel"
      onSubmit={(e) => {
        e.preventDefault();
        void create({
          name: name.trim(),
          slug,
          short_name: short || null,
          timezone,
          self_join_enabled: join,
        });
      }}
    >
      <h3>{t.create}</h3>
      <div className="clubs-form-grid">
        <label>
          {t.name}
          <input
            required
            maxLength={160}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setSlug(slugify(e.target.value));
            }}
          />
        </label>
        <label>
          {t.slug}
          <input
            required
            minLength={2}
            maxLength={64}
            pattern="[a-z0-9][a-z0-9-]+"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
        </label>
        <label>
          {t.short}
          <input
            maxLength={40}
            value={short}
            onChange={(e) => setShort(e.target.value)}
          />
        </label>
        <label>
          {t.timezone}
          <input
            required
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
          />
        </label>
      </div>
      <label className="clubs-check">
        <input
          type="checkbox"
          checked={join}
          onChange={(e) => setJoin(e.target.checked)}
        />
        {t.selfJoin}
      </label>
      <p>{t.selfJoinNote}</p>
      <div className="clubs-actions">
        <button type="submit" {...keepFocusOnPress}>
          {t.create}
        </button>
        <button type="button" onClick={cancel}>
          {t.cancel}
        </button>
      </div>
    </form>
  );
}

function GroupForm({
  t,
  create,
}: {
  t: Copy;
  create: (slug: string, name: string) => Promise<void>;
}) {
  const [name, setName] = useState(""),
    [slug, setSlug] = useState("");
  return (
    <form
      className="clubs-panel"
      onSubmit={(e) => {
        e.preventDefault();
        void create(slug, name.trim());
      }}
    >
      <h3>{t.createGroup}</h3>
      <div className="clubs-form-grid">
        <label>
          {t.groupName}
          <input
            required
            maxLength={120}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setSlug(slugify(e.target.value));
            }}
          />
        </label>
        <label>
          {t.slug}
          <input
            required
            minLength={2}
            pattern="[a-z0-9][a-z0-9-]+"
            maxLength={64}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
        </label>
      </div>
      <button type="submit" {...keepFocusOnPress}>
        {t.createGroup}
      </button>
    </form>
  );
}

function AddMember({ t, clubId, run }: { t: Copy; clubId: number; run: Run }) {
  const [query, setQuery] = useState(""),
    [users, setUsers] = useState<ClubCandidate[]>([]),
    [chosen, setChosen] = useState<Map<number, ClubCandidate>>(new Map()),
    [role, setRole] = useState<Role>("member"),
    [error, setError] = useState(false);
  useEffect(() => {
    let live = true;
    setUsers([]);
    setError(false);
    if (!query.trim()) return;
    const timer = window.setTimeout(() => {
      api.candidates(clubId, query)
        .then((data) => {
          if (live) setUsers(data.items);
        })
        .catch(() => {
          if (live) setError(true);
        });
    }, 250);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [query, clubId]);
  const toggle = (user: ClubCandidate, checked: boolean) =>
    setChosen((old) => {
      const next = new Map(old);
      if (checked && next.size < 100) next.set(user.user_id, user);
      else if (!checked) next.delete(user.user_id);
      return next;
    });
  return (
    <details className="clubs-panel clubs-add-member">
      <summary>{t.addMember}</summary>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (chosen.size)
            void run(async () => {
              await api.bulk(clubId, {
                action: "add",
                ids: [...chosen.keys()],
                role,
              });
              setChosen(new Map());
            });
        }}
      >
        <div className="clubs-form-grid">
          <label>
            {t.search}
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <RoleField t={t} value={role} change={setRole} />
        </div>
        <p>{t.searchHint}</p>
        {users.length > 0 && (
          <>
            <label className="clubs-check">
              <input
                type="checkbox"
                checked={users.every((u) => chosen.has(u.user_id))}
                onChange={(e) => {
                  const checked = e.target.checked;
                  setChosen((old) => {
                    const next = new Map(old);
                    users.forEach((u) => {
                      if (checked && next.size < 100) next.set(u.user_id, u);
                      else if (!checked) next.delete(u.user_id);
                    });
                    return next;
                  });
                }}
              />
              {t.selectAccount}
            </label>
            <div className="clubs-account-results">
              {users.map((u) => (
                <label className="clubs-check" key={u.user_id}>
                  <input
                    type="checkbox"
                    checked={chosen.has(u.user_id)}
                    disabled={chosen.size >= 100 && !chosen.has(u.user_id)}
                    onChange={(e) => toggle(u, e.target.checked)}
                  />
                  <span>
                    {u.display_name}
                    <small>{u.email}</small>
                  </span>
                </label>
              ))}
            </div>
          </>
        )}
        {error && <p role="alert">{t.unavailable}</p>}
        <p aria-live="polite">
          {chosen.size} {t.selected}
          {chosen.size > 0 && (
            <> — {[...chosen.values()].map((u) => u.display_name).join(", ")}</>
          )}
        </p>
        <div className="clubs-actions">
          <button type="submit" disabled={!chosen.size} {...keepFocusOnPress}>
            {t.attachAccounts} ({chosen.size})
          </button>
          {chosen.size > 0 && (
            <button type="button" onClick={() => setChosen(new Map())}>
              {t.clearSelection}
            </button>
          )}
        </div>
      </form>
    </details>
  );
}

function MemberList({
  t,
  detail,
  revision,
  run,
}: {
  t: Copy;
  detail: ClubDetail;
  revision: number;
  run: Run;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [action, setAction] = useState<"group" | "role" | "remove">("group");
  const [role, setRole] = useState<Role>("member"),
    [group, setGroup] = useState(""),
    [publish, setPublish] = useState(false),
    [assignGrant, setAssignGrant] = useState(false);
  const [from, setFrom] = useState(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: detail.club.timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date()),
  );
  const firstId = detail.members[0]?.membership.id;
  useEffect(() => {
    setSelected(new Set());
  }, [firstId]);
  const pageIds = detail.members.map((m) => m.membership.id);
  const ids = pageIds.filter((id) => selected.has(id));
  return (
    <div className="clubs-members">
      <div className="clubs-selection">
        <label className="clubs-check">
          <input
            type="checkbox"
            checked={pageIds.length > 0 && ids.length === pageIds.length}
            disabled={!pageIds.length}
            onChange={(e) =>
              setSelected(e.target.checked ? new Set(pageIds) : new Set())
            }
          />
          {t.selectPage} ({pageIds.length})
        </label>
        <span aria-live="polite">
          {ids.length} {t.selected}
        </span>
        {ids.length > 0 && (
          <button onClick={() => setSelected(new Set())}>
            {t.clearSelection}
          </button>
        )}
      </div>
      {ids.length > 0 && (
        <form
          className="clubs-bulk-bar"
          aria-label={t.applySelection}
          onSubmit={(e) => {
            e.preventDefault();
            if (
              window.confirm(
                `${t.bulkConfirm} (${ids.length})\n${action === "group" ? t.bulkGroup + ": " + (detail.groups.find((g) => g.id === Number(group))?.name || t.none) + " — " + from : action === "role" ? t.bulkRole + ": " + t[role] : t.bulkRemove}`,
              )
            )
              void run(async () => {
                await api.bulk(detail.club.id, {
                  action,
                  ids,
                  ...(action === "group"
                    ? {
                        group_id: group === "none" ? null : Number(group),
                        effective_from: from,
                      }
                    : action === "role"
                      ? {
                          role,
                          can_publish: publish,
                          can_assign_groups: assignGrant,
                        }
                      : {}),
                });
                setSelected(new Set());
              });
          }}
        >
          <label>
            {t.action}
            <select
              value={action}
              onChange={(e) => setAction(e.target.value as typeof action)}
            >
              <option value="group">{t.bulkGroup}</option>
              <option value="role">{t.bulkRole}</option>
              <option value="remove">{t.bulkRemove}</option>
            </select>
          </label>
          {action === "group" && (
            <>
              <label>
                {t.group}
                <select
                  required
                  value={group}
                  onChange={(e) => setGroup(e.target.value)}
                >
                  <option value="">—</option>
                  <option value="none">{t.none}</option>
                  {detail.groups.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t.from}
                <input
                  required
                  type="date"
                  value={from}
                  onChange={(e) => setFrom(e.target.value)}
                />
              </label>
            </>
          )}
          {action === "role" && (
            <>
              <RoleField t={t} value={role} change={setRole} />
              {role === "coach" && (
                <>
                  <label className="clubs-check">
                    <input
                      type="checkbox"
                      checked={publish}
                      onChange={(e) => setPublish(e.target.checked)}
                    />
                    {t.publish}
                  </label>
                  <label className="clubs-check">
                    <input
                      type="checkbox"
                      checked={assignGrant}
                      onChange={(e) => setAssignGrant(e.target.checked)}
                    />
                    {t.assignGrant}
                  </label>
                </>
              )}
            </>
          )}
          <button
            type="submit"
            {...keepFocusOnPress}
            className={action === "remove" ? "clubs-danger" : "clubs-primary"}
          >
            {t.applySelection} ({ids.length})
          </button>
        </form>
      )}
      {detail.members.map((m) => (
        <article key={m.membership.id} className="clubs-roster-row">
          <label className="clubs-check">
            <input
              type="checkbox"
              aria-label={`${t.choose}: ${m.display_name}`}
              checked={selected.has(m.membership.id)}
              onChange={(e) =>
                setSelected((old) => {
                  const next = new Set(old);
                  if (e.target.checked) next.add(m.membership.id);
                  else next.delete(m.membership.id);
                  return next;
                })
              }
            />
            <span>
              <strong>{m.display_name}</strong>
              <small>{m.email}</small>
            </span>
          </label>
          <span className="clubs-role-badge">{t[m.membership.role]}</span>
          <span className="clubs-roster-group">
            {detail.groups.find((g) => g.id === m.assignment?.group_id)?.name ||
              t.none}
          </span>
          <details>
            <summary>{t.editMember}</summary>
            <MemberRow
              key={`${m.membership.id}-${revision}`}
              t={t}
              member={m}
              detail={detail}
              run={run}
            />
          </details>
        </article>
      ))}
    </div>
  );
}

function RoleField({
  t,
  value,
  change,
}: {
  t: Copy;
  value: Role;
  change: (role: Role) => void;
}) {
  return (
    <label>
      {t.role}
      <select value={value} onChange={(e) => change(e.target.value as Role)}>
        {(["member", "coach", "manager"] as const).map((r) => (
          <option key={r} value={r}>
            {t[r]}
          </option>
        ))}
      </select>
    </label>
  );
}

function MemberRow({
  t,
  member: m,
  detail,
  run,
}: {
  t: Copy;
  member: Member;
  detail: ClubDetail;
  run: Run;
}) {
  const [role, setRole] = useState(m.membership.role),
    [publish, setPublish] = useState(m.membership.can_publish),
    [assignGrant, setAssignGrant] = useState(m.membership.can_assign_groups);
  const [group, setGroup] = useState(
      m.assignment ? String(m.assignment.group_id) : "",
    ),
    [from, setFrom] = useState(
      new Intl.DateTimeFormat("en-CA", {
        timeZone: detail.club.timezone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(new Date()),
    );
  return (
    <article className="clubs-member">
      <div>
        <h3>{m.display_name}</h3>
        <p>{m.email}</p>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(() =>
            api.updateMember(detail.club.id, m.membership.id, {
              role,
              can_publish: publish,
              can_assign_groups: assignGrant,
            }),
          );
        }}
      >
        <RoleField t={t} value={role} change={setRole} />
        {role === "coach" && (
          <>
            <label className="clubs-check">
              <input
                type="checkbox"
                checked={publish}
                onChange={(e) => setPublish(e.target.checked)}
              />
              {t.publish}
            </label>
            <label className="clubs-check">
              <input
                type="checkbox"
                checked={assignGrant}
                onChange={(e) => setAssignGrant(e.target.checked)}
              />
              {t.assignGrant}
            </label>
          </>
        )}
        <button type="submit" {...keepFocusOnPress}>
          {t.save}
        </button>
      </form>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run(() =>
            api.assign(
              detail.club.id,
              m.membership.user_id,
              group ? Number(group) : null,
              from,
            ),
          );
        }}
      >
        <label>
          {t.group}
          <select value={group} onChange={(e) => setGroup(e.target.value)}>
            <option value="">{t.none}</option>
            {detail.groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t.from}
          <input
            type="date"
            required
            value={from}
            onChange={(e) => setFrom(e.target.value)}
          />
        </label>
        <button type="submit" {...keepFocusOnPress}>
          {t.assign}
        </button>
      </form>
      <button
        className="clubs-danger"
        onClick={() => {
          if (window.confirm(t.removeConfirm))
            void run(() => api.removeMember(detail.club.id, m.membership.id));
        }}
      >
        {t.remove}
      </button>
    </article>
  );
}

function ImportPanel({
  t,
  detail,
  run,
}: {
  t: Copy;
  detail: ClubDetail;
  run: Run;
}) {
  const [bundles, setBundles] = useState<{ id: string; label: string }[]>([]),
    [loadError, setLoadError] = useState(false);
  const [bundle, setBundle] = useState(""),
    [season, setSeason] = useState(""),
    [beginner, setBeginner] = useState(""),
    [advanced, setAdvanced] = useState("");
  const [preview, setPreview] = useState<ImportPreview | null>(null),
    [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    let live = true;
    api
      .bundles(detail.club.id)
      .then((data) => {
        if (live) setBundles(data.items);
      })
      .catch(() => {
        if (live) setLoadError(true);
      });
    return () => {
      live = false;
    };
  }, [detail.club.id]);
  const input = {
    bundle_id: bundle,
    season_start: season,
    groups: { beginners: Number(beginner), advanced: Number(advanced) },
  };
  const change = (fn: () => void) => {
    fn();
    setPreview(null);
    setConfirmed(false);
  };
  return (
    <div className="clubs-import">
      <p>{t.importNote}</p>
      {loadError ? (
        <p role="alert">{t.unavailable}</p>
      ) : !bundles.length ? (
        <p className="clubs-empty">{t.noBundles}</p>
      ) : (
        <form
          className="clubs-panel"
          onSubmit={(e) => {
            e.preventDefault();
            setPreview(null);
            setConfirmed(false);
            void run(async () => {
              setPreview(await api.preview(detail.club.id, input));
            }, "");
          }}
        >
          <div className="clubs-form-grid">
            <label>
              {t.bundles}
              <select
                required
                value={bundle}
                onChange={(e) => change(() => setBundle(e.target.value))}
              >
                <option value="">—</option>
                {bundles.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.season}
              <input
                type="date"
                required
                value={season}
                onChange={(e) => change(() => setSeason(e.target.value))}
              />
            </label>
            {(
              [
                ["beginners", beginner, setBeginner],
                ["advanced", advanced, setAdvanced],
              ] as const
            ).map(([key, value, setter]) => (
              <label key={key}>
                {t[key]}
                <select
                  required
                  value={value}
                  onChange={(e) => change(() => setter(e.target.value))}
                >
                  <option value="">—</option>
                  {detail.groups.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <button type="submit" {...keepFocusOnPress}>
            {t.preview}
          </button>
        </form>
      )}
      {preview && (
        <section className="clubs-panel">
          <h3>{t.review}</h3>
          <dl className="clubs-counts">
            {(
              [
                "create",
                "update",
                "unchanged",
                "conflict",
                "missing_from_source",
              ] as const
            ).map((key, i) => (
              <div key={key}>
                <dt>
                  {
                    [t.created, t.updated, t.unchanged, t.conflicts, t.missing][
                      i
                    ]
                  }
                </dt>
                <dd>{preview.summary.training[key]}</dd>
              </div>
            ))}
          </dl>
          <p>
            {t.drafts}: {preview.summary.competitions.draft || 0} ·{" "}
            {t.resources}: {preview.summary.resources?.create || 0} ·{" "}
            {t.sourceLinks}: {preview.summary.link_sources?.create || 0}
          </p>
          <p>{t.conflictNote}</p>
          <div className="clubs-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t.date}</th>
                  <th>{t.group}</th>
                  <th>{t.venue}</th>
                  <th>{t.action}</th>
                </tr>
              </thead>
              <tbody>
                {preview.plan.training.flatMap((g) =>
                  (["create", "update"] as const).flatMap((action) =>
                    g[action].map((slot) => (
                      <tr key={slot.key}>
                        <td>
                          {slot.provenance
                            ? `${slot.provenance.local_date} ${slot.provenance.start_local}–${slot.provenance.end_local}`
                            : new Date(`${slot.starts_at}Z`).toLocaleString(
                                undefined,
                                { timeZone: detail.club.timezone },
                              )}
                        </td>
                        <td>{g.group_key || slot.key.split(":")[2]}</td>
                        <td>{slot.venue_name}</td>
                        <td>{action === "create" ? t.created : t.updated}</td>
                      </tr>
                    )),
                  ),
                )}
              </tbody>
            </table>
          </div>
          <label className="clubs-check">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            {t.confirmImport}
          </label>
          <button
            disabled={!confirmed}
            onClick={() =>
              void run(async () => {
                try {
                  await api.apply(detail.club.id, {
                    ...input,
                    plan_hash: preview.plan_hash,
                    batch_id: preview.batch_id,
                  });
                } finally {
                  setPreview(null);
                  setConfirmed(false);
                }
              }, t.applied)
            }
          >
            {t.apply}
          </button>
        </section>
      )}
    </div>
  );
}

function LaunchPanel({
  t,
  detail,
  run,
  refreshAuth,
}: {
  t: Copy;
  detail: ClubDetail;
  run: Run;
  refreshAuth: () => Promise<void>;
}) {
  const [checks, setChecks] = useState(checksInitial);
  const r = detail.readiness;
  const rows = [
    [t.managers, r.managers > 0, r.managers],
    [t.readyGroups, r.groups > 0, r.groups],
    [
      t.assigned,
      r.unassigned_members === 0,
      r.unassigned_members === 0 ? "✓" : `${r.unassigned_members} ${t.none}`,
    ],
    [t.events, r.occurrences > 0, r.occurrences],
    [
      t.worker,
      !r.problems.includes("scheduled_checks_missing"),
      r.scheduled_checks,
    ],
  ] as const;
  return (
    <div className="clubs-panel">
      <div className="clubs-heading">
        <h3>
          <CalendarDays size={18} />
          {detail.calendar_enabled ? t.on : t.off}
        </h3>
        {detail.calendar_enabled && (
          <CheckCircle2 size={20} className="text-app-accent" />
        )}
      </div>
      <p>{t.global}</p>
      <h4>{t.preparation}</h4>
      <ul className="clubs-readiness">
        {rows.map(([label, okay, value]) => (
          <li key={label}>
            <span className={okay ? "text-app-accent" : ""}>
              {okay ? "✓" : "○"}
            </span>
            <span>{label}</span>
            <strong>{value}</strong>
          </li>
        ))}
      </ul>
      <p>{t.operator}</p>
      {r.problems.some(
        (p) =>
          ![
            "manager_missing",
            "groups_missing",
            "members_unassigned",
            "events_missing",
            "scheduled_checks_missing",
          ].includes(p),
      ) && (
        <p role="alert" className="clubs-error">
          {t.alertProblem}
        </p>
      )}
      {r.last_check_at && (
        <p>{new Date(`${r.last_check_at}Z`).toLocaleString()}</p>
      )}
      {!detail.calendar_enabled && (
        <div className="clubs-checks">
          {(Object.keys(checks) as (keyof typeof checks)[]).map((key) => (
            <label key={key} className="clubs-check">
              <input
                type="checkbox"
                checked={checks[key]}
                onChange={(e) =>
                  setChecks((old) => ({ ...old, [key]: e.target.checked }))
                }
              />
              {t[key]}
            </label>
          ))}
        </div>
      )}
      <button
        className={detail.calendar_enabled ? "clubs-danger" : "clubs-primary"}
        disabled={
          !detail.calendar_enabled &&
          (r.problems.length > 0 || !Object.values(checks).every(Boolean))
        }
        onClick={() => {
          if (
            window.confirm(
              detail.calendar_enabled ? t.pauseConfirm : t.enableConfirm,
            )
          )
            void run(async () => {
              await api.activate(
                detail.club.id,
                !detail.calendar_enabled,
                checks,
              );
              await refreshAuth();
            });
        }}
      >
        {detail.calendar_enabled ? t.pause : t.enable}
      </button>
    </div>
  );
}
