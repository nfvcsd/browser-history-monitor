# Pre-publication review — October 28, 2026

Reviewed all eight existing commits reachable from the repository's branches and
158 historical file blobs, plus the new deployment changes staged for publication.
The remote had one branch (`master`) and no additional tags. GitHub returned zero
releases, Actions runs/artifacts, and issues (including pull requests).

Checks included private-key and common provider-token patterns, exact comparisons
against current local environment credential values without printing those values,
and review of historical credential assignments, email addresses, and file names.
No production credentials, database files, exported browsing records, or screenshots
were found in tracked history. Credential strings found in tests and `.env.example`
are fixtures/placeholders. School branding, the backend hostname, repository URLs,
Git author identity, and the extension's public signing ID are public configuration.

Local `.env`, private signing key, generated distributions, and dependencies are
excluded from publication. Local store screenshots show real dashboard data and
are explicitly ignored; they were never tracked. The generic generated store icon
contains no personal information and may be published. Finder metadata was removed
from the current tree and ignored; the historical blob contained folder-view
metadata and project file names, not credential values or browsing records.

This is a source/history exposure review, not a penetration test or a guarantee
that every possible secret format is detectable. Repeat review before publishing
new data, screenshots, generated artifacts, or configuration.
