/* Short-lived authorization is bound to server, user, device and policy revision. */
const CollectionPolicy = (() => {
  let cached;
  let cachedToken;
  let pending;
  let generation = 0;
  function invalidate() {
    generation++;
    cached = undefined;
  }
  async function get(force = false) {
    const ctx = await DeviceAuth.context();
    const { config, identity, deviceKey } = ctx;
    const scope = JSON.stringify([
      config.apiUrl.replace(/\/$/, ""),
      identity.email.trim().toLowerCase(),
      deviceKey,
    ]);
    if (
      !force &&
      cachedToken === ctx.authKey &&
      cached?.scope === scope &&
      Date.now() < cached.refreshAt &&
      Date.now() < Date.parse(cached.valid_until)
    )
      return cached;
    if (pending?.scope === scope) return pending.promise;
    const stamp = generation;
    const promise = (async () => {
      try {
        const payload = {
          user_email: identity.email,
          device_key: deviceKey,
          device_name: navigator.userAgent,
          extension_version: chrome.runtime.getManifest().version,
        };
        async function check(body) {
          const response = await fetch(
            `${config.apiUrl.replace(/\/$/, "")}/api/v1/sync/policy`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                ...ctx.headers,
              },
              body: JSON.stringify(body),
              signal: AbortSignal.timeout(10000),
              cache: "no-store",
            },
          );
          if (!response.ok) {
            await DeviceAuth.rejected(response, ctx);
            throw new Error(
              `Collection policy unavailable (${response.status})`,
            );
          }
          return response.json();
        }
        let result = await check(payload);
        if (result.ip_enabled && result.ip_source === "device") {
          // Only this request goes to ipify: never send identity, browsing data or credentials.
          let address = null;
          try {
            const response = await fetch(
              "https://api64.ipify.org?format=json",
              {
                signal: AbortSignal.timeout(5000),
                cache: "no-store",
                credentials: "omit",
              },
            );
            if (response.ok) address = (await response.json()).ip;
          } catch {
            /* Server will pause collection if lookup failed. */
          }
          result = await check({ ...payload, public_ip: address });
        }
        if (stamp !== generation)
          throw new Error("Network or configuration changed; checking again");
        cachedToken = ctx.authKey;
        cached = { ...result, scope, refreshAt: Date.now() + 20000 };
        const { collectionPermits = [] } =
          await chrome.storage.session.get("collectionPermits");
        const recent = collectionPermits.filter(
          (item) =>
            item.scope === scope &&
            item.revision === result.revision &&
            Date.parse(item.valid_until) > Date.now() - 20 * 60 * 1000,
        );
        if (result.allowed) recent.push(cached);
        await chrome.storage.session.set({
          collectionPermits: recent.slice(-100),
        });
        await chrome.storage.local.set({
          collectionStatus: result.reason,
          lastPolicyError: "",
          collectionPublicIp: result.source_ip,
          lastPolicyCheck: new Date().toISOString(),
        });
        return cached;
      } catch (error) {
        cached = undefined;
        await chrome.storage.local.set({
          collectionStatus: "policy_unavailable",
          lastPolicyError: String(error?.message || error),
        });
        return {
          allowed: false,
          restricted: true,
          reason: "policy_unavailable",
        };
      }
    })();
    pending = { scope, promise };
    try {
      return await promise;
    } finally {
      if (pending?.promise === promise) pending = undefined;
    }
  }
  async function permits(policy) {
    const { collectionPermits = [] } =
      await chrome.storage.session.get("collectionPermits");
    return collectionPermits.filter(
      (item) =>
        item.scope === policy.scope && item.revision === policy.revision,
    );
  }
  function forTime(permits, start, end = start) {
    return permits.find(
      (item) =>
        Date.parse(item.valid_from) <= start &&
        start < Date.parse(item.valid_until) &&
        end <= Date.parse(item.valid_until),
    );
  }
  return { get, permits, forTime, invalidate };
})();
if (typeof module !== "undefined") module.exports = CollectionPolicy;
