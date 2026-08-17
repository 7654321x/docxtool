#!/usr/bin/env python3
"""Generate strong random secrets for local or production .env files."""

import secrets


def main() -> None:
    print("ADMIN_TOKEN=" + secrets.token_urlsafe(48))
    print("PROXY_SECRET=" + secrets.token_urlsafe(48))


if __name__ == "__main__":
    main()
