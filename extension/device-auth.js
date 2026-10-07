/* Credentials belong to one backend and primary Chrome profile. Never show them in Options. */
const DeviceAuth = (() => {
  let pending;
  let retryAfter = 0;
  let lastError = "Enrollment is waiting for administrator configuration";
  let generation = 0;
  let cachedScope;
  function invalidate() {
    generation++;
    retryAfter = 0;
    cachedScope = undefined;
    void chrome.storage.session.remove("enrollmentBackoff");
  }
  async function context() {
    const config = await getConfig();
    const deviceKey = await getDeviceKey();
    if (config.enrollmentMode !== "enrolled") {
      if (!config.extensionToken)
        throw new Error("Development extension token is not configured");
      return {
        config,
        deviceKey,
        identity: await getIdentity(config),
        headers: { "X-Extension-Token": config.extensionToken },
        authKey: config.extensionToken,
      };
    }
    const base = new URL(config.apiUrl);
    if (
      base.protocol !== "https:" ||
      base.username ||
      base.password ||
      base.search ||
      base.hash
    )
      throw new Error("Managed enrollment requires an HTTPS backend URL");
    const profile = await chrome.identity.getProfileUserInfo({
      accountStatus: "ANY",
    });
    if (!profile?.id || !profile?.email)
      throw new Error(
        "Sign into the managed Chrome profile; no primary account is available",
      );
    const scope = JSON.stringify([base.href.replace(/\/$/, ""), profile.id]);
    if (cachedScope !== scope) {
      retryAfter = 0;
      cachedScope = scope;
    }
    const { deviceEnrollment } =
      await chrome.storage.local.get("deviceEnrollment");
    if (
      deviceEnrollment?.scope === scope &&
      deviceEnrollment.deviceKey === deviceKey &&
      Date.parse(deviceEnrollment.expires_at) > Date.now() + 5 * 60 * 1000
    ) {
      return result(config, deviceKey, deviceEnrollment);
    }
    const { enrollmentBackoff } =
      await chrome.storage.session.get("enrollmentBackoff");
    if (enrollmentBackoff?.scope === scope) {
      retryAfter = enrollmentBackoff.until;
      lastError = enrollmentBackoff.error;
    }
    if (Date.now() < retryAfter) throw new Error(lastError);
    if (pending?.scope === scope) return pending.promise;
    const stamp = generation;
    const promise = (async () => {
      try {
        const self = await chrome.management.getSelf();
        if (self.installType !== "admin")
          throw new Error(
            "Verified enrollment requires Google Admin force installation",
          );
        if (!chrome.runtime.getManifest().oauth2?.client_id)
          throw new Error(
            "Publisher must configure the extension OAuth client before deployment",
          );
        // Target the primary profile explicitly. Never prompt or pick a web account.
        let oauth = await chrome.identity.getAuthToken({
          interactive: false,
          account: { id: profile.id },
        });
        if (!oauth?.token)
          throw new Error(
            "Silent Google identity unavailable; administrator approval is required",
          );
        const enroll = (token) =>
          fetch(`${base.href.replace(/\/$/, "")}/api/v1/enrollment`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
              device_key: deviceKey,
              profile_subject: profile.id,
              device_name: navigator.userAgent,
              extension_version: chrome.runtime.getManifest().version,
            }),
            signal: AbortSignal.timeout(30000),
            cache: "no-store",
          });
        let response = await enroll(oauth.token);
        if (response.status === 401) {
          await chrome.identity.removeCachedAuthToken({ token: oauth.token });
          oauth = await chrome.identity.getAuthToken({
            interactive: false,
            account: { id: profile.id },
          });
          if (!oauth?.token)
            throw new Error(
              "Silent Google identity unavailable; contact your administrator",
            );
          response = await enroll(oauth.token);
        }
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(
            typeof body.detail === "string"
              ? body.detail
              : `Enrollment failed (${response.status})`,
          );
        }
        const enrollment = await response.json();
        const current = await chrome.identity.getProfileUserInfo({
          accountStatus: "ANY",
        });
        if (
          stamp !== generation ||
          current.id !== profile.id ||
          enrollment.subject !== profile.id ||
          !enrollment.device_token ||
          !enrollment.email ||
          !(Date.parse(enrollment.expires_at) > Date.now())
        )
          throw new Error(
            "Chrome profile changed during enrollment; collection paused",
          );
        // Force a fresh Google token at the next renewal if Chrome returned one
        // close to expiry; do not keep rotating short-lived device credentials.
        if (Date.parse(enrollment.expires_at) < Date.now() + 10 * 60 * 1000)
          await chrome.identity.removeCachedAuthToken({ token: oauth.token });
        const saved = { ...enrollment, scope, deviceKey };
        await chrome.storage.local.set({
          deviceEnrollment: saved,
          enrollmentStatus: "Verified",
          enrollmentEmail: enrollment.email,
          enrollmentExpiresAt: enrollment.expires_at,
        });
        retryAfter = 0;
        await chrome.storage.session.remove("enrollmentBackoff");
        return result(config, deviceKey, saved);
      } catch (error) {
        // Backoff prevents an OU rollout from repeatedly hammering Google on setup errors.
        lastError = String(error?.message || error);
        retryAfter = Date.now() + 60000 + Math.floor(Math.random() * 60000);
        await chrome.storage.session.set({
          enrollmentBackoff: { scope, until: retryAfter, error: lastError },
        });
        await chrome.storage.local.set({ enrollmentStatus: lastError });
        throw new Error(lastError);
      }
    })();
    pending = { scope, promise };
    try {
      return await promise;
    } finally {
      if (pending?.promise === promise) pending = undefined;
    }
  }
  function result(config, deviceKey, enrollment) {
    return {
      config,
      deviceKey,
      identity: { email: enrollment.email, displayName: null },
      headers: { "X-Device-Token": enrollment.device_token },
      authKey: enrollment.device_token,
    };
  }
  async function rejected(response, ctx) {
    if (
      ctx.config.enrollmentMode !== "enrolled" ||
      ![401, 403].includes(response.status)
    )
      return;
    const { deviceEnrollment } =
      await chrome.storage.local.get("deviceEnrollment");
    if (deviceEnrollment?.device_token !== ctx.authKey) return;
    await chrome.storage.local.remove("deviceEnrollment");
    invalidate();
    CollectionPolicy.invalidate();
    await chrome.storage.local.set({
      enrollmentStatus:
        response.status === 403
          ? "Enrollment blocked or revoked; contact administrator"
          : "Credential expired; automatic re-enrollment pending",
    });
  }
  async function checkedContext() {
    try {
      return await context();
    } catch (error) {
      await chrome.storage.local.set({
        enrollmentStatus: String(error?.message || error),
        collectionStatus: "enrollment_unavailable",
      });
      throw error;
    }
  }
  return { context: checkedContext, invalidate, rejected };
})();
if (typeof module !== "undefined") module.exports = DeviceAuth;
