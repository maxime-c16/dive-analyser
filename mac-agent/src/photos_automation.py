"""Opt-in local VNC session for a single, verified PhotoKit deletion.

No remote VNC, clipboard, saved screenshots, command-line secrets or retries.
The signed UI helper has its own Automation/Accessibility grants.
"""
import asyncio
import getpass
from contextlib import asynccontextmanager
import io
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import uuid

SERVICE = "com.diveanalyzer.photos-cleanup"


def session_state():
    import Quartz
    session = dict(Quartz.CGSessionCopyCurrentDictionary() or {})
    owner = pwd.getpwuid(os.stat('/dev/console').st_uid).pw_name
    result = subprocess.run(['/usr/sbin/netstat', '-an', '-p', 'tcp'],
                            capture_output=True, text=True, check=True, timeout=10)
    viewers = sum(len(p := line.split()) >= 6 and p[3].endswith('.5900') and p[5] == 'ESTABLISHED'
                  for line in result.stdout.splitlines())
    if session.get('kCGSessionLoginDoneKey') is not True or owner != getpass.getuser():
        raise RuntimeError('cleanup_console_session_unavailable')
    return bool(session.get('CGSSessionScreenIsLocked', False)), viewers


def keychain_password(value=None):
    """Use Security.framework directly; never put credentials in argv/env."""
    import Security as S
    from Foundation import NSData
    query = {S.kSecClass: S.kSecClassGenericPassword, S.kSecAttrService: SERVICE,
             S.kSecAttrAccount: getpass.getuser()}
    if value is not None:
        data = NSData.dataWithBytes_length_(value, len(value))
        status = S.SecItemUpdate(query, {S.kSecValueData: data})
        if status == S.errSecItemNotFound:
            status, _ = S.SecItemAdd(query | {S.kSecValueData: data}, None)
        if status != S.errSecSuccess:
            raise RuntimeError('cleanup_keychain_write_refused')
        return
    status, data = S.SecItemCopyMatching(query | {S.kSecReturnData: True, S.kSecMatchLimit: S.kSecMatchLimitOne}, None)
    if status != S.errSecSuccess or data is None:
        raise RuntimeError('cleanup_keychain_unavailable')
    return bytes(data).decode('utf-8')


def password_field(observations, width, height, display_name):
    """Find exactly one empty password field below the console user's name.

    Vision returns normalized, bottom-left rectangles. Refuse translated or
    unexpected screens rather than sending a password to an unverified field.
    """
    names = [box for text, box in observations if text.strip().casefold() == display_name.casefold()]
    fields = [box for text, box in observations if text.strip().casefold() in {'enter password', 'saisir le mot de passe'}]
    if len(names) != 1 or len(fields) != 1:
        raise RuntimeError('cleanup_unlock_field_unverified')
    nx, ny, nw, nh = names[0]
    x, y, w, h = fields[0]
    if not (0 < ny - y < .12 and abs((nx + nw / 2) - (x + w / 2)) < .1
            and .25 < x + w / 2 < .75 and y < .3):
        raise RuntimeError('cleanup_unlock_field_unverified')
    return round((x + w / 2) * width), round((1 - y - h / 2) * height)


def locate_password(frame):
    import Vision
    from Foundation import NSData
    from PIL import Image
    buffer = io.BytesIO()
    height, width = frame.shape[:2]
    left, top, right, bottom = int(width * .3), int(height * .75), int(width * .7), int(height * .96)
    Image.fromarray(frame[top:bottom, left:right]).resize(((right-left)*2, (bottom-top)*2)).save(buffer, format='PNG')
    data = buffer.getvalue()
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(["en-US", "fr-FR"])
    request.setUsesLanguageCorrection_(False)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
        NSData.dataWithBytes_length_(data, len(data)), {})
    success, _ = handler.performRequests_error_([request], None)
    if not success:
        raise RuntimeError('cleanup_unlock_field_unverified')
    observations = []
    for result in request.results() or []:
        candidates = result.topCandidates_(1)
        if candidates:
            box = result.boundingBox()
            observations.append((str(candidates[0].string()), ((left + box.origin.x * (right-left)) / width,
                (height-bottom + box.origin.y * (bottom-top)) / height,
                box.size.width * (right-left) / width, box.size.height * (bottom-top) / height)))
    user = pwd.getpwuid(os.getuid())
    return password_field(observations, frame.shape[1], frame.shape[0], user.pw_gecos.split(',')[0] or user.pw_name)


