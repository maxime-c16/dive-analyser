"""Optional real nginx+njs integration; no production connections."""
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.parse import urlsplit

import httpx
import pytest
from app.config import get_settings
from app.services.signed_media import signed_url


def test_nginx_hmac_without_python(tmp_path, monkeypatch):
    binary = os.getenv('LOT2_NGINX_BINARY')
    module = os.getenv('LOT2_NGINX_MODULE')
    if not binary or not module:
        pytest.skip('local nginx+njs not configured')
    root = tmp_path / 'cache'
    root.mkdir()
    path = root / 'test.jpg'
    path.write_bytes(b'0123456789')
    monkeypatch.setattr(get_settings(), 'media_cache_root', str(root))
    monkeypatch.setenv('MEDIA_SIGNING_SECRET', 'a'*64)
    monkeypatch.setenv('MEDIA_SIGNED_URLS_ENABLED', 'true')
    listener = socket.socket()
    listener.bind(('127.0.0.1',0))
    port = listener.getsockname()[1]
    listener.close()
    repo = Path(__file__).resolve().parents[2]
    lan = (repo / 'nginx/conf.d/default.conf').read_text()
    block = lan[lan.index('    # Signed capability'):lan.index('    location /internal-media-cache/')]
    block = block.replace('/app/media-cache/', str(root)+'/')
    conf = tmp_path / 'nginx.conf'
    conf.write_text(f'''load_module {module};
error_log {tmp_path}/error.log;
pid {tmp_path}/nginx.pid;
events {{}}
http {{
 access_log off;
 map $host $media_signing_secret {{ default "{'a'*64}"; }}
 js_import media from {repo}/nginx/njs/media.js;
 js_set $media_signature_valid media.verify;
 js_set $media_cache_age media.cacheAge;
 server {{ listen 127.0.0.1:{port}; {block} }}
}}
''')
    subprocess.run([binary, '-p', str(tmp_path), '-c', str(conf), '-t'], check=True, capture_output=True)
    process = subprocess.Popen([binary, '-p', str(tmp_path), '-c', str(conf), '-g', 'daemon off;'])
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(100):
            try:
                httpx.get(base, timeout=.1)
                break
            except httpx.ConnectError:
                time.sleep(.02)
        url = signed_url(path, 'b'*64)
        response = httpx.get(base+url)
        assert response.status_code == 200 and response.content == b'0123456789'
        assert response.headers['cache-control'] == 'private, max-age=3600, immutable'
        near_expiry = httpx.get(base+signed_url(path, 'b'*64, now=time.time()-3600))
        assert near_expiry.status_code == 200
        assert 'max-age=3600' not in near_expiry.headers['cache-control']
        assert httpx.head(base+url).headers['content-length'] == '10'
        response = httpx.get(base+url, headers={'Range':'bytes=2-4'})
        assert response.status_code == 206 and response.content == b'234'
        assert httpx.get(base+url, headers={'If-None-Match':httpx.get(base+url).headers['etag']}).status_code == 304
        assert httpx.get(base+url.replace('b'*64,'c'*64)).status_code == 403
        assert httpx.get(base+url.replace('test.jpg','another.jpg')).status_code == 403
        assert httpx.get(base+url+'&sig=bad').status_code == 403
        assert httpx.get(base+url.split('?')[0]).status_code == 403
        assert httpx.get(base+signed_url(path, 'b'*64, now=time.time()-5000)).status_code == 403
        assert httpx.post(base+url).status_code == 403
        # Signature is correct but symlink target must still be denied.
        external = tmp_path / 'private.jpg'
        external.write_bytes(b'secret')
        (root / 'link.jpg').symlink_to(external)
        # Mint URI for its lexical path by changing a valid signed payload.
        import hmac, hashlib
        from urllib.parse import parse_qs
        uri = urlsplit(url).path.replace('test.jpg','link.jpg')
        exp = parse_qs(urlsplit(url).query)['expires'][0]
        sig = hmac.new(b'a'*64, f'{exp}\n{uri}'.encode(), hashlib.sha256).hexdigest()
        assert httpx.get(base+f'{uri}?expires={exp}&sig={sig}').status_code == 403
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_both_deployment_configurations_parse(tmp_path):
    binary = os.getenv('LOT2_NGINX_BINARY')
    module = os.getenv('LOT2_NGINX_MODULE')
    if not binary or not module:
        pytest.skip('local nginx+njs not configured')
    repo = Path(__file__).resolve().parents[2]
    (tmp_path / 'logs').mkdir()
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', str(tmp_path/'server.key'), '-out', str(tmp_path/'server.crt'),
        '-days', '1', '-subj', '/CN=localhost'], check=True, capture_output=True)
    # Adapt ONLY machine paths, DNS and non-portable epoll. Server blocks,
    # signing template, HMAC script and all nginx directives remain real.
    for main, server in [('nginx/nginx.conf','nginx/conf.d/default.conf'),
                         ('ops/tailscale/main.conf','ops/tailscale/nginx.conf')]:
        conf_dir = tmp_path / ('lan' if main.startswith('nginx/') else 'funnel')
        conf_dir.mkdir()
        server_text = (repo/server).read_text()
        for upstream in ('backend','frontend','adminer'):
            server_text = server_text.replace(f'{upstream}:', '127.0.0.1:')
        for upstream, port in [('backend',8000),('frontend',8001),('adminer',8080)]:
            server_text = server_text.replace(f'http://{upstream}', f'http://127.0.0.1:{port}')
        server_text = server_text.replace('/etc/nginx/ssl/', str(tmp_path)+'/')
        server_text = server_text.replace('/var/log/nginx/', str(tmp_path)+'/')
        (conf_dir/'default.conf').write_text(server_text)
        template = (repo/'nginx/media-signing.conf.template').read_text().replace('${MEDIA_SIGNING_SECRET}', 'a'*64)
        template = template.replace('/etc/nginx/njs/media.js',str(repo/'nginx/njs/media.js'))
        (conf_dir/'media-signing.conf').write_text(template)
        main_text = (repo/main).read_text().replace('load_module modules/ngx_http_js_module.so;',f'load_module {module};')
        main_text = main_text.replace('user nginx;','').replace('    use epoll;','')
        main_text = main_text.replace('/var/log/nginx/', str(tmp_path)+'/').replace('/var/run/nginx.pid',str(tmp_path/'nginx.pid'))
        main_text = main_text.replace('include /etc/nginx/mime.types;', 'types { image/jpeg jpg; image/webp webp; }')
        main_text = main_text.replace('/etc/nginx/conf.d/*.conf',str(conf_dir/'*.conf'))
        (conf_dir/'main').write_text(main_text)
        result = subprocess.run([binary,'-p',str(tmp_path),'-c',str(conf_dir/'main'),'-t'], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
