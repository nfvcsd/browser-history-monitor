# GitHub-hosted extension deployment

This matches [nfvcsd/eaglercraft-blocker](https://github.com/nfvcsd/eaglercraft-blocker):
GitHub Actions signs a CRX3, GitHub Releases hosts it, and GitHub Pages hosts
`updates.xml`. Google Admin or device management force-installs the extension by
its ID and update URL. No Chrome Web Store listing is needed for this managed
self-hosting path. The FastAPI backend, PostgreSQL, dashboard, and collected browsing
data remain on your server; GitHub only hosts public extension distribution files.

The code is prepared locally. No signing identity, OAuth client, GitHub secret,
Pages deployment, release, or device policy has been created by this change.

## One-time setup

1. Use a **separate signing key for this extension**. Never use the blocker key.
   Store it outside the repository and back it up securely. This command refuses
   to overwrite an existing file:

   ```sh
   mkdir -p "$HOME/.config/browser-history-monitor"
   (umask 077; set -C; openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 > "$HOME/.config/browser-history-monitor/signing.pem")
   python3 scripts/build_self_hosted.py \
     --key "$HOME/.config/browser-history-monitor/signing.pem" --identity-only
   ```

   Keep the printed 32-character extension ID. Use this same key for every update.
   Chrome expects PKCS#8 PEM RSA keys; `genpkey` creates that format. Do not regenerate
   the key to resolve a build problem. A different key means a different extension.
2. Create a Google OAuth **Chrome Extension** client bound to that ID. It is
   separate from the dashboard Web application client. Keep the existing enrollment
   scopes (`openid`, `https://www.googleapis.com/auth/userinfo.email`). Configure
   Workspace OAuth app access for the pilot. Silent OAuth on a self-hosted,
   policy-installed extension must be tested; successful CRX installation alone
   does not validate enrollment. See [enrollment and pilot requirements](managed-deployment.md).
3. Configure the backend with `EXTENSION_AUTH_MODE=enrolled`, the extension OAuth
   client in `EXTENSION_GOOGLE_CLIENT_IDS`, and the school domains in
   `EXTENSION_WORKSPACE_DOMAINS`. Keep the existing dashboard auth configuration.
   The backend must be reachable over trusted HTTPS from the pilot devices.
4. In `nfvcsd/browser-history-monitor`, create the GitHub environment
   **extension-release**. Restrict it to the default branch and add a release
   reviewer where your GitHub plan supports it. Set these environment values:

   | Type | Name | Value |
   | --- | --- | --- |
   | Secret | `CRX_PRIVATE_KEY_B64` | Base64 encoding of this extension's signing PEM |
   | Variable | `EXTENSION_ID` | ID printed in step 1 |
   | Variable | `EXTENSION_OAUTH_CLIENT_ID` | Full Chrome Extension OAuth client ID |
   | Variable | `EXTENSION_API_ORIGIN` | Backend origin, e.g. `https://history.nfv.k12.ia.us` |

   Transfer the key directly into the secret through GitHub's UI or CLI; do not
   paste it into chat, commit it, or print it in a workflow log. It is never bundled
   in release assets. OAuth client IDs and extension IDs are public identifiers.
5. Enable **Settings → Pages → Source: GitHub Actions**. Both the Pages feed and
   Release asset must be anonymously downloadable. Private Release assets that
   require GitHub authentication cannot serve Chrome updates. Do not make a private
   source repository public without reviewing it; use a dedicated public distribution
   repository or separate HTTPS hosting if private source is required. The supplied
   workflow assumes releases and Pages are served from this same repository.
6. Commit/push the prepared files, then run **Signed extension release** from the
   default branch. It tests the extension and packager, checks the signing ID,
   creates `extension-v<VERSION>`, verifies the anonymous CRX download matches the
   build, and only then publishes the Pages feed. No release occurs on ordinary
   pushes. Existing release tags/assets are not overwritten.

For the default repository, the stable update URL will be:

```
https://nfvcsd.github.io/browser-history-monitor/updates.xml
```

The versioned asset will be:

```
https://github.com/nfvcsd/browser-history-monitor/releases/download/extension-v0.4.0/browser-history-agent.crx
```

These are intended endpoints, not a claim that this change has published them.

## Google Admin force installation and configuration

In **Devices → Chrome → Apps & extensions → Users & browsers**, select a pilot OU,
add an extension by ID, choose **From a custom URL**, enter the signing ID and the
Pages `updates.xml` URL, and set **Force install**. Keep updates pointed at that
installation URL or the same packaged update URL. Do not use a GitHub HTML file
view or a direct CRX download as the update manifest URL.

Use [google-admin-policy.example.json](google-admin-policy.example.json) for the
extension's managed configuration, replacing the API URL. `enrollmentMode` remains
`enrolled`. Do not put shared development tokens or fallback emails in the policy.
Schedules, public-IP rules, and retention continue to be controlled by the backend.

For Windows/Mac, ensure the devices meet Chrome's enterprise requirements for
external force installs. Signing into a school website alone is insufficient.
Windows requires an eligible managed environment (AD/Entra join or Chrome Enterprise
Core enrollment); macOS supports MDM management such as Jamf or eligible Chrome
Enterprise management. Validate effective policy at `chrome://policy` on each
platform. ChromeOS deployment uses the managed user/device environment.

## Jamf-managed Macs

Merge the following entry into your existing **com.google.Chrome** custom-settings
`ExtensionSettings` dictionary. Replace the ID; preserve other extension entries
(including the Eaglercraft blocker). Do not replace the entire existing policy
with this fragment if it already manages other extensions.

```xml
<key>ExtensionSettings</key>
<dict>
  <key>REPLACE_WITH_HISTORY_EXTENSION_ID</key>
  <dict>
    <key>installation_mode</key><string>force_installed</string>
    <key>update_url</key><string>https://nfvcsd.github.io/browser-history-monitor/updates.xml</string>
    <key>override_update_url</key><true/>
  </dict>
</dict>
```

In a separate custom-settings payload for
`com.google.Chrome.extensions.REPLACE_WITH_HISTORY_EXTENSION_ID`, supply managed
configuration with plain plist values (not the Google Admin JSON `Value` wrappers):

```xml
<dict>
  <key>apiUrl</key><string>https://history.nfv.k12.ia.us</string>
  <key>enrollmentMode</key><string>enrolled</string>
  <key>initialHistoryDays</key><integer>7</integer>
  <key>reconciliationMinutes</key><integer>5</integer>
</dict>
```

Choose one authoritative management source for these settings to avoid conflicts.
The configured HTTPS hostname must match the packaged API origin. Existing
schedule/IP restrictions still govern collection and historical backfill.

## Local build and verification

```sh
python3 scripts/build_self_hosted.py \
  --chrome '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  --key "$HOME/.config/browser-history-monitor/signing.pem" \
  --expected-id YOUR_32_CHARACTER_EXTENSION_ID \
  --oauth-client-id YOUR_FULL_EXTENSION_OAUTH_CLIENT_ID \
  --api-origin https://history.nfv.k12.ia.us
```

The builder writes `dist/self-hosted/`: CRX, checksum, public extension ID, and a
`pages/` folder containing only the feed. It refuses an existing output directory;
use `--output` with a new path for another build. It injects the public key and
update URL into the packaged manifest while preserving the unpacked development
manifest. It reuses the existing ZIP builder to avoid shipping tests or secrets.
For another school, pass `--repository OWNER/REPO` and that school's API origin;
use its own signing identity, OAuth client, and backend allowlists. Multiple
`--api-origin` options or explicit `--managed-https` are supported for locally built
multi-school packages; the supplied workflow deliberately uses a single origin.

Run packaging tests with real Chrome:

```sh
CHROME_BIN='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  python3 -m unittest discover -s scripts/tests -v
node --test extension/tests/*.test.cjs
```

Tests generate and delete temporary fixture keys. They do not create a production
identity or prove live Google OAuth or managed force-install behavior.

## Pilot and updates

1. Verify the feed and CRX download anonymously, including redirects. Confirm Chrome
   force-installs the expected ID/version on one device per platform. GitHub Release
   redirects must be reachable on the school network; an HTTP download check is not
   a substitute for an actual managed Chrome installation.
2. On a fresh managed, signed-in Chrome profile, confirm silent enrollment and the
   correct verified identity in Settings. Test collection rules, credential renewal,
   and revocation. If Google requires consent, collection stops; there is no silent
   fallback to unverified development credentials. Resolve centrally before rollout.
3. Increment `extension/manifest.json`'s version, keep the same key, commit/push and
   run the workflow again. Verify the installed extension updates **without reinstalling**.
4. Only then expand the pilot. If migrating from the Web Store/unpacked extension,
   a new signing ID is a separate installation with separate local storage and device
   enrollment. Remove the old force-install assignment during the controlled migration
   to avoid double collection; existing backend history remains intact.

If asset verification or Pages deployment fails after creating a release, the
previous feed remains active. Do not overwrite the released CRX. Fix the issue and
publish a higher extension version; this workflow intentionally fails if the tag
already exists. Chrome generally does not downgrade installed extensions; a code
rollback should be packaged with a higher version and the same signing key.

If GitHub CRX delivery fails in the pilot, host the exact signed CRX on an anonymously
reachable HTTPS static server with `application/x-chrome-extension` and no login.
Update the feed's `codebase` only after verifying the asset, keeping the signing key,
ID and stable update URL. Never disable Chrome protections to make installation work.

## References

- [Chrome supported distribution methods](https://developer.chrome.com/docs/extensions/how-to/distribute)
- [Self-hosting and update manifest format](https://developer.chrome.com/docs/extensions/how-to/distribute/host-on-linux)
- [Google Admin extension configuration](https://support.google.com/chrome/a/answer/6177447)
- [Enterprise force-install requirements](https://chromeenterprise.google/policies/extension-install-forcelist/)
- [Chrome identity API and non-interactive authorization](https://developer.chrome.com/docs/extensions/reference/api/identity)
