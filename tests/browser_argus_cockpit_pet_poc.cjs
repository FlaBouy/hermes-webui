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
    await page.waitForFunction(() => window.argusCockpitPocAdapter?.connected);
    assert.equal(await page.locator('argus-cockpit-pet').count(), 1);
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelectorAll('.menu-button').length), 12);
    assert.equal(await page.locator('#poc-composer [data-composer-action]').count(), 6);
    assert.equal(await page.locator('#poc-response').getAttribute('data-mode'), 'concise');
    assert.equal(await page.locator('#contract-status').textContent(), 'PARITY PASS · 12/12 · 10/10');
    const contract = await page.evaluate(() => window.argusCockpitPocAdapter.snapshot());
    const parity = await page.evaluate(() => window.argusCockpitPocAdapter.verifyParity());
    assert.equal(contract.actionCount, 12);
    assert.deepEqual(contract.actions, ['chat','tasks','kanban','skills','memory','spaces','profiles','todos','insights','logs','settings','tools']);
    assert.equal(parity.passed, true);
    assert.equal(parity.productionWired, false);
    assert.equal(parity.composerControls, 6);
    const composerBefore = await page.locator('#poc-composer').evaluate(el => ({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height,bottom:innerHeight-el.getBoundingClientRect().bottom}));
    await page.locator('#orb-name').fill('WATCHTOWER');
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.name').textContent), 'WATCHTOWER');
    assert.equal(await page.locator('argus-cockpit-pet').getAttribute('label'), 'WATCHTOWER');
    const beforeWidth = await page.locator('argus-cockpit-pet').evaluate(el => el.getBoundingClientRect().width);
    await page.locator('#orb-scale').fill('60');
    const afterWidth = await page.locator('argus-cockpit-pet').evaluate(el => el.getBoundingClientRect().width);
    assert.ok(afterWidth < beforeWidth);
    const composerAfter = await page.locator('#poc-composer').evaluate(el => ({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height,bottom:innerHeight-el.getBoundingClientRect().bottom}));
    assert.deepEqual(composerAfter, composerBefore, 'Biggy bar remains a fixed independent anchor while the Orb scales');
    const proportions = await page.locator('argus-cockpit-pet').evaluate(el => {
      const root = el.shadowRoot; const hostWidth = el.getBoundingClientRect().width; const button = root.querySelector('.menu-button').getBoundingClientRect();
      return { width: button.width / hostWidth, height: button.height / hostWidth };
    });
    assert.ok(Math.abs(proportions.width - .11667) < .002);
    assert.ok(Math.abs(proportions.height - .0375) < .002);
    const before = await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.getElementById('eye').style.translate);
    await page.mouse.move(1320, 80); await page.waitForTimeout(180);
    const after = await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.getElementById('eye').style.translate);
    assert.notEqual(after, before, 'Eye follows pointer direction');
    const [x,y] = after.split(' ').map(Number); assert.ok(x > 0 && y < 0); assert.ok(Math.abs(x)<=11.1 && Math.abs(y)<=8.1);
    const action = await page.locator('argus-cockpit-pet').evaluate(el => new Promise(resolve => { el.addEventListener('argus-cockpit-action', e => resolve(e.detail.action), {once:true}); el.shadowRoot.querySelector('.menu-button[data-action="chat"]').click(); }));
    assert.equal(action, 'chat');
    assert.equal(await page.locator('#contract-status').textContent(), 'PARITY PASS · 12/12 · 10/10 · CHAT');
    const submitted = await page.locator('#poc-composer').evaluate(el => new Promise(resolve => {
      el.addEventListener('argus-cockpit-submit', e => resolve(e.detail.text), {once:true});
      el.querySelector('.poc-prompt').value = 'Anchor test';
      el.querySelector('[data-composer-action="send"]').click();
    }));
    assert.equal(submitted, 'Anchor test');
    await page.locator('argus-cockpit-pet').evaluate(el => el.setActiveActions(['chat']));
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelectorAll('[data-action="chat"].active').length), 5);
    await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.menu-button[data-action="tools"]').dispatchEvent(new PointerEvent('pointerenter')));
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelectorAll('[data-action="tools"].hover').length), 5);
    await page.locator('argus-cockpit-pet').evaluate(el => { el.model='ignored'; el.setAttribute('model','POC-MODEL'); el.setAttribute('status','thinking'); });
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.model').textContent), '◆ POC-MODEL');
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.state').textContent), 'THINKING');
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.entity').dataset.state), 'thinking');
    await page.locator('argus-cockpit-pet').evaluate(el => el.setAttribute('status','speaking'));
    assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.entity').dataset.state), 'speaking');
    await page.locator('[data-state="warning"]').click();
    assert.equal(await page.locator('#poc-composer').getAttribute('data-state'), 'warning');
    await page.locator('[data-response="expanded"]').click();
    assert.equal(await page.locator('#poc-response').getAttribute('data-mode'), 'expanded');
    assert.equal(await page.locator('#poc-response .poc-response-detail').isVisible(), true);
    await page.locator('[data-response="hidden"]').click();
    assert.equal(await page.locator('#poc-response').isVisible(), false);
    for (const state of ['listening', 'dispatch', 'working', 'success', 'warning', 'error', 'sleep']) {
      await page.locator('argus-cockpit-pet').evaluate((el, value) => el.setAttribute('status', value), state);
      assert.equal(await page.locator('argus-cockpit-pet').evaluate(el => el.shadowRoot.querySelector('.entity').dataset.state), state);
    }
    assert.deepEqual(errors, []);
    console.log('PASS: portable cockpit-pet, editable label, unified Orb scaling/placement, independent composer anchor, state animation, menu path feedback, bounded cursor-tracking eye');
  } finally { await browser.close(); server.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
