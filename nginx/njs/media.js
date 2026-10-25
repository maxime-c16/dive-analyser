import crypto from 'crypto';

function verify(r) {
    const secret = r.variables.media_signing_secret;
    const expires = r.args.expires;
    const sig = r.args.sig;
    if (!/^[0-9a-f]{64}$/.test(secret || '') || typeof expires !== 'string' ||
        !/^[0-9]{10}$/.test(expires) || typeof sig !== 'string' || !/^[0-9a-f]{64}$/.test(sig)) return '0';
    if (Number(expires) <= Date.now() / 1000 || Number(expires) > Date.now() / 1000 + 4500) return '0';
    if (r.method !== 'GET' && r.method !== 'HEAD') return '0';
    const uri = r.variables.uri;
    if (uri.split('/').some(x => x === '.' || x === '..')) return '0';
    const expected = crypto.createHmac('sha256', secret).update(expires + '\n' + uri).digest('hex');
    let diff = 0;
    for (let i = 0; i < 64; i++) diff |= expected.charCodeAt(i) ^ sig.charCodeAt(i);
    return diff === 0 ? '1' : '0';
}
function cacheAge(r) {
    return String(Math.max(0, Math.min(3600, Number(r.args.expires) - Math.ceil(Date.now() / 1000))));
}
export default { verify, cacheAge };
