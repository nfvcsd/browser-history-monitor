---
paths:
  - "extension/**"
  - "scripts/**"
---
# Chrome extension and packaging

Preserve Manifest V3 worker restart behavior, bounded durable queues, stable sample
IDs, and original user/device/backend ownership of queued data. Do not reassign
old samples when account or managed configuration changes.

Managed enrolled mode must use centrally supplied configuration and verified
primary-profile identity. Keep OAuth non-interactive, honor failure backoff, and
pause collection if authentication or collection policy is unavailable. Removing
managed enrollment configuration must not silently restore local fallback identity.
Profile verification is not hardware attestation; force installation alone does not
guarantee silent Google consent. State these limits accurately.

Collection schedules and IP controls remain server-enforced. Preserve restrictions
on historical backfill, permit expiry, idle/focus sampling, and incognito handling.
Do not add unnecessary permissions or transmit history to third-party services.

Run `node --test extension/tests/*.test.cjs` from the repository root. For packaging
changes, also run `python3 -m unittest discover -s scripts/tests -v`; set `CHROME_BIN`
to a real Chrome executable to exercise CRX3 packing. Fixture keys are disposable;
never substitute them for the production signing identity.

Use the existing ZIP/CRX builders. Preserve the stable production signing key and
extension ID. Do not generate a replacement key to fix a failed build. Bump the
manifest version for a new installed release and preserve the update URL. A different
ID is a separate installation and can cause duplicate collection if both remain active.
