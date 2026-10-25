const { chromium } = require(process.env.PW_PATH);
const fs = require('fs'); const path = require('path');
const dir = process.argv[2]; const sizes = ['2034x3616','1080x1920','720x1280','480x640'];
(async () => {
  const browser = await chromium.launch({ channel: 'chrome' });
  const out = {};
  for (const throttle of [1, 4]) {
    const page = await browser.newPage();
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: throttle });
    await page.route('http://probe.local/**', r => { const p = path.basename(new URL(r.request().url()).pathname); if (p === 'index.html') return r.fulfill({ body: '<html><body></body></html>', contentType: 'text/html' }); const f = path.join(dir, p);
      r.fulfill({ body: fs.readFileSync(f), contentType: 'image/jpeg', headers: { 'cache-control': 'no-store' } }); });
    await page.goto('http://probe.local/index.html');

    for (const s of sizes) {
      const r = await page.evaluate(async (s) => {
        const res = [];
        for (let round = 0; round < 3; round++) {
          const imgs = Array.from({ length: 15 }, (_, i) => { const im = new Image(); im.src = `http://probe.local/p_${s}.jpg?r=${round}-${i}`; return im; });
          await Promise.all(imgs.map(im => new Promise(ok => im.complete ? ok() : im.onload = ok)));
          const t0 = performance.now(); await Promise.all(imgs.map(im => im.decode())); res.push(performance.now() - t0);
        }
        res.sort((a, b) => a - b); return res[1];
      }, s);
      const [w, h] = s.split('x').map(Number);
      out[`cpu${throttle}x`] = out[`cpu${throttle}x`] || {};
      out[`cpu${throttle}x`][s] = { decode15_ms_median_of3: Math.round(r), decoded_MiB_for15: Math.round(15 * w * h * 4 / 1048576), bytes_each: fs.statSync(path.join(dir, `p_${s}.jpg`)).size };
    }
    await page.close();
  }
  console.log(JSON.stringify(out, null, 2)); await browser.close();
})();
