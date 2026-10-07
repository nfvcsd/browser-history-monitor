const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const crypto = require("node:crypto").webcrypto;
function setup() {
  let now = 1000000,
    active = true,
    focused = true,
    tab = { id: 1, active: true, url: "https://example.test/a", title: "A" },
    fail = false;
  const local = {},
    session = {};
  const store = (data) => ({
    get: async (key) =>
      typeof key === "string"
        ? { [key]: structuredClone(data[key]) }
        : Object.fromEntries(key.map((k) => [k, structuredClone(data[k])])),
    set: async (values) => Object.assign(data, structuredClone(values)),
  });
  const context = {
    CollectionPolicy: {
      get: async () => ({ allowed: true, restricted: false, revision: 1 }),
    },
    module: { exports: {} },
    crypto,
    TextEncoder,
    Date: class extends Date {
      static now() {
        return now;
      }
    },
    AbortSignal,
    navigator: { userAgent: "test" },
    getConfig: async () => ({
      apiUrl: "http://server",
      extensionToken: "token",
    }),
    getIdentity: async () => ({ email: "user@example.test" }),
    getDeviceKey: async () => "device-key",
    chrome: {
      storage: { local: store(local), session: store(session) },
      idle: { queryState: async () => (active ? "active" : "idle") },
      windows: { getLastFocused: async () => ({ focused, tabs: [tab] }) },
      runtime: { getManifest: () => ({ version: "0.2.0" }) },
    },
    fetch: async (_url, options) => {
      if (fail) throw Error("offline");
      const batch = JSON.parse(options.body);
      return {
        ok: true,
        json: async () => ({ accepted: batch.intervals.length, duplicates: 0 }),
      };
    },
  };
  context.DeviceAuth = {
    context: async () => ({
      config: await context.getConfig(),
      identity: await context.getIdentity(),
      deviceKey: await context.getDeviceKey(),
      headers: { "X-Extension-Token": "token" },
      authKey: "token",
    }),
    rejected: async () => {},
  };
  vm.runInNewContext(
    fs.readFileSync(require.resolve("../activity-tracker.js"), "utf8"),
    context,
  );
  return {
    tracker: context.module.exports,
    local,
    session,
    advance: (ms) => (now += ms),
    focus: (v) => (focused = v),
    idle: (v) => (active = !v),
    tab: (v) => (tab = { ...tab, ...v }),
    fail: (v) => (fail = v),
    context,
  };
}
test("foreground switching, idle, blur, long gaps and restart", async () => {
  const s = setup();
  await s.tracker.sample();
  s.advance(30000);
  await s.tracker.sample();
  assert.equal(s.local.activityQueue.length, 1);
  s.advance(10000);
  s.tab({ id: 2, url: "https://example.test/b" });
  await s.tracker.sample(true);
  assert.equal(s.local.activityQueue[1].url, "https://example.test/a");
  s.advance(10000);
  s.focus(false);
  await s.tracker.sample(true);
  s.advance(30000);
  await s.tracker.sample();
  assert.equal(s.local.activityQueue.length, 3);
  s.focus(true);
  await s.tracker.sample();
  s.advance(10000);
  s.idle(true);
  await s.tracker.sample(true);
  s.advance(30000);
  await s.tracker.sample();
  assert.equal(s.local.activityQueue.length, 4);
  s.idle(false);
  await s.tracker.sample();
  s.advance(90000);
  await s.tracker.sample();
  assert.equal(s.local.activityQueue.length, 4);
  delete s.session.activitySession;
  s.advance(10000);
  await s.tracker.sample();
  assert.equal(s.local.activityQueue.length, 4);
});
test("durable retry IDs, worker restart, incognito and forbidden pages", async () => {
  const s = setup();
  await s.tracker.sample();
  s.advance(30000);
  await s.tracker.sample();
  const id = s.local.activityQueue[0].sample_id;
  s.fail(true);
  await s.tracker.flush();
  assert.equal(s.local.activityQueue[0].sample_id, id);
  const restarted = { ...s.context, module: { exports: {} } };
  vm.runInNewContext(
    fs.readFileSync(require.resolve("../activity-tracker.js"), "utf8"),
    restarted,
  );
  s.tracker = restarted.module.exports;
  s.advance(10000);
  await s.tracker.sample();
  assert.equal(s.local.activityQueue.length, 2);
  assert.equal(s.local.activityQueue[0].sample_id, id);
  s.fail(false);
  await s.tracker.flush();
  assert.equal(s.local.activityQueue.length, 0);
  s.tab({ incognito: true });
  s.advance(10000);
  await s.tracker.sample(true);
  const count = s.local.activityQueue.length;
  s.advance(30000);
  await s.tracker.sample();
  assert.equal(s.local.activityQueue.length, count);
  s.tab({ incognito: false, url: "chrome://settings" });
  await s.tracker.sample();
  s.advance(30000);
  await s.tracker.sample();
  assert.equal(s.local.activityQueue.length, count);
});

test("restricted activity carries permission, clips expiry and drops blocked transitions", async () => {
  const s = setup();
  let permission = {
    allowed: true,
    restricted: true,
    revision: 1,
    permit: "signed",
    valid_from: new Date(1000000).toISOString(),
    valid_until: new Date(1020000).toISOString(),
  };
  s.context.CollectionPolicy.get = async () => permission;
  await s.tracker.sample();
  s.advance(30000);
  await s.tracker.sample();
  assert.equal(s.local.activityQueue.length, 1);
  assert.equal(s.local.activityQueue[0].collection_permit, "signed");
  assert.equal(
    s.local.activityQueue[0].ended_at,
    new Date(1020000).toISOString(),
  );
  permission = { allowed: false, restricted: true, revision: 1 };
  s.advance(10000);
  await s.tracker.sample(true);
  assert.equal(s.local.activityQueue.length, 1);
  assert.equal(s.local.activitySnapshot.page, null);
  permission = {
    allowed: true,
    restricted: true,
    revision: 2,
    permit: "new",
    valid_from: new Date(1040000).toISOString(),
    valid_until: new Date(1080000).toISOString(),
  };
  await s.tracker.sample();
  s.advance(10000);
  await s.tracker.sample();
  assert.equal(s.local.activityQueue.length, 2);
  assert.equal(s.local.activityQueue[1].collection_permit, "new");
});
