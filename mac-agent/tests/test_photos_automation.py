"""Safety boundaries for unattended cleanup; no real Mac/credentials."""
import asyncio
import json
import sys
from types import SimpleNamespace as NS

import pytest

from src.photos_automation import PhotosAutomation, password_field


@pytest.mark.parametrize('observations', [[], [('Enter Password', (.45,.08,.1,.02))],
    [('Other user', (.45,.13,.1,.02)), ('Enter Password', (.45,.08,.1,.02))],
    [('Media', (.45,.13,.1,.02)), ('Enter Password', (.45,.08,.1,.02)), ('Enter Password', (.45,.08,.1,.02))],
    [('Media', (.45,.13,.1,.02)), ('Enter Password', (.1,.8,.1,.02))]])
def test_password_never_sent_to_unverified_screen(observations):
    with pytest.raises(RuntimeError, match='field_unverified'):
        password_field(observations, 2880, 1800, 'Media')


def test_field_is_bound_to_name_and_converted_to_pixel_coordinates():
    assert password_field([('Media', (.45,.13,.1,.02)), ('Enter Password', (.45,.08,.1,.02))],
                          2880,1800,'Media') == (1440,1638)


@pytest.mark.asyncio
async def test_failed_login_latches_before_any_key_and_never_retries(tmp_path, monkeypatch):
    import src.photos_automation as module
    automation = PhotosAutomation(tmp_path)
    automation.root.mkdir(parents=True)
    sent = []
    async def drain(): pass
    async def screenshot(): return 'frame'
    def press(key):
        assert automation.blocked.exists()
        sent.append(key)
    client = NS(screenshot=screenshot, drain=drain, mouse=NS(move=lambda *_:None,click=lambda:None),
                keyboard=NS(press=press))
    monkeypatch.setitem(sys.modules, 'asyncvnc', NS(key_codes={'a':1}))
    monkeypatch.setattr(module,'locate_password',lambda _: (100,100))
    monkeypatch.setattr(module,'session_state',lambda: (True,1))
    real_sleep = asyncio.sleep
    async def no_wait(_): await real_sleep(0)
    monkeypatch.setattr(module.asyncio,'sleep',no_wait)
    with pytest.raises(RuntimeError,match='unlock_failed'):
        await automation.unlock(client,'a')
    assert sent == ['a','Return'] and automation.blocked.exists()
    with pytest.raises(RuntimeError,match='unlock_blocked'):
        await automation.run([('uuid',123)])
    assert sent == ['a','Return']


@pytest.mark.asyncio
async def test_other_viewer_refuses_before_reading_keychain(tmp_path,monkeypatch):
    import src.photos_automation as module
    automation=PhotosAutomation(tmp_path)
    automation.app.mkdir(parents=True)
    monkeypatch.setitem(sys.modules,'asyncvnc',NS())
    monkeypatch.setattr(module,'session_state',lambda: (True,1))
    monkeypatch.setattr(module,'keychain_password',lambda: pytest.fail('must not read credential'))
    with pytest.raises(RuntimeError,match='operator_connected'):
        await automation.run([('uuid',123)])


def test_ui_reply_requires_matching_nonce_and_exact_result(tmp_path,monkeypatch):
    import src.photos_automation as module
    automation=PhotosAutomation(tmp_path)
    automation.root.mkdir(parents=True)
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**kw:None)
    (automation.root/'result.json').write_text(json.dumps({'nonce':'stale','result':'clicked'}))
    with pytest.raises(RuntimeError,match='confirmation_refused'):
        automation.ui('confirm','fresh',123)


def test_ui_timeout_terminates_only_our_nonce_bound_applet(tmp_path,monkeypatch):
    import src.photos_automation as module
    automation=PhotosAutomation(tmp_path)
    automation.root.mkdir(parents=True)
    record=automation.root/'ui-process.json'
    killed=[]
    monkeypatch.setattr(module.os,'kill',lambda pid,signal:killed.append(pid))
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**kw:NS(stdout=str(automation.app/'Contents/MacOS/applet')))
    record.write_text(json.dumps({'nonce':'old','pid':123}))
    automation.stop_ui('new')
    assert not killed
    record.write_text(json.dumps({'nonce':'new','pid':123}))
    automation.stop_ui('new')
    assert killed==[123]
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**kw:NS(stdout='/usr/bin/unrelated'))
    automation.stop_ui('new')
    assert killed==[123]


@pytest.mark.asyncio
@pytest.mark.parametrize('offered',[b'\x01',b'\x02',b'\x01\x02'])
async def test_vnc_refuses_non_apple_authentication(offered):
    from src.photos_automation import AppleAuthReader
    reader=asyncio.StreamReader()
    reader.feed_data(bytes([len(offered)])+offered)
    guarded=AppleAuthReader(reader)
    await guarded.readexactly(1)
    with pytest.raises(RuntimeError,match='native_auth_required'):
        await guarded.readexactly(len(offered))


@pytest.mark.asyncio
async def test_vnc_accepts_native_apple_auth_without_altering_protocol():
    from src.photos_automation import AppleAuthReader
    reader=asyncio.StreamReader()
    reader.feed_data(b'\x02\x21\x01payload')
    guarded=AppleAuthReader(reader)
    assert await guarded.readexactly(1)==b'\x02'
    assert await guarded.readexactly(2)==b'\x21\x01'
    assert await guarded.readexactly(7)==b'payload'
