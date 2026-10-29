# NFVCSD deployment preparation

Extension ID: `aekomeheakpbnjbkokddheginepaojdn`.

The signing key is stored outside the repository at
`~/.config/browser-history-monitor/signing.pem` with owner-only permissions.
Back it up securely. Never commit or share it in chat. The files here contain only
public configuration, not the private key.

Version 0.4.0 and its update feed are published, and the package includes the
configured Google OAuth client. Begin with a pilot device. Verified collection
still requires a reachable HTTPS backend configured for enrolled authentication.

- The update URL in `com.google.Chrome.plist` targets this repository’s GitHub
  Pages feed. Merge its `ExtensionSettings` entry into existing Jamf
  Chrome settings; preserve the Eaglercraft blocker and other entries.
- The separate `com.google.Chrome.extensions.aekomeheakpbnjbkokddheginepaojdn.plist`
  configures this extension in Jamf. Confirm the backend HTTPS address before use.
- `google-admin-policy.json` provides the equivalent Google Admin managed values.
- `extension-id.txt` is the public stable ID for the Google OAuth client and
  GitHub `EXTENSION_ID` variable.

See `../docs/github-deployment.md` for the deployment and fresh-profile pilot.

## Jamf XML payload files

- `jamf-chrome-install.xml`: preference domain `com.google.Chrome`. Merge its
  extension entry into any existing `ExtensionSettings` policy to preserve the blocker.
- `jamf-history-settings.xml`: preference domain
  `com.google.Chrome.extensions.aekomeheakpbnjbkokddheginepaojdn`.

These are custom-settings plist XML payloads, not full `.mobileconfig` profiles.
The API address is `https://history.nfv.k12.ia.us`; change it if your deployed
backend differs, and ensure the signed extension permits the chosen origin.
