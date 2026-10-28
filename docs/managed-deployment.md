# Managed deployment: ChromeOS, Windows and macOS

This release adds **automatic browser-profile enrollment**, not manual enrollment
codes or per-device setup. Google Admin force-installs the extension and supplies
its configuration. When Chrome can supply a Google identity silently, the extension
automatically gets its own short-lived backend credential and renews it.

**Rollout gate:** Google force-installation and managed configuration do not, by
themselves, guarantee silent OAuth consent. This implementation always calls
`chrome.identity.getAuthToken({interactive:false, account:{id:primaryProfileId}})`.
If Google requires consent/sign-in, it stops collection and reports the error;
it never prompts students and never treats a reported email as verified. Test a
fresh managed profile on each platform before broad deployment. If those pilots
require individual consent, this OAuth enrollment path does **not** satisfy a
zero-interaction rollout in that tenant; stop and resolve centrally provisioned
authorization or evaluate enterprise attestation, rather than ask every user to
enroll. Chrome's [identity API](https://developer.chrome.com/docs/extensions/reference/api/identity)
documents this non-interactive failure behavior.

No real OAuth client, Web Store listing, school credentials or Admin Console
configuration was created by the code change. Google verification is simulated in
automated tests; real tenant/platform behavior still requires the pilot below.

## Distribution choice

For GitHub-hosted CRX releases instead of Web Store distribution, follow
[GitHub deployment](github-deployment.md). Obtain the extension ID from your own
signing key, then configure the OAuth client for that ID. The enrollment, backend,
and pilot requirements below still apply. The Web Store steps in section 1 and
store-based force-install choice in section 3 are only for Web Store distribution.

## 1. One-time publisher setup, starting from an unpacked test extension

1. Prepare the backend behind HTTPS, reachable by the managed devices. The existing
   `http://localhost:8000` development path remains available only in development
   mode. For a LAN backend, provide a trusted HTTPS hostname/certificate; the IP
   allowlist's Device lookup mode still works with it.
2. Create a draft upload to obtain a stable Chrome Web Store extension ID:

   ```sh
   python3 scripts/package_extension.py --draft \
     --api-origin https://history.your-school.example \
     --output dist/history-agent-draft.zip
   ```

   Upload it as a **draft** store item. Do not deploy this draft: it intentionally
   has no OAuth client and cannot perform verified enrollment. Follow Google's
   publisher registration and store requirements; keep the same store item/ID for
   subsequent versions.
3. In Google Cloud, configure the OAuth consent application and create an OAuth
   client of type **Chrome Extension**, bound to that exact extension ID. This is
   separate from the dashboard's **Web application** OAuth client. Request only
   `openid` and `https://www.googleapis.com/auth/userinfo.email`.
4. Build the enrollment-capable package, replacing the example client ID:

   ```sh
   python3 scripts/package_extension.py \
     --oauth-client-id YOUR_CHROME_EXTENSION_CLIENT_ID.apps.googleusercontent.com \
     --api-origin https://history.your-school.example \
     --output dist/history-agent-0.4.0.zip
   ```

   Use the exact full client ID Google supplies (normally begins with digits).
   The builder requires a valid-looking client ID, strips localhost permissions,
   includes only extension source files, and refuses to overwrite an existing ZIP.
   No OAuth client secret or shared enrollment token belongs in the extension.
5. Upload this package to the **same** store item, complete the required listing,
   privacy/disclosure and distribution settings, and make it available to the
   pilot organization. Publishing/distribution is a separate administrator action.

The Chrome OAuth client is a manifest setting; Chrome does not accept a replacement
client ID from `storage.managed`. It is set once per publisher package, not per
device. One publisher package/client can serve multiple schools, with each school
configuring its own backend and authorization allowlist. Internal OAuth audience
and private distribution restrict which organizations can use the app; choose
external/distribution settings appropriate to the actual intended schools. Google
approval/verification requirements still apply.

