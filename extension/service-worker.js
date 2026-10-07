importScripts("device-auth.js", "collection-policy.js", "activity-tracker.js");
const DEFAULTS = {
  enrollmentMode: "development",
  apiUrl: "http://localhost:8000",
  extensionToken: "",
  initialHistoryDays: 7,
  reconciliationMinutes: 5,
  fallbackEmail: "",
};

const BATCH_SIZE = 250;
const RECONCILE_LOOKBACK_MINUTES = 10;

async function getConfig() {
  const managed = await chrome.storage.managed.get(null);
  const local = await chrome.storage.local.get(DEFAULTS);
  const { managedEnrollmentSeen } = await chrome.storage.local.get(
    "managedEnrollmentSeen",
  );
  const mode =
    managed.enrollmentMode ||
    (managed.apiUrl ? "enrolled" : local.enrollmentMode);
  if (mode === "enrolled") {
    if (!managed.apiUrl)
      throw new Error("Waiting for Google Admin managed configuration");
    await chrome.storage.local.set({ managedEnrollmentSeen: true });
    return {
      ...DEFAULTS,
      ...managed,
      enrollmentMode: "enrolled",
      extensionToken: "",
      fallbackEmail: "",
    };
  }
  if (managedEnrollmentSeen && managed.enrollmentMode !== "development")
    throw new Error(
      "Managed enrollment configuration was removed; collection paused",
    );
  return { ...DEFAULTS, ...local, ...managed };
}

let deviceKeyPromise;
function getDeviceKey() {
  if (!deviceKeyPromise)
    deviceKeyPromise = createDeviceKey().catch((error) => {
      deviceKeyPromise = undefined;
      throw error;
    });
  return deviceKeyPromise;
}
async function createDeviceKey() {
  const { deviceKey } = await chrome.storage.local.get("deviceKey");
  if (deviceKey) return deviceKey;

  const created = crypto.randomUUID();
  await chrome.storage.local.set({ deviceKey: created });
  return created;
}

async function getIdentity(config) {
  try {
    const profile = await chrome.identity.getProfileUserInfo({
      accountStatus: "ANY",
    });
    if (profile?.email) {
      return { email: profile.email, displayName: null };
    }
  } catch (error) {
    console.warn("Unable to read Chrome profile identity", error);
  }

  if (config.fallbackEmail) {
    return { email: config.fallbackEmail, displayName: null };
  }

  throw new Error(
    "No Chrome profile email is available. Configure a fallback email in extension options.",
  );
}

async function postBatch(visits) {
  if (!visits.length) return;

  const ctx = await DeviceAuth.context();
  const { config, identity, deviceKey } = ctx;

  const response = await fetch(
    `${config.apiUrl.replace(/\/$/, "")}/api/v1/sync/batch`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...ctx.headers,
      },
      body: JSON.stringify({
        user_email: identity.email,
        display_name: identity.displayName,
        device_key: deviceKey,
        device_name: navigator.userAgent,
        extension_version: chrome.runtime.getManifest().version,
        visits,
      }),
    },
  );

  if (!response.ok) {
    await DeviceAuth.rejected(response, ctx);
    const text = await response.text();
    throw new Error(`Sync failed: ${response.status} ${text}`);
  }

  const result = await response.json();
  await chrome.storage.local.set({
    lastSuccessfulSync: new Date().toISOString(),
    lastSyncResult: result,
    lastSyncError: "",
  });

  return result;
}

function toPayload(historyItem, visit) {
  if (!historyItem.url || !visit.visitId || !visit.visitTime) return null;

  return {
    chrome_visit_id: String(visit.visitId),
    chrome_history_id: String(historyItem.id ?? ""),
    referring_visit_id: visit.referringVisitId
      ? String(visit.referringVisitId)
      : null,
    url: historyItem.url,
    title: historyItem.title ?? null,
    visit_time: new Date(visit.visitTime).toISOString(),
    transition: visit.transition ?? null,
    is_local: typeof visit.isLocal === "boolean" ? visit.isLocal : null,
    visit_count:
      typeof historyItem.visitCount === "number"
        ? historyItem.visitCount
        : null,
    typed_count:
      typeof historyItem.typedCount === "number"
        ? historyItem.typedCount
        : null,
  };
}

async function sendInChunks(visits) {
  let accepted = 0;
  let duplicates = 0;

  for (let i = 0; i < visits.length; i += BATCH_SIZE) {
    const result = await postBatch(visits.slice(i, i + BATCH_SIZE));
    accepted += result?.accepted ?? 0;
    duplicates += result?.duplicates ?? 0;
  }

  return { accepted, duplicates };
}

