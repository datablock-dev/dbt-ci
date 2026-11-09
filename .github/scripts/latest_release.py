"""
Print the newest release of a package on PyPI, pre-releases included.

The scheduled pre-release workflow pins dbt to this exact version. `pip install --pre`
would also pull pre-releases of every other dependency, which tests those packages
rather than dbt; an exact pin allows a pre-release for the named package only.

    python .github/scripts/latest_release.py dbt-core --below 2   # newest 1.x, e.g. 1.13.0rc1
    python .github/scripts/latest_release.py dbt-core --from 2    # newest 2.x, e.g. 2.0.0rc10

Bounds compare release numbers, so 2.0.0rc10 counts as 2.0.0: below 2, not from 2.
"""

import argparse
import json
import urllib.request

from packaging.version import InvalidVersion, Version


def newest(
    versions: list[str], below: Version | None = None, start: Version | None = None
) -> Version:
    """Return the highest valid version, pre-releases included, within the given bounds."""
    parsed = []
    for raw in versions:
        try:
            version = Version(raw)
        except InvalidVersion:
            continue
        release = Version(version.base_version)
        if version.is_devrelease:
            continue
        if (below is not None and release >= below) or (start is not None and release < start):
            continue
        parsed.append(version)
    if not parsed:
        raise SystemExit("No matching release found.")
    return max(parsed)


def released_versions(package: str) -> list[str]:
    """Return the versions of a package on PyPI that still have files to install."""
    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=30) as response:
        releases = json.load(response)["releases"]
    return [
        version
        for version, files in releases.items()
        if files and not all(file.get("yanked") for file in files)
    ]


def main() -> None:
    """Print the newest release of the package given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("package")
    parser.add_argument("--below", type=Version, help="only versions lower than this")
    parser.add_argument("--from", dest="start", type=Version, help="only this version or later")
    args = parser.parse_args()
    print(newest(released_versions(args.package), args.below, args.start))


if __name__ == "__main__":
    main()
