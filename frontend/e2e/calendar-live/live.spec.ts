import { test, expect, type Browser, type Page } from "@playwright/test";

// Two-account flows on a real backend + disposable database seeded with the
// dev accounts and the reviewed KCPM import. Gated by env; credentials are
// never committed. Accounts: manager, coach, alice, bruno, una @dev.test.
const PASSWORD = process.env.CALENDAR_LIVE_PASSWORD;
const INVITE_CODE = process.env.CALENDAR_LIVE_INVITE_CODE;
test.skip(!PASSWORD, "CALENDAR_LIVE_PASSWORD not set (live run only)");
test.describe.configure({ mode: "serial" });

const OCT = "/calendar?date=2026-10-01";
const shots = "/tmp/calendar-task03-live-shots";

async function session(browser: Browser, who: string, width: number, height = 844): Promise<Page> {
  const context = await browser.newContext({ viewport: { width, height }, locale: "fr-FR",
    isMobile: width < 768, hasTouch: width < 768 });
  const page = await context.newPage();
  await page.goto("/login");
  await page.locator('input[type="email"]').fill(`${who}@dev.test`);
  await page.locator('input[type="password"]').fill(PASSWORD!);
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/api/v1/auth/login")),
    page.locator('button[type="submit"]').click(),
  ]);
  expect(response.status()).toBe(200);
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
  return page;
}

/** Navigate and wait until the calendar page has rendered (dev server compiles lazily). */
async function open(page: Page, url: string) {
  await page.goto(url);
  try {
    await page.locator(".calendar-page").waitFor({ timeout: 30_000 });
  } catch (error) {
    console.log("open failed", url, page.url(), JSON.stringify((await page.locator("body").innerText()).slice(0, 300)));
    throw error;
  }
}

/** Tap Save directly while a field still has focus (the realistic first tap on
 * a phone): the shell hides the bottom nav during text entry and restores it
 * on blur, so this exercises the lost-first-tap regression. */
async function save(page: Page) {
  await page.getByRole("button", { name: "Enregistrer" }).click();
}

const rows = (page: Page) => page.locator(".calendar-agenda .calendar-event");
const tabs = (page: Page) => page.locator(".mobile-tab-bar");

