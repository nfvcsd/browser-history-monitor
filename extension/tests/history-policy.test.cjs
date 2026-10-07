const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
function setup(allowed, restricted) {
  const calls = [],
    local = {};
  const permission = {
    permit: "signed",
    valid_from: new Date(1000000).toISOString(),
    valid_until: new Date(1045000).toISOString(),
  };
  const event = { addListener: () => {} };
  const context = {
    console,
    importScripts: () => {},
    ActivityTracker: { install: () => {} },
    CollectionPolicy: {
      get: async () => ({ allowed, restricted }),
      permits: async () => [permission],
      forTime: (items, t) =>
        items.find(
          (p) => Date.parse(p.valid_from) <= t && t < Date.parse(p.valid_until),
        ),
      invalidate: () => {},
    },
    Date,
    crypto: require("node:crypto").webcrypto,
    navigator: { userAgent: "test" },
    self: { addEventListener: () => {} },
    chrome: {
      storage: {
        managed: { get: async () => ({}) },
        local: {
          get: async (key) =>
            typeof key === "object"
              ? {
                  ...key,
                  extensionToken: "token",
                  fallbackEmail: "alice@example.com",
                }
              : { deviceKey: "device-key" },
          set: async (v) => Object.assign(local, v),
        },
        onChanged: event,
      },
      identity: {
        getProfileUserInfo: async () => ({ email: "alice@example.com" }),
        onSignInChanged: event,
      },
      runtime: {
        onInstalled: event,
        onStartup: event,
        onMessage: event,
        getManifest: () => ({ version: "0.3.0" }),
      },
      alarms: { onAlarm: event },
      history: {
        onVisited: event,
        search: async (range) => {
          calls.push(range);
          return [{ id: "1", url: "https://example.com", title: "Lesson" }];
        },
        getVisits: async () => [
          { visitId: "old", visitTime: 990000 },
          { visitId: "allowed", visitTime: 1010000 },
          { visitId: "after", visitTime: 1050000 },
        ],
      },
    },
  };
  vm.runInNewContext(
    fs.readFileSync(require.resolve("../service-worker.js"), "utf8"),
    context,
  );
  return { context, calls };
}
test("paused policy never reads Chrome history", async () => {
  const s = setup(false, true);
  assert.equal((await s.context.collectRange(0, 1100000)).length, 0);
  await s.context.syncVisitedItem({ url: "https://example.com" });
  assert.equal(s.calls.length, 0);
});
test("restricted reconciliation only returns visits covered at collection time", async () => {
  const s = setup(true, true);
  const visits = await s.context.collectRange(0, 1100000);
  assert.equal(s.calls[0].startTime, 1000000);
  assert.equal(visits.length, 1);
  assert.equal(visits[0].chrome_visit_id, "allowed");
  assert.equal(visits[0].collection_permit, "signed");
});
test("unrestricted configuration preserves historical backfill", async () => {
  const s = setup(true, false);
  assert.equal((await s.context.collectRange(0, 1100000)).length, 3);
});

test('managed enrollment ignores local credentials and fails closed if policy disappears',async()=>{
 const s=setup(true,false);const local={apiUrl:'http://local',extensionToken:'shared-secret',fallbackEmail:'fake@example.com'};let managed={apiUrl:'https://school.example',enrollmentMode:'enrolled'};
 s.context.chrome.storage.local.get=async key=>typeof key==='object'?Object.fromEntries(Object.keys(key).map(k=>[k,local[k]??key[k]])):{[key]:local[key]};
 s.context.chrome.storage.local.set=async values=>Object.assign(local,values);
 s.context.chrome.storage.managed.get=async()=>managed;
 const config=await s.context.getConfig();assert.equal(config.apiUrl,'https://school.example');assert.equal(config.extensionToken,'');assert.equal(config.fallbackEmail,'');
 managed={};await assert.rejects(s.context.getConfig(),/removed/);
 managed={enrollmentMode:'development'};assert.equal((await s.context.getConfig()).extensionToken,'shared-secret');
});