class AppleAuthReader:
    """Refuse asyncvnc's no-auth/DES fallbacks before it sends credentials."""
    def __init__(self, reader):
        self.reader, self.packet = reader, 0

    def __getattr__(self, name):
        return getattr(self.reader, name)

    async def readexactly(self, size):
        value = await self.reader.readexactly(size)
        self.packet += 1
        # After the RFB greeting, Client.create reads count then auth types.
        if self.packet == 2 and 33 not in value:
            raise RuntimeError('cleanup_native_auth_required')
        return value


@asynccontextmanager
async def native_connection(password):
    import asyncvnc
    reader, writer = await asyncio.open_connection('127.0.0.1', 5900)
    try:
        client = await asyncvnc.Client.create(AppleAuthReader(reader), writer, getpass.getuser(), password)
        yield client
    finally:
        # asyncvnc.connect only closes after successful Client.create. Close
        # handshake failures too; never leave a half-open viewer behind.
        writer.close()
        await writer.wait_closed()


class PhotosAutomation:
    def __init__(self, state_dir):
        self.root = Path(state_dir).expanduser() / 'photos_cleanup' / 'automation'
        self.app = self.root / 'DiveSensei Photos Cleanup.app'
        self.blocked = self.root / 'unlock-blocked'

    def ui(self, action, nonce, pid=0):
        from .photos_cleanup import atomic_json
        # A single worker lock owns this directory. A nonce binds every response.
        atomic_json(self.root / 'request.json', {'nonce': nonce, 'pid': pid, 'action': action})
        try:
            subprocess.run(['/usr/bin/open', '-W', '-n', str(self.app)],
                           capture_output=True, check=True, timeout=15)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            # Killing `open` alone does not stop the app it launched. Disarm
            # only our nonce-bound UI process, before it can act late.
            self.stop_ui(nonce)
            raise RuntimeError('cleanup_ui_timeout') from None
        response = json.loads((self.root / 'result.json').read_text())
        if action in {'inspect', 'confirm', 'cancel', 'lock'}:
            atomic_json(self.root / f'last-{action}.json', response)
        if response.get('nonce') != nonce or response.get('result') != {'inspect': 'clear', 'confirm': 'clicked', 'cancel': 'cancelled', 'lock': 'locked'}[action]:
            raise RuntimeError('cleanup_confirmation_refused')

    def stop_ui(self, nonce):
        try:
            record = json.loads((self.root / 'ui-process.json').read_text())
            pid = record['pid']
            if record.get('nonce') != nonce or type(pid) is not int or pid < 2:
                return
            command = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'command='],
                                     capture_output=True, text=True, check=True, timeout=3).stdout
            if command.strip().startswith(str(self.app / 'Contents/MacOS/applet')):
                import signal
                os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass

    async def unlock(self, client, password):
        import asyncvnc
        if not password or len(password.encode()) > 63 or any(c not in asyncvnc.key_codes for c in password):
            raise RuntimeError('cleanup_credential_unsupported')
        # Image exists only in memory, before any credential keystroke.
        x, y = locate_password(await asyncio.wait_for(client.screenshot(), 15))
        if session_state() != (True, 1):
            raise RuntimeError('cleanup_session_changed')
        client.mouse.move(x, y)
        client.mouse.click()
        await client.drain()
        await asyncio.sleep(.5)
        # Latch BEFORE typing. A crash or failed login requires an explicit reset.
        self.blocked.write_text('One unlock was attempted; inspect session before reset.\n')
        for char in password:
            client.keyboard.press(char)
            await client.drain()
            await asyncio.sleep(.12)
        await asyncio.sleep(1)
        client.keyboard.press('Return')
        await client.drain()
        for _ in range(10):
            await asyncio.sleep(.5)
            locked, viewers = session_state()
            if viewers != 1:
                raise RuntimeError('cleanup_session_changed')
            if not locked:
                self.blocked.unlink()
                return
        raise RuntimeError('cleanup_unlock_failed')

    async def run(self, assets, authorize=None):
        import asyncvnc
        if len(assets) != 1:
            raise RuntimeError('cleanup_automation_requires_single_asset')
        if self.blocked.exists():
            raise RuntimeError('cleanup_unlock_blocked')
        if not self.app.is_dir():
            raise RuntimeError('cleanup_ui_helper_missing')
        initially_locked, viewers = session_state()
        if not initially_locked or viewers:
            raise RuntimeError('cleanup_operator_connected')
        # Never capture exceptions from libraries that might include credentials.
        password = keychain_password()
        nonce = uuid.uuid4().hex
        helper = None
        phase = 'authentication'
        try:
            self.blocked.write_text('Authentication attempt started; reset only after inspection.\n')
            async with asyncio.timeout(100):
                async with native_connection(password) as client:
                    try:
                        phase = 'unlock'
                        if session_state()[0]:
                            await self.unlock(client, password)
                        password = None
                        self.blocked.unlink(missing_ok=True)
                        if session_state() != (False, 1):
                            raise RuntimeError('cleanup_session_changed')
                        phase = 'ui_preflight'
                        await asyncio.to_thread(self.ui, 'inspect', nonce)
                        phase = 'revalidation'
                        if authorize is not None:
                            await asyncio.to_thread(authorize)
                        phase = 'native_start'
                        helper = subprocess.Popen(
                            [sys.executable, '-m', 'src.photos_cleanup', '--automated-batch', nonce],
                            cwd=Path(__file__).resolve().parent.parent, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
                            env=dict(os.environ, DIVE_PHOTOS_AUTOMATION_DIR=str(self.root)))
                        helper.stdin.write(json.dumps(assets))
                        helper.stdin.close()
                        # Wait for this helper's armed marker, not arbitrary dialog polling.
                        marker = self.root / f'{nonce}.armed'
                        for _ in range(50):
                            if marker.exists():
                                break
                            if helper.poll() is not None:
                                raise RuntimeError('cleanup_native_helper_failed')
                            await asyncio.sleep(.1)
                        else:
                            raise RuntimeError('cleanup_native_helper_not_armed')
                        # Native window may appear after performChanges returns.
                        await asyncio.sleep(1)
                        if session_state() != (False, 1):
                            raise RuntimeError('cleanup_session_changed')
                        phase = 'confirmation'
                        await asyncio.to_thread(self.ui, 'confirm', nonce, helper.pid)
                        phase = 'native_completion'
                        code = await asyncio.to_thread(helper.wait, 45)
                        if code:
                            raise RuntimeError('cleanup_native_helper_failed')
                    finally:
                        if helper is not None and helper.poll() is None:
                            try:
                                if session_state() == (False, 1):
                                    await asyncio.to_thread(self.ui, 'cancel', nonce, helper.pid)
                            except Exception:
                                pass
                            helper.terminate()
                            try:
                                await asyncio.to_thread(helper.wait, 3)
                            except subprocess.TimeoutExpired:
                                helper.kill()
                                await asyncio.to_thread(helper.wait)
                        if initially_locked and session_state() == (False, 1):
                            await asyncio.to_thread(self.ui, 'lock', nonce)
                            for _ in range(10):
                                if session_state()[0]:
                                    break
                                await asyncio.sleep(.5)
                        if not session_state()[0]:
                            raise RuntimeError('cleanup_relock_failed')
        except Exception:
            if helper is not None:
                self.blocked.write_text('Native/UI cleanup failed; inspect outstanding dialogs before reset.\n')
            # No raw exception, server message, password or screenshot in logs.
            raise RuntimeError('cleanup_automation_deferred:' + phase) from None
        finally:
            password = None
            if helper is not None and helper.poll() is None:
                helper.terminate()
                try:
                    helper.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    helper.kill()
                    helper.wait()
            for name in ['request.json', 'ui-process.json', f'{nonce}.armed']:
                (self.root / name).unlink(missing_ok=True)

    def remove_many(self, assets, authorize=None):
        asyncio.run(self.run(assets, authorize))
