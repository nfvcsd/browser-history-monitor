/* Foreground time estimation. All durable queue mutations are serialized. */
const ActivityTracker = (() => {
  const MAX_GAP_MS = 45000;
  const MAX_QUEUE = 10000;
  let serial = Promise.resolve();
  let sending = false;

  function interval(previous, next, now, transition) {
    if (!previous?.page || now <= previous.at || now - previous.at > MAX_GAP_MS)
      return null;
    if (
      !transition &&
      (!next?.page ||
        previous.page.tabId !== next.page.tabId ||
        previous.page.url !== next.page.url ||
        previous.scope !== next.scope)
    )
      return null;
    return {
      sample_id: crypto.randomUUID(),
      url: previous.page.url,
      title: previous.page.title || null,
      started_at: new Date(previous.at).toISOString(),
      ended_at: new Date(now).toISOString(),
    };
  }
  function enqueue(fn) {
    const work = serial.then(fn);
    serial = work.catch((error) =>
      chrome.storage.local.set({
        lastActivityError: String(error?.message || error),
      }),
    );
    return work;
  }
  async function context() {
    const auth = await DeviceAuth.context();
    const { config, identity, deviceKey } = auth;
    const apiUrl = config.apiUrl.replace(/\/$/, "");
    return {
      config,
      auth,
      email: identity.email.trim().toLowerCase(),
      deviceKey,
      apiUrl,
      scope: JSON.stringify([
        apiUrl,
        identity.email.trim().toLowerCase(),
        deviceKey,
      ]),
    };
  }
  async function sample(transition = false, reset = false) {
    const now = Date.now();
    return enqueue(async () => {
      let { activitySession } =
        await chrome.storage.session.get("activitySession");
      if (!activitySession) {
        activitySession = crypto.randomUUID();
        await chrome.storage.session.set({ activitySession });
      }
      const { activitySnapshot: previous, activityQueue = [] } =
        await chrome.storage.local.get(["activitySnapshot", "activityQueue"]);
      const ctx = await context();
      const policy = await CollectionPolicy.get();
      let page = null;
      if (
        ctx &&
        policy.allowed &&
        (await chrome.idle.queryState(60)) === "active"
      ) {
        const window = await chrome.windows
          .getLastFocused({ populate: true, windowTypes: ["normal"] })
          .catch(() => null);
        const tab = window?.tabs?.find((tab) => tab.active);
        if (
          window?.focused &&
          tab &&
          !tab.incognito &&
          /^https?:\/\//i.test(tab.url || "") &&
          tab.url.length <= 8192
        ) {
          page = {
            tabId: tab.id,
            url: tab.url,
            title: (tab.title || "").slice(0, 4096),
          };
        }
      }
      const next = {
        at: Date.now(),
        page,
        scope: ctx?.scope,
        session: activitySession,
        policy,
      };
      let entry =
        reset ||
        previous?.session !== activitySession ||
        previous?.scope !== ctx?.scope
          ? null
          : interval(previous, next, now, transition);
      if (entry) {
        const permission = previous.policy;
        if (
          !policy.allowed ||
          !permission?.allowed ||
          permission.revision !== policy.revision
        ) {
          entry = null;
        } else if (permission.restricted) {
          const end = Math.min(now, Date.parse(permission.valid_until));
          if (
            previous.at < Date.parse(permission.valid_from) ||
            end <= previous.at
          )
            entry = null;
          else {
            entry.ended_at = new Date(end).toISOString();
            entry.collection_permit = permission.permit;
          }
        }
      }
      if (entry) {
        if (
          activityQueue.length >= MAX_QUEUE ||
          new TextEncoder().encode(JSON.stringify([...activityQueue, entry]))
            .length >
            4 * 1024 * 1024
        ) {
          await chrome.storage.local.set({
            lastActivityError:
              "Activity queue full; new time samples skipped until sync succeeds.",
          });
        } else {
          activityQueue.push({ scope: ctx.scope, ...entry });
        }
      }
      // Atomically persist samples and their checkpoint to survive worker termination.
      await chrome.storage.local.set({ activityQueue, activitySnapshot: next });
    });
  }
  async function flush() {
    if (sending) return;
    sending = true;
    try {
      const ctx = await context();
      if (!ctx) return;
      const batch = await enqueue(async () => {
        const { activityQueue = [] } =
          await chrome.storage.local.get("activityQueue");
        return activityQueue
          .filter((item) => item.scope === ctx.scope)
          .slice(0, 250);
      });
      if (!batch.length) return;
      const response = await fetch(`${ctx.apiUrl}/api/v1/sync/activity`, {
        method: "POST",
        signal: AbortSignal.timeout(15000),
        headers: {
          "Content-Type": "application/json",
          ...ctx.auth.headers,
        },
        body: JSON.stringify({
          user_email: ctx.email,
          device_key: ctx.deviceKey,
          device_name: navigator.userAgent,
          extension_version: chrome.runtime.getManifest().version,
          intervals: batch.map(({ scope, ...item }) => item),
        }),
      });
      if (!response.ok) {
        await DeviceAuth.rejected(response, ctx.auth);
        throw new Error(`Activity sync failed: ${response.status}`);
      }
      const result = await response.json();
      if (
        result.accepted + result.duplicates + (result.filtered || 0) !==
        batch.length
      )
        throw new Error("Unexpected activity acknowledgement");
      const ids = new Set(batch.map((item) => item.sample_id));
      await enqueue(async () => {
        const { activityQueue = [] } =
          await chrome.storage.local.get("activityQueue");
        await chrome.storage.local.set({
          activityQueue: activityQueue.filter(
            (item) => !ids.has(item.sample_id),
          ),
          lastActivitySync: new Date().toISOString(),
          lastActivityError: "",
        });
      });
    } catch (error) {
      await chrome.storage.local.set({
        lastActivityError: String(error?.message || error),
      });
    } finally {
      sending = false;
    }
  }
  function wake(transition = false, reset = false) {
    void sample(transition, reset)
      .then(flush)
      .catch(() => {});
  }
  function install() {
    chrome.idle.setDetectionInterval(60);
    chrome.tabs.onActivated.addListener(() => wake(true));
    chrome.tabs.onUpdated.addListener((_id, change) => {
      if (change.url || change.title || change.status === "complete")
        wake(true);
    });
    chrome.tabs.onRemoved.addListener(() => wake(true));
    chrome.windows.onFocusChanged.addListener(() => wake(true));
    chrome.idle.onStateChanged.addListener(() => wake(true));
    chrome.runtime.onStartup.addListener(() => wake(false, true));
    chrome.runtime.onInstalled.addListener(() => wake(false, true));
    chrome.alarms.onAlarm.addListener((alarm) => {
      if (alarm.name === "activity-heartbeat") wake();
    });
    void chrome.alarms.get("activity-heartbeat").then((alarm) => {
      if (!alarm)
        return chrome.alarms.create("activity-heartbeat", {
          periodInMinutes: 0.5,
        });
    });
    wake();
  }
  return { interval, sample, flush, install };
})();
if (typeof module !== "undefined") module.exports = ActivityTracker;
