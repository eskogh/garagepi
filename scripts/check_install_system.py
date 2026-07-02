#!/usr/bin/env python3
import platform
import sys


SUPPORTED_MACHINES = {"armv6l", "armv7l", "armv8l", "aarch64"}


def main() -> int:
    system = platform.system().lower()
    machine = platform.machine().lower()
    version = sys.version_info

    if version < (3, 9):
        print(
            "GaragePi requires Python 3.9 or newer "
            f"(found {version.major}.{version.minor}).",
            file=sys.stderr,
        )
        return 1

    if system != "linux":
        print(
            f"GaragePi production install requires Linux on Raspberry Pi hardware "
            f"(found {platform.system()} {platform.machine()}).",
            file=sys.stderr,
        )
        print("Use `make dev` for development installs on this machine.", file=sys.stderr)
        return 1

    if machine not in SUPPORTED_MACHINES:
        print(
            f"GaragePi production install requires Raspberry Pi ARM hardware "
            f"(found {platform.machine()}).",
            file=sys.stderr,
        )
        print("Use `make dev` for development installs on this machine.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