For a known set of schools, repeat `--api-origin` for each HTTPS backend. For a
shared package that must accept arbitrary school backend hostnames, replace those
arguments with `--managed-https`. That grants HTTPS host access broadly and should
be an intentional publisher choice. The backend URL still comes from managed
configuration. Google documents the ID/client relationship in its
[extension OAuth tutorial](https://developer.chrome.com/docs/extensions/how-to/integrate/oauth).

## 2. Configure each school's backend once

Keep dashboard `AUTH_MODE=google` and its existing administrator settings for
production. Separately set:

```dotenv
EXTENSION_AUTH_MODE=enrolled
EXTENSION_GOOGLE_CLIENT_IDS=YOUR_CHROME_EXTENSION_CLIENT_ID.apps.googleusercontent.com
EXTENSION_WORKSPACE_DOMAINS=nfv.k12.ia.us
```

Each school supplies its own exact Workspace hosted domains. Multiple values are
comma separated. The enrolled mode rejects **all** `X-Extension-Token` credentials,
including a previously valid shared development token. No automatic downgrade is
provided. A blank allowlist prevents enrollment. Rebuild/recreate the backend:
`docker compose up --build -d`.

Local development remains explicitly `EXTENSION_AUTH_MODE=development`; Compose
preserves that default for the existing testing environment. Running the backend
outside Compose defaults to enrolled mode. The existing .env is not rewritten.

Enrollment verifies the opaque Google access token with Google's token-information
endpoint, checks audience, authorized party, expiry and identity scopes, then
fetches OpenID UserInfo and checks subject consistency, verified email and `hd`
against the server allowlist. A token for the dashboard or another app is rejected.
The claimed Chrome primary account must match Google's subject. A user/email or
device mismatch on any subsequent history, activity or policy upload is rejected.
The [Google token documentation](https://docs.cloud.google.com/docs/authentication/token-types#user_access_tokens)
describes the token fields. Enrollment/renewal needs outbound HTTPS to
`oauth2.googleapis.com` and `openidconnect.googleapis.com`; ingestion does not
call Google on every sample. Provision Google API capacity for the expected fleet.

## 3. Google Admin Console configuration

1. Use a **pilot organizational unit** containing managed Chromebook users and
   managed Chrome profiles on Windows and macOS. Browser management and a signed-in
   primary Chrome profile are required on desktops; signing into a Google website
   alone is not sufficient. Guest/incognito/unsigned profiles do not enroll.
2. In **Devices → Chrome → Apps & extensions → Users & browsers**, add the published
   extension by its stable ID and set **Force install** for that OU. Google documents
   [force installation](https://support.google.com/chrome/a/answer/6306504).
3. In the extension's managed policy configuration, use
   [`google-admin-policy.example.json`](google-admin-policy.example.json), replacing
   its example backend URL. The values are:
   - `apiUrl`: school's HTTPS backend URL.
   - `enrollmentMode`: `enrolled`.
   - `initialHistoryDays`: 1–365, normally 7. Schedule/IP restrictions still prevent
     unverified historical backfill.
   - `reconciliationMinutes`: 1–60, normally 5.
4. Configure the extension OAuth application's access in Workspace API controls
   for the intended pilot users. Do not confuse trusting an app with proof that
   every fresh profile has a silent OAuth grant; test that separately. Do not put
   administrator emails, fallback user emails, shared tokens, service-account keys
   or OAuth secrets in this policy.
5. Configure retention, schedules, and allowed public IPs centrally in the app's
   Settings page. These server-enforced rules remain deployment-wide. Google Admin
   configures deployment/connection; it does not override backend collection rules.

Managed enrolled mode ignores local server overrides, fallback email and shared
extension tokens. Options becomes diagnostic/read-only for those fields. Removing
managed enrollment configuration pauses collection instead of silently reverting
to an old local token. An explicit centrally managed development mode is only for
isolated testing. Chrome's [managed storage](https://developer.chrome.com/docs/extensions/reference/api/storage)
provides the configuration; no user has to open Options to enroll.

## 4. Pilot acceptance checks before expanding the OU

- On **fresh** managed profiles on Chromebook, Windows and Mac, confirm the
  extension arrives automatically and managed values appear in `chrome://policy`.
- Without opening any login/enrollment dialog, confirm the device appears in
  Settings → Collection health as **verified**, with the correct Google email.
- If enrollment is missing, inspect Extension Options for the setup error. Failed
  initial enrollment cannot safely appear as a verified device in the dashboard.
  Resolve policy/OAuth setup centrally; no manual enrollment-code workaround exists.
- Confirm background renewal after an hour, worker/browser restarts, and temporary
  network loss. Setup failures use a 60–120 second retry backoff that survives worker
  restarts. Nothing is collected until authentication and collection policy succeed.
- Check a normal allowed browsing session, then outside hours/on an unapproved IP.
  The existing schedule/IP tests remain necessary on real school networks.
- Revoke a **test** enrollment in Settings. Its next upload/check-in must be denied;
  re-enrollment with the same device key must remain blocked. Existing history is
  preserved, and the audit log records the action.
- Try an account outside the allowed Workspace domain and a mismatched payload
  email/device. Neither may upload data. Switching the primary account never
  reuses the previous account's credential; a device-key ownership conflict pauses
  enrollment rather than relabeling history.

## Credentials, revocation and limits

Each browser profile holds a random credential locally, scoped to one backend,
user and device key. The backend stores only its SHA-256 hash. Its lifetime is at
most one hour and never exceeds the verified Google token's expiry. Renewal repeats
Google verification and replaces the old credential; expired/revoked credentials
cannot use any sync endpoint. An in-flight request authorized before revocation
may finish. Credentials are never included in health responses, Options status,
audit details or managed policy. Chrome local storage is restricted to trusted
extension contexts; this is not a hardware-keystore guarantee.

Enrollment and renewal write audit events atomically with credential changes.
Settings → Collection health shows legacy, verified, expired and revoked states.
Revocation requires an administrator and a confirmation in the UI, and blocks
renewal for that enrollment. There is intentionally no automatic un-revoke path.

A “device” here is a **Chrome profile installation**, not an attested hardware asset.
Clearing all extension storage can create a new device key and a new enrollment
for an otherwise allowed Google account. A reported `installType=admin` is a
client-side requirement, not server-verifiable hardware/management attestation.
For permanent physical-device bans or stronger proof of managed status, enterprise
attestation is still required. To stop a user or deployment centrally, remove its
access/force-install assignment in Google Admin as appropriate and revoke existing
credentials; Google/account revocation can take until the short credential expires
to be reflected. Removing a Workspace domain from the backend allowlist blocks
its enrolled requests immediately.

Existing development history is preserved, but enrollment does not retroactively
prove the identity associated with previously collected rows. Reusing an existing
device key with a different verified user is rejected. A recycled email tied to a
different Google subject, or a subject whose email changed, requires administrator
review rather than automatic reassignment.

## Automated verification

Backend tests use disposable PostgreSQL and mocked Google responses to cover
credential hashing/rotation/expiry, user/device binding, audience/domain checks,
legacy-token rejection and revocation. Extension tests cover non-interactive primary
account selection, concurrent enrollment, renewal, consent failure/backoff and
account changes. The package builder can be tested with a fixture client ID in a
temporary directory; that does not produce a deployable Google identity.

No live Chromebook or managed Windows/Mac Google OAuth pilot has been completed
in this development environment. Complete section 4 before claiming a fully
zero-interaction rollout.
