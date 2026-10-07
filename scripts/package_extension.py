"""Build one publisher package for Google Admin deployment; never embed secrets."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile, ZIP_DEFLATED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument(
        "--draft",
        action="store_true",
        help="Create initial store draft to obtain a stable extension ID; cannot enroll",
    )
    identity.add_argument(
        "--oauth-client-id",
        help="Chrome Extension OAuth client ID registered to the stable store ID",
    )
    hosts = parser.add_mutually_exclusive_group(required=True)
    hosts.add_argument(
        "--api-origin",
        action="append",
        help="Allowed HTTPS backend origin; repeat for multiple schools",
    )
    hosts.add_argument(
        "--managed-https",
        action="store_true",
        help="Allow any HTTPS backend selected through managed configuration",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.draft and not re.fullmatch(
        r"[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", args.oauth_client_id
    ):
        parser.error("Expected a Google Chrome Extension OAuth client ID")
    origins = ["https://*/*"] if args.managed_https else []
    for origin in args.api_origin or []:
        value = urlsplit(origin)
        if (
            value.scheme != "https"
            or not value.hostname
            or value.username
            or value.password
            or value.query
            or value.fragment
            or value.path not in ("", "/")
            or "*" in origin
        ):
            parser.error(
                "API origins must be HTTPS origins without credentials, paths or wildcards"
            )
        origins.append(f"https://{value.netloc}/*")
    source = Path(__file__).resolve().parents[1] / "extension"
    manifest = json.loads((source / "manifest.json").read_text())
    if not args.draft:
        manifest["oauth2"] = {
            "client_id": args.oauth_client_id,
            "scopes": ["openid", "https://www.googleapis.com/auth/userinfo.email"],
        }
    manifest["host_permissions"] = sorted(set(origins + ["https://api64.ipify.org/*"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create avoids overwriting a reviewed publisher artifact.
    with ZipFile(args.output, "x", ZIP_DEFLATED) as archive:
        for path in sorted(source.iterdir()):
            if path.is_file() and path.suffix in {".js", ".json", ".html"}:
                content = (
                    json.dumps(manifest, indent=2) + "\n"
                    if path.name == "manifest.json"
                    else path.read_text()
                )
                archive.writestr(path.name, content)
    print(f"Created {args.output}")


if __name__ == "__main__":
    main()