async function collectRange(startTime, endTime = Date.now()) {
  const policy = await CollectionPolicy.get();
  if (!policy.allowed) {
    if (policy.reason === "policy_unavailable")
      throw new Error(
        "Collection policy unavailable; history collection paused.",
      );
    return [];
  }
  const permits = await CollectionPolicy.permits(policy);
  if (policy.restricted) {
    if (!permits.length) return [];
    startTime = Math.max(
      startTime,
      Math.min(...permits.map((item) => Date.parse(item.valid_from))),
    );
    if (startTime > endTime) return [];
  }
  const items = await chrome.history.search({
    text: "",
    startTime,
    endTime,
    maxResults: 10000,
  });

  const collected = [];

  for (const item of items) {
    if (!item.url) continue;

    const visits = await chrome.history.getVisits({ url: item.url });
    for (const visit of visits) {
      if (!visit.visitTime) continue;
      if (visit.visitTime < startTime || visit.visitTime > endTime) continue;

      const permit = CollectionPolicy.forTime(permits, visit.visitTime);
      if (policy.restricted && !permit) continue;
      const payload = toPayload(item, visit);
      if (payload)
        collected.push({ ...payload, collection_permit: permit?.permit });
    }
  }

  collected.sort((a, b) => a.visit_time.localeCompare(b.visit_time));
  return collected;
}

async function reconcile(lookbackMinutes = RECONCILE_LOOKBACK_MINUTES) {
  try {
    const startTime = Date.now() - lookbackMinutes * 60 * 1000;
    const visits = await collectRange(startTime);
    const result = await sendInChunks(visits);
    console.log("Reconciliation complete", result);
    return result;
  } catch (error) {
    console.error("Reconciliation failed", error);
    await chrome.storage.local.set({
      lastSyncError: String(error?.message ?? error),
    });
    throw error;
  }
}

async function initialSync() {
  const config = await getConfig();
  const startTime =
    Date.now() - Number(config.initialHistoryDays || 7) * 24 * 60 * 60 * 1000;

  try {
    const visits = await collectRange(startTime);
    const result = await sendInChunks(visits);
    await chrome.storage.local.set({
      initialSyncCompleted: new Date().toISOString(),
    });
    console.log("Initial sync complete", result);
  } catch (error) {
    console.error("Initial sync failed", error);
    await chrome.storage.local.set({
      lastSyncError: String(error?.message ?? error),
    });
  }
}

async function syncVisitedItem(historyItem) {
  if (!historyItem?.url) return;

  try {
    const policy = await CollectionPolicy.get();
    if (!policy.allowed) return;
    const permits = await CollectionPolicy.permits(policy);
    const visits = await chrome.history.getVisits({ url: historyItem.url });
    const newest = visits
      .filter((visit) => visit.visitTime)
      .sort((a, b) => (b.visitTime ?? 0) - (a.visitTime ?? 0))[0];

    if (!newest) return;

    const payload = toPayload(historyItem, newest);
    const permit = CollectionPolicy.forTime(permits, newest.visitTime);
    if (policy.restricted && !permit) return;
    if (payload)
      await postBatch([{ ...payload, collection_permit: permit?.permit }]);
  } catch (error) {
    console.warn(
      "Immediate visit sync failed; reconciliation will retry it.",
      error,
    );
  }
}

async function configureReconciliation() {
  const config = await getConfig();
  const minutes = Number(config.reconciliationMinutes);
  await chrome.alarms.create("history-reconcile", {
    periodInMinutes:
      Number.isInteger(minutes) && minutes >= 1 && minutes <= 60 ? minutes : 5,
  });
}
chrome.runtime.onInstalled.addListener(() => {
  void configureReconciliation().catch((error) =>
    chrome.storage.local.set({ enrollmentStatus: error.message }),
  );
  void initialSync();
});

chrome.runtime.onStartup.addListener(() => {
  void configureReconciliation().catch((error) =>
    chrome.storage.local.set({ enrollmentStatus: error.message }),
  );
  void reconcile(30);
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "history-reconcile") {
    void reconcile();
  }
});

chrome.history.onVisited.addListener((historyItem) => {
  void syncVisitedItem(historyItem);
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "TEST_SYNC") {
    reconcile(5)
      .then((result) => sendResponse({ ok: true, result }))
      .catch((error) =>
        sendResponse({ ok: false, error: String(error?.message ?? error) }),
      );
    return true;
  }

  if (message?.type === "INITIAL_SYNC") {
    initialSync()
      .then(() => sendResponse({ ok: true }))
      .catch((error) =>
        sendResponse({ ok: false, error: String(error?.message ?? error) }),
      );
    return true;
  }
});

ActivityTracker.install();

self.addEventListener("online", () => CollectionPolicy.invalidate());
self.addEventListener("offline", () => CollectionPolicy.invalidate());

chrome.identity.onSignInChanged.addListener(() => {
  DeviceAuth.invalidate();
  CollectionPolicy.invalidate();
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "managed")
    void configureReconciliation().catch((error) =>
      chrome.storage.local.set({ enrollmentStatus: error.message }),
    );
  if (
    area === "managed" ||
    (area === "local" &&
      ["apiUrl", "extensionToken", "fallbackEmail", "enrollmentMode"].some(
        (key) => key in changes,
      ))
  ) {
    DeviceAuth.invalidate();
    CollectionPolicy.invalidate();
  }
});

void chrome.storage.local.setAccessLevel?.({ accessLevel: "TRUSTED_CONTEXTS" });
