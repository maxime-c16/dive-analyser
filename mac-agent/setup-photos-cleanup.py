#!/usr/bin/env python3
"""Install the opt-in Photos UI helper and provision its Keychain credential.

Run as the media Mac's logged-in user, never sudo. This does not enable cleanup.
"""
import argparse
import getpass
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'store-password', 'reset-unlock', 'status'])
    parser.add_argument('--state-dir', required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.getuid() == 0:
        raise SystemExit('Run as the logged-in media Mac user')
    from src.photos_automation import PhotosAutomation, keychain_password
    automation = PhotosAutomation(args.state_dir)
    if args.action == 'install':
        automation.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        automation.root.chmod(0o700)
        location = str(automation.root.resolve())
        if any(c in location for c in ['"', '\\', '\n', '\r']):
            raise SystemExit('Unsupported state directory')
        source = (Path(__file__).parent / 'automation/confirm.applescript').read_text().replace('__STATE_DIR__', location)
        with tempfile.TemporaryDirectory(dir=automation.root) as temporary:
            candidate = Path(temporary) / 'confirm.applescript'
            candidate.write_text(source)
            subprocess.run(['/usr/bin/osacompile', '-o', str(Path(temporary) / 'confirm.scpt'), str(candidate)], check=True)
            candidate.chmod(0o600)
            os.replace(candidate, automation.root / 'confirm.applescript')
        info = automation.app / 'Contents/Info.plist'
        existing = plistlib.loads(info.read_bytes()) if info.exists() else {}
        if existing.get('CFBundleVersion') != '2':
            with tempfile.TemporaryDirectory() as temporary:
                script = Path(temporary) / 'launcher.applescript'
                script.write_text('return run script POSIX file "' + location + '/confirm.applescript"\n')
                subprocess.run(['/usr/bin/osacompile', '-o', str(automation.app), str(script)], check=True)
            properties = plistlib.loads(info.read_bytes())
            properties.update(CFBundleIdentifier='com.diveanalyzer.photos-cleanup-ui', CFBundleVersion='2',
                              NSAppleEventsUsageDescription='Confirm only verified post-ingest Photos cleanup requests.',
                              LSUIElement=True)
            info.write_bytes(plistlib.dumps(properties))
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(automation.app)], check=True)
        print('Installed. Grant this app Automation (System Events) and Accessibility in System Settings.')
        print('Cleanup remains off until configured. See docs/PHOTOS_CLEANUP_PERMISSIONS.md.')
    elif args.action == 'store-password':
        secret = getpass.getpass('Mac account password: ') if sys.stdin.isatty() else sys.stdin.read(4096)
        if not secret or '\x00' in secret or len(secret.encode()) > 63:
            raise SystemExit('Unsupported credential')
        keychain_password(secret.encode())
        secret = None
        print('Stored in the current user Keychain; no config file contains the password.')
    elif args.action == 'reset-unlock':
        automation.blocked.unlink(missing_ok=True)
        print('Unlock latch reset. The next eligible clip may attempt one unlock.')
    else:
        import json
        print(json.dumps({'helper_installed': automation.app.is_dir(), 'unlock_blocked': automation.blocked.exists()}))


if __name__ == '__main__':
    main()