test("manager assigns groups and grants the coach; members then see only their group", async ({ browser }) => {
  const manager = await session(browser, "manager", 1280, 900);
  await open(manager, "/calendar/club/1");
  await expect(manager.getByRole("heading", { name: "Kingfisher Club Plongeon Montreuil" })).toBeVisible();
  await expect(manager.getByText(/pas la liste complète du club/)).toBeVisible();
  const member = (name: string) => manager.locator(".calendar-member").filter({ hasText: name });
  for (const [name, group] of [["Alice", "Débutants"], ["Bruno", "Confirmés"]]) {
    const row = member(name);
    await row.getByLabel("Groupe").selectOption({ label: group });
    await row.getByLabel("À partir du").fill("2026-09-01");
    await row.getByRole("button", { name: "Attribuer" }).click();
    await expect(manager.getByRole("status").filter({ hasText: "Enregistré" })).toBeVisible();
    await expect(member(name)).toContainText(`Groupe : ${group}`.replace(" : ", ": "));
  }
  await member("Coralie").getByLabel("Rôle").selectOption("coach");
  await expect(member("Coralie").getByLabel("Peut publier")).toBeVisible();
  if (!(await member("Coralie").getByLabel("Peut publier").isChecked())) await member("Coralie").getByLabel("Peut publier").click(); // server-confirmed
  await expect(member("Coralie").getByLabel("Peut publier")).toBeChecked();
  if (!(await member("Coralie").getByLabel("Peut attribuer les groupes").isChecked())) await member("Coralie").getByLabel("Peut attribuer les groupes").click(); // server-confirmed
  await expect(member("Coralie").getByLabel("Peut attribuer les groupes")).toBeChecked();
  await expect(member("Una")).toContainText("déclaratif");
  await manager.screenshot({ path: `${shots}/manager-club-1280.png`, fullPage: true });

  const alice = await session(browser, "alice", 390);
  await open(alice, OCT);
  await expect(rows(alice).first()).toBeVisible();
  await expect(tabs(alice).getByRole("link")).toHaveCount(5);
  const aliceTitles = await rows(alice).locator(".calendar-source").allTextContents();
  expect(aliceTitles.some((t) => t.includes("Débutants"))).toBe(true);
  expect(aliceTitles.some((t) => t.includes("Confirmés"))).toBe(false);
  await alice.screenshot({ path: `${shots}/alice-agenda-390.png`, fullPage: true });
  await alice.getByRole("button", { name: "Mois", exact: true }).click();
  expect(await alice.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await alice.screenshot({ path: `${shots}/alice-month-390.png`, fullPage: true });

  const una = await session(browser, "una", 375);
  await open(una, OCT);
  await expect(una.getByRole("status").filter({ hasText: "groupe d’entraînement n’a pas encore été attribué" })).toBeVisible();
  await expect(rows(una)).toHaveCount(0);
  await una.screenshot({ path: `${shots}/una-unassigned-375.png`, fullPage: true });
  await Promise.all([manager, alice, una].map((p) => p.context().close()));
});

test("interest and absence are independent; another group's direct link is unavailable", async ({ browser }) => {
  const alice = await session(browser, "alice", 390);
  await open(alice, "/calendar?date=2026-10-03");
  await rows(alice).filter({ hasText: "Débutants" }).filter({ hasNotText: "Annulé" }).first().click();
  const occurrenceUrl = alice.url();
  await alice.getByRole("button", { name: "Ça m’intéresse", exact: true }).click();
  await expect(alice.getByRole("button", { name: "Ça m’intéresse", exact: true })).toHaveAttribute("aria-pressed", "true");
  const withdraw = alice.getByRole("button", { name: "Retirer mon absence", exact: true });
  if (await withdraw.isVisible()) await withdraw.click(); // rerun on the same disposable DB
  await alice.getByRole("button", { name: "Signaler mon absence", exact: true }).click();
  await expect(alice.locator(".calendar-detail").getByText("Absence signalée", { exact: true })).toBeVisible();
  await expect(alice.getByRole("button", { name: "Ça m’intéresse", exact: true })).toHaveAttribute("aria-pressed", "true");
  // Explicit dive link: own dives on this date only; videos unchanged.
  await alice.getByRole("button", { name: "Lier mes plongeons" }).click();
  await expect(alice.getByLabel(/101B/)).toBeVisible();
  if (!(await alice.getByLabel(/101B/).isChecked())) await alice.getByLabel(/101B/).click(); // server-confirmed
  await expect(alice.getByLabel(/101B/)).toBeChecked();
  await expect(alice.getByText(/ne change jamais qui peut voir vos vidéos/)).toBeVisible();
  await alice.screenshot({ path: `${shots}/alice-detail-390.png`, fullPage: true });
  await alice.reload();
  await expect(alice.getByRole("button", { name: "Ça m’intéresse", exact: true })).toHaveAttribute("aria-pressed", "true");

  const bruno = await session(browser, "bruno", 375);
  await open(bruno, new URL(occurrenceUrl).pathname);
  await expect(bruno.getByRole("alert")).toHaveText(/indisponible/);
  await open(bruno, OCT);
  await expect(rows(bruno).first()).toBeVisible();
  const brunoTitles = await rows(bruno).locator(".calendar-source").allTextContents();
  expect(brunoTitles.length).toBeGreaterThan(0);
  expect(brunoTitles.some((t) => t.includes("Confirmés"))).toBe(true);
  expect(brunoTitles.some((t) => t.includes("Débutants"))).toBe(false);
  await bruno.getByRole("link", { name: "Club KCPM" }).click();
  await expect(bruno.locator(".calendar-member select")).toHaveCount(0); // no admin controls for members
  await Promise.all([alice, bruno].map((p) => p.context().close()));
});

test("invited outing: invite, accept, venue change keeps interest, revoke removes access", async ({ browser }) => {
  const alice = await session(browser, "alice", 390);
  await open(alice, OCT);
  await alice.getByRole("link", { name: "Nouvel événement" }).click();
  await alice.getByRole("textbox", { name: "Titre" }).fill("Sortie fosse à plongeon");
  await alice.getByLabel("Date", { exact: true }).fill("2026-10-24");
  await alice.getByLabel("Début").fill("10:00");
  await alice.getByLabel("Fin").fill("09:00");
  await save(alice);
  await expect(alice.getByRole("alert")).toHaveText(/Vérifiez/);
  await expect(alice.getByRole("textbox", { name: "Titre" })).toHaveValue("Sortie fosse à plongeon");
  await alice.getByLabel("Fin").fill("12:00");
  await alice.getByRole("textbox", { name: "Lieu" }).fill("Fosse de Villeneuve");
  await save(alice);
  await expect(alice.getByRole("heading", { name: "Sortie fosse à plongeon", level: 1 })).toBeVisible();
  const outingUrl = new URL(alice.url()).pathname;
  await alice.getByLabel("Rechercher des personnes").fill("Bru");
  await alice.locator(".calendar-invitations li").filter({ hasText: "Bruno" }).getByRole("button", { name: "Inviter" }).click();
  await expect(alice.locator(".calendar-invitations li").filter({ hasText: "Bruno Confirmé · En attente" })).toBeVisible();

  const bruno = await session(browser, "bruno", 375);
  await open(bruno, outingUrl);
  await expect(bruno.getByRole("heading", { name: "Vous êtes invité·e" })).toBeVisible();
  await bruno.getByRole("button", { name: "Accepter l’invitation" }).click();
  await expect(bruno.getByText(/Invitation\s?: Acceptée/)).toBeVisible();
  await bruno.getByRole("button", { name: "Ça m’intéresse", exact: true }).click();
  await expect(bruno.getByRole("button", { name: "Ça m’intéresse", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(bruno.locator(".calendar-invitations")).toHaveCount(0); // no guest list for invitees

  await alice.reload();
  await alice.getByRole("link", { name: "Modifier l’événement" }).click();
  await alice.getByRole("textbox", { name: "Lieu" }).fill("Fosse Aqualud");
  await alice.getByLabel("Début").fill("14:00");
  await alice.getByLabel("Fin").fill("16:00");
  await save(alice);
  await expect(alice.getByText(/Horaire ou lieu modifié/)).toBeVisible();

  await bruno.reload();
  await expect(bruno.getByText(/Horaire ou lieu modifié/)).toBeVisible();
  await expect(bruno.getByText(/Aucune notification n’est encore envoyée/)).toBeVisible();
  await expect(bruno.locator(".calendar-detail").getByText(/14:00–16:00/)).toBeVisible();
  await expect(bruno.getByRole("button", { name: "Ça m’intéresse", exact: true })).toHaveAttribute("aria-pressed", "true");
  await bruno.screenshot({ path: `${shots}/bruno-invited-changed-375.png`, fullPage: true });

  await alice.reload();
  await alice.locator(".calendar-invitations li").filter({ hasText: "Bruno" }).getByRole("button", { name: "Retirer" }).click();
  await expect(alice.locator(".calendar-invitations li").filter({ hasText: "Bruno Confirmé · Retirée" })).toBeVisible();
  await bruno.reload();
  await expect(bruno.getByRole("alert")).toHaveText(/indisponible/);
  await Promise.all([alice, bruno].map((p) => p.context().close()));
});

test("coach edits and cancels an imported session; stale edit keeps input; members keep responses", async ({ browser }) => {
  const coach = await session(browser, "coach", 1280, 900);
  await open(coach, "/calendar?date=2026-10-03");
  await expect(rows(coach).locator(".calendar-source").filter({ hasText: "Confirmés" }).first()).toBeVisible();
  await expect(rows(coach).locator(".calendar-source").filter({ hasText: "Débutants" }).first()).toBeVisible();
  // First not-yet-cancelled beginners session (reruns on the same disposable DB).
  await rows(coach).filter({ hasText: "Débutants" }).filter({ hasNotText: "Annulé" }).first().click();
  const sessionUrl = new URL(coach.url()).pathname;
  await coach.getByRole("link", { name: "Modifier cette séance" }).click();
  await coach.getByRole("textbox", { name: "Lieu" }).fill("SNMT bassin extérieur");
  // A second tab edits first: this tab's save must report a conflict and keep input.
  const other = await coach.context().newPage();
  await open(other, sessionUrl + "/edit");
  await other.getByRole("textbox", { name: "Lieu" }).fill(`SNMT grand bassin ${Date.now()}`);
  await save(other);
  await expect(other.getByText(/Horaire ou lieu modifié/)).toBeVisible();
  await save(coach);
  await expect(coach.getByRole("alert")).toHaveText(/Quelqu’un a modifié/);
  await expect(coach.getByRole("textbox", { name: "Lieu" })).toHaveValue("SNMT bassin extérieur");
  await coach.getByRole("button", { name: "Recharger" }).click();
  await expect(coach.getByRole("alert")).toHaveCount(0); // latest version loaded, input kept
  await expect(coach.getByRole("textbox", { name: "Lieu" })).toHaveValue("SNMT bassin extérieur");
  await save(coach);
  await expect(coach.getByText("SNMT bassin extérieur")).toBeVisible();
  await coach.getByRole("button", { name: "Annuler cette séance" }).click();
  await coach.getByRole("button", { name: "Confirmer l’annulation" }).click();
  await expect(coach.getByText(/réponses sont conservées/)).toBeVisible();
  await coach.screenshot({ path: `${shots}/coach-cancelled-1280.png`, fullPage: true });

  const alice = await session(browser, "alice", 430);
  await open(alice, sessionUrl);
  await expect(alice.getByText(/réponses sont conservées/)).toBeVisible();
  await expect(alice.getByRole("button", { name: "Ça m’intéresse", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(alice.getByRole("button", { name: "Ça m’intéresse", exact: true })).toBeDisabled();
  await Promise.all([coach, alice].map((p) => p.context().close()));
});

test("signup with the club selector creates a plain self-declared membership", async ({ browser }) => {
  test.skip(!INVITE_CODE, "registration invite code not provided");
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: "fr-FR", isMobile: true });
  const page = await context.newPage();
  await page.goto("/register");
  await page.locator('input[type="email"]').fill(`nina${Date.now()}@dev.test`);
  await page.locator('input[type="password"]').nth(0).fill(PASSWORD!);
  await page.locator('input[type="password"]').nth(1).fill(PASSWORD!);
  await page.locator('input[type="text"]').last().fill(INVITE_CODE!); // invite code field
  await expect(page.getByText(/Déclaratif/)).toBeVisible();
  await page.getByLabel(/Club/).selectOption({ label: "Kingfisher Club Plongeon Montreuil" });
  await page.screenshot({ path: `${shots}/register-club-390.png`, fullPage: true });
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/dives/);
  await open(page, OCT);
  await expect(page.getByRole("status").filter({ hasText: "pas encore été attribué" })).toBeVisible();
  await expect(rows(page)).toHaveCount(0);
  await open(page, "/calendar/club/1");
  await expect(page.getByText(/déclarative/)).toBeVisible();
  await context.close();
});
