const DEFAULTS = {
  apiUrl: "http://localhost:8000",
  extensionToken: "",
  initialHistoryDays: 7,
  reconciliationMinutes: 5,
  fallbackEmail: "",
};

const BATCH_SIZE = 250;
const RECONCILE_LOOKBACK_MINUTES = 10;

async function getConfig() {
  const managed = await chrome.storage.managed.get(null).catch(() => ({}));
  const local = await chrome.storage.local.get(DEFAULTS);
  return { ...DEFAULTS, ...local, ...managed };
}

async function getDeviceKey() {
  const { deviceKey } = await chrome.storage.local.get("deviceKey");
  if (deviceKey) return deviceKey;

  const created = crypto.randomUUID();
  await chrome.storage.local.set({ deviceKey: created });
  return created;
}

async function getIdentity(config) {
  try {
    const profile = await chrome.identity.getProfileUserInfo({ accountStatus: "ANY" });
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
    "No Chrome profile email is available. Configure a fallback email in extension options."
  );
}

async function postBatch(visits) {
  if (!visits.length) return;

  const config = await getConfig();
  if (!config.extensionToken) {
    throw new Error("Extension token is not configured.");
  }

  const identity = await getIdentity(config);
  const deviceKey = await getDeviceKey();

  const response = await fetch(
    `${config.apiUrl.replace(/\/$/, "")}/api/v1/sync/batch`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Extension-Token": config.extensionToken,
      },
      body: JSON.stringify({
        user_email: identity.email,
        display_name: identity.displayName,
        device_key: deviceKey,
        device_name: navigator.userAgent,
        extension_version: chrome.runtime.getManifest().version,
        visits,
      }),
    }
  );

  if (!response.ok) {
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
      typeof historyItem.visitCount === "number" ? historyItem.visitCount : null,
    typed_count:
      typeof historyItem.typedCount === "number" ? historyItem.typedCount : null,
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

      const payload = toPayload(item, visit);
      if (payload) collected.push(payload);
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
    const visits = await chrome.history.getVisits({ url: historyItem.url });
    const newest = visits
      .filter((visit) => visit.visitTime)
      .sort((a, b) => (b.visitTime ?? 0) - (a.visitTime ?? 0))[0];

    if (!newest) return;

    const payload = toPayload(historyItem, newest);
    if (payload) await postBatch([payload]);
  } catch (error) {
    console.warn("Immediate visit sync failed; reconciliation will retry it.", error);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("history-reconcile", { periodInMinutes: 5 });
  void initialSync();
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("history-reconcile", { periodInMinutes: 5 });
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
        sendResponse({ ok: false, error: String(error?.message ?? error) })
      );
    return true;
  }

  if (message?.type === "INITIAL_SYNC") {
    initialSync()
      .then(() => sendResponse({ ok: true }))
      .catch((error) =>
        sendResponse({ ok: false, error: String(error?.message ?? error) })
      );
    return true;
  }
});
