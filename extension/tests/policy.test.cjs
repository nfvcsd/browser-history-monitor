const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
function setup() {
  let now = 1000000,
    mode = "connection",
    enabled = false,
    allowed = true,
    fail = false,
    lookupFail = false,
    revision = 1;
  const local = {},
    session = {},
    requests = [];
  const store = (data) => ({
    get: async (key) => ({ [key]: structuredClone(data[key]) }),
    set: async (value) => Object.assign(data, structuredClone(value)),
  });
  const context = {
    module: { exports: {} },
    Date: class extends Date {
      static now() {
        return now;
      }
    },
    AbortSignal,
    navigator: { userAgent: "test" },
    getConfig: async () => ({
      apiUrl: "https://backend",
      extensionToken: "secret",
    }),
    getIdentity: async () => ({ email: "alice@example.com" }),
    getDeviceKey: async () => "device-id",
    chrome: {
      storage: { local: store(local), session: store(session) },
      runtime: { getManifest: () => ({ version: "0.3.0" }) },
    },
    fetch: async (url, opts) => {
      requests.push({ url, opts });
      if (url.startsWith("https://api64.ipify.org")) {
        if (lookupFail) throw Error("unavailable");
        return { ok: true, json: async () => ({ ip: "8.8.8.8" }) };
      }
      if (fail) throw Error("offline");
      const body = JSON.parse(opts.body);
      const permitted =
        allowed &&
        (!enabled || mode === "connection" || body.public_ip === "8.8.8.8");
      return {
        ok: true,
        json: async () => ({
          allowed: permitted,
          restricted: enabled,
          reason: permitted ? "collecting" : "ip_not_allowed",
          ip_enabled: enabled,
          ip_source: mode,
          source_ip: body.public_ip || null,
          revision,
          permit: "signed",
          valid_from: new Date(now).toISOString(),
          valid_until: new Date(now + 45000).toISOString(),
        }),
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
    fs.readFileSync(require.resolve("../collection-policy.js"), "utf8"),
    context,
  );
  return {
    policy: context.module.exports,
    local,
    session,
    requests,
    advance: (ms) => (now += ms),
    device: () => {
      enabled = true;
      mode = "device";
    },
    block: () => (allowed = false),
    offline: () => (fail = true),
    lookupFail: () => (lookupFail = true),
    revision: () => revision++,
  };
}
test("cached policy expires, failures pause, revision removes prior permissions", async () => {
  const s = setup();
  let p = await s.policy.get();
  assert.equal(p.allowed, true);
  await s.policy.get();
  assert.equal(s.requests.length, 1);
  assert.equal(
    s.policy.forTime(await s.policy.permits(p), 1000000).permit,
    "signed",
  );
  assert.equal(s.policy.forTime(await s.policy.permits(p), 999999), undefined);
  s.advance(21000);
  s.revision();
  p = await s.policy.get();
  assert.equal(s.session.collectionPermits.length, 1);
  assert.equal(p.revision, 2);
  assert.equal(JSON.stringify(s.session).includes("secret"), false);
  s.advance(21000);
  s.offline();
  assert.equal((await s.policy.get()).allowed, false);
  assert.equal(s.local.collectionStatus, "policy_unavailable");
});
test("LAN lookup sends no credentials to ipify and fails closed", async () => {
  const s = setup();
  s.device();
  const p = await s.policy.get();
  assert.equal(p.allowed, true);
  assert.equal(s.requests.length, 3);
  const lookup = s.requests[1];
  assert.equal(lookup.url, "https://api64.ipify.org?format=json");
  assert.equal(lookup.opts.body, undefined);
  assert.equal(lookup.opts.headers, undefined);
  assert.equal(lookup.opts.credentials, "omit");
  s.lookupFail();
  s.policy.invalidate();
  assert.equal((await s.policy.get()).allowed, false);
});
test("deny policy never creates collection permission", async () => {
  const s = setup();
  s.block();
  const p = await s.policy.get();
  assert.equal(p.allowed, false);
  assert.equal((await s.policy.permits(p)).length, 0);
});
