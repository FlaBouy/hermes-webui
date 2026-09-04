/* Isolated real-browser POC checks. No production session or wiring. */
const { chromium } = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const repo = path.resolve(__dirname, '..');
const mime = file => file.endsWith('.js') ? 'application/javascript' : file.endsWith('.png') ? 'image/png' : 'text/html';
const server = http.createServer((req,res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const file = pathname === '/' ? '/static/argus-cockpit-pet-poc.html' : pathname;
  const target = path.join(repo, file);
  if (!target.startsWith(repo) || !fs.existsSync(target)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, {'Content-Type': mime(target)}); res.end(fs.readFileSync(target));
});
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.BIGGY_TEST_CHROMIUM || undefined});
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const page = await browser.newPage({viewport:{width:1366,height:768}});
    const errors=[]; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.waitForFunction(() => customElements.get('argus-cockpit-pet'));
    assert.equal(await page.locator('argus-cockpit-pet').count(), 1);
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelectorAll('button').length), 12);
    await page.locator('#orb-name').fill('WATCHTOWER');
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.name').textContent), 'WATCHTOWER');
    assert.equal(await page.locator('argus-cockpit-pet').getAttribute('label'), 'WATCHTOWER');
    const beforeWidth = await page.locator('argus-cockpit-pet').evaluate(el => el.getBoundingClientRect().width);
    await page.locator('#orb-scale').fill('60');
    const afterWidth = await page.locator('argus-cockpit-pet').evaluate(el => el.getBoundingClientRect().width);
    assert.ok(afterWidth < beforeWidth);
    const proportions = await page.locator('argus-cockpit-pet').evaluate(el => {
      const root = el.shadowRoot; const hostWidth = el.getBoundingClientRect().width; const button = root.querySelector('button').getBoundingClientRect();
      return { width: button.width / hostWidth, height: button.height / hostWidth };
    });
    assert.ok(Math.abs(proportions.width - .11667) < .002);
    assert.ok(Math.abs(proportions.height - .0375) < .002);
    const before = await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.getElementById('eye').style.translate);
    await page.mouse.move(1320, 80); await page.waitForTimeout(180);
    const after = await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.getElementById('eye').style.translate);
    assert.notEqual(after, before, 'Eye follows pointer direction');
    const [x,y] = after.split(' ').map(Number); assert.ok(x > 0 && y < 0); assert.ok(Math.abs(x)<=11.1 && Math.abs(y)<=8.1);
    const action = await page.locator('argus-cockpit-pet').evaluate(el => new Promise(resolve => { el.addEventListener('argus-cockpit-action', e => resolve(e.detail.action), {once:true}); el.shadowRoot.querySelector('[data-action="chat"]').click(); }));
    assert.equal(action, 'chat');
    await page.locator('argus-cockpit-pet').evaluate(el => el.setActiveActions(['chat']));
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelectorAll('[data-action="chat"].active').length), 3);
    await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('button[data-action="tools"]').dispatchEvent(new PointerEvent('pointerenter')));
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelectorAll('[data-action="tools"].hover').length), 3);
    await page.locator('argus-cockpit-pet').evaluate(el => { el.model='ignored'; el.setAttribute('model','POC-MODEL'); el.setAttribute('status','thinking'); });
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.model').textContent), '◆ POC-MODEL');
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.state').textContent), 'THINKING');
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.entity').dataset.state), 'thinking');
    await page.locator('argus-cockpit-pet').evaluate(el => el.setAttribute('status','speaking'));
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.entity').dataset.state), 'speaking');
    for (const state of ['working', 'success', 'warning', 'error']) {
      await page.locator('argus-cockpit-pet').evaluate((el, value) => el.setAttribute('status', value), state);
      assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.entity').dataset.state), state);
    }
    assert.deepEqual(errors, []);
    console.log('PASS: portable cockpit-pet, editable label, unified scaling/placement, state animation, menu path feedback, bounded cursor-tracking eye');
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
