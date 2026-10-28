# NFVCSD deployment preparation

Extension ID: `aekomeheakpbnjbkokddheginepaojdn`.

The signing key is stored outside the repository at
`~/.config/browser-history-monitor/signing.pem` with owner-only permissions.
Back it up securely. Never commit or share it in chat. The files here contain only
public configuration, not the private key.

Deployment is pending the first signed GitHub release and a Google Chrome
Extension OAuth client bound to this ID. Do not deploy these files yet.

- The update URL in `com.google.Chrome.plist` targets this repository’s GitHub
  Pages feed. Merge its `ExtensionSettings` entry into existing Jamf
  Chrome settings; preserve the Eaglercraft blocker and other entries.
- The separate `com.google.Chrome.extensions.aekomeheakpbnjbkokddheginepaojdn.plist`
  configures this extension in Jamf. Confirm the backend HTTPS address before use.
- `google-admin-policy.json` provides the equivalent Google Admin managed values.
- `extension-id.txt` is the public stable ID for the Google OAuth client and
  GitHub `EXTENSION_ID` variable.

See `../docs/github-deployment.md` for the deployment and fresh-profile pilot.
