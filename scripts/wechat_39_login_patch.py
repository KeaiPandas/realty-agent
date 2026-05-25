"""Patch a running WeChat 3.9.x login screen to bypass "version too low".

This follows the same high-level idea as the referenced project: attach to the
running `WeChat.exe` process and replace in-memory `x64` markers with `x32`
before confirming the QR-code login on the phone.
"""

from __future__ import annotations

import sys

import pymem
import pymem.exception


def patch_wechat() -> bool:
    try:
        pm = pymem.Pymem("WeChat.exe")
    except pymem.exception.ProcessNotFound:
        print("[-] WeChat.exe is not running. Open WeChat and stay on the login page first.")
        return False

    print(f"[+] Attached to WeChat.exe (PID: {pm.process_id})")

    matches = list(pm.pattern_scan_all(b"x64", return_multiple=True) or [])
    print(f"[*] Found {len(matches)} in-memory occurrences of 'x64'")

    patched = 0
    for addr in matches:
        try:
            pm.write_bytes(addr, b"x32", 3)
            patched += 1
        except Exception:
            continue

    print(f"[OK] Patched {patched} occurrences from 'x64' to 'x32'")
    print()
    print("Next steps:")
    print("1. Scan the QR code on your phone.")
    print("2. Do not confirm on the phone yet.")
    print("3. Scan again to refresh the page.")
    print("4. Then confirm login on the phone.")
    return patched > 0


def main() -> int:
    print("=== WeChat 3.9.x Login Patch ===")
    print("0. Open WeChat and keep it on the login / QR screen.")
    print("1. Press Enter here to apply the patch.")
    print("2. Then follow the scan -> rescan -> confirm sequence.")
    print()
    input("Press Enter when ready...")
    return 0 if patch_wechat() else 1


if __name__ == "__main__":
    raise SystemExit(main())
