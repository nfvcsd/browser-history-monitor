const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
function setup() {
  let now = 1000000,
    subject = "primary-id",
    consent = false,
    revoked = false,
    requests = 0,
    mode = "enrolled";
  const local = {},
    session = {},
    authCalls = [];
  const context = {
    module: { exports: {} },
    URL,
    Date: class extends Date {
      static now() {
        return now;
      }
    },
    Math,
    AbortSignal,
    navigator: { userAgent: "test" },
    getConfig: async () => ({
      apiUrl: "https://school.example",
      enrollmentMode: mode,
    }),
    getDeviceKey: async () => "device-key",
    CollectionPolicy: { invalidate: () => {} },
    chrome: {
      storage: {
        session: {
          get: async (key) => ({ [key]: structuredClone(session[key]) }),
          set: async (data) => Object.assign(session, structuredClone(data)),
          remove: async (key) => delete session[key],
        },
        local: {
          get: async (key) => ({ [key]: structuredClone(local[key]) }),
          set: async (data) => Object.assign(local, structuredClone(data)),
          remove: async (key) => delete local[key],
        },
      },
      identity: {
        getProfileUserInfo: async () => ({
          id: subject,
          email: "alice@example.com",
        }),
        getAuthToken: async (options) => {
          authCalls.push(options);
          if (consent) throw Error("OAuth consent required");
          return { token: "google-token" };
        },
        removeCachedAuthToken: async () => {},
      },
      management: { getSelf: async () => ({ installType: "admin" }) },
      runtime: {
        getManifest: () => ({
          oauth2: { client_id: "configured-client" },
          version: "0.4.0",
        }),
      },
    },
    fetch: async () => {
      requests++;
      return revoked
        ? {
            ok: false,
            status: 403,
            json: async () => ({
              detail: "Enrollment revoked by administrator",
            }),
          }
        : {
            ok: true,
            status: 200,
            json: async () => ({
              device_token: "credential-" + requests,
              email: "alice@example.com",
              subject,
              expires_at: new Date(now + 3600000).toISOString(),
            }),
          };
    },
  };
  vm.runInNewContext(
    fs.readFileSync(require.resolve("../device-auth.js"), "utf8"),
    context,
  );
  return {
    auth: context.module.exports,
    local,
    authCalls,
    count: () => requests,
    advance: (ms) => (now += ms),
    consent: () => (consent = true),
    revoke: () => (revoked = true),
    subject: (value) => (subject = value),
  };
}
test("automatic enrollment uses primary account with no prompts; caches and renews", async () => {
  const s = setup();
  const [a, b] = await Promise.all([s.auth.context(), s.auth.context()]);
  assert.equal(a.authKey, b.authKey);
  assert.equal(s.count(), 1);
  assert.equal(s.authCalls[0].interactive, false);
  assert.equal(s.authCalls[0].account.id, "primary-id");
  assert.equal(a.headers["X-Device-Token"], "credential-1");
  await s.auth.context();
  assert.equal(s.count(), 1);
  s.advance(3400000);
  await s.auth.context();
  assert.equal(s.count(), 2);
});
test("consent failure pauses with backoff rather than prompting or falling back", async () => {
  const s = setup();
  s.consent();
  await assert.rejects(s.auth.context(), /consent/);
  await assert.rejects(s.auth.context(), /consent/);
  assert.equal(s.authCalls.length, 1);
  assert.equal(s.count(), 0);
  assert.equal(s.local.deviceEnrollment, undefined);
});
test("revocation invalidates credential and renewal stays blocked", async () => {
  const s = setup();
  const ctx = await s.auth.context();
  s.revoke();
  await s.auth.rejected({ status: 403 }, ctx);
  assert.equal(s.local.deviceEnrollment, undefined);
  await assert.rejects(s.auth.context(), /revoked/);
  assert.equal(s.local.deviceEnrollment, undefined);
});
test("profile change never reuses previous account credential", async () => {
  const s = setup();
  const old = await s.auth.context();
  s.subject("second-id");
  s.auth.invalidate();
  const fresh = await s.auth.context();
  assert.notEqual(fresh.authKey, old.authKey);
  assert.equal(s.authCalls[1].account.id, "second-id");
});
