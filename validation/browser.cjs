// Real browser -> Vite proxy -> Django -> Next.js -> HTTP provider fixture.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const frontend = path.resolve(__dirname, '../../AI-edu-frontend');
const { chromium } = require(path.join(frontend, 'node_modules/@playwright/test'));
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const results = [];
async function check(name, action) {
  const start = Date.now();
  try { const evidence = await action(); results.push({ name, passed: true, elapsed_ms: Date.now()-start, evidence }); }
  catch (error) { results.push({ name, passed: false, elapsed_ms: Date.now()-start, error: error.message }); throw error; }
  finally { fs.writeFileSync(config.result, JSON.stringify({ results }, null, 2)); }
}
(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const contexts = [], pages = [];
    for (const student of config.students) {
      const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
      const page = await context.newPage(); contexts.push(context); pages.push(page);
      const traffic=[];
      page.on('response', r=>{if(r.url().includes('/api/')) traffic.push({path:new URL(r.url()).pathname,status:r.status()});});
      page.on('pageerror', e=>traffic.push({error:e.message}));
      await check(`browser_login_${student.marker}`, async () => {
        await page.goto(config.base + '/#/login');
        await page.locator('input[name="email"]').fill(student.email);
        await page.locator('input[name="password"]').fill(config.password);
        const login = page.waitForResponse(r => r.url().endsWith('/api/v1/auth/login/') && r.request().method() === 'POST');
        await page.locator('form button[type="submit"]').click();
        assert.equal((await login).status(), 200);
        await page.waitForURL(url=>url.hash==='#/' || url.hash==='');
        await page.goto(config.base + '/#/items/' + student.item);
        try {
          await page.locator('.tutor-panel textarea').waitFor({state:'attached'});
          if(!await page.locator('.tutor-panel textarea').isVisible()) await page.locator('.tutor-toggle').click();
          await page.locator('.tutor-panel textarea').waitFor();
        } catch(error) {
          fs.writeFileSync(path.join(config.screenshots,'browser-failure.json'),JSON.stringify({traffic,url:page.url(),body:await page.locator('body').innerText()},null,2));
          await page.screenshot({path:path.join(config.screenshots,'browser-failure.png'),fullPage:true});
          throw error;
        }
        return { login_status: 200, item: student.item, browser: browser.version() };
      });
    }
    async function ask(page, text, expected, failure = false) {
      await page.locator('.tutor-panel textarea').fill(text);
      const response = page.waitForResponse(r => r.url().endsWith('/api/v1/tutor/chat/') && r.request().method() === 'POST');
      await page.locator('.tutor-panel button[type="submit"]').click();
      const r = await response;
      // The real client cancels its reader when it encounters event:error.
      // Chrome may then discard the response body; persisted gateway evidence
      // and the visible error remain available and are checked independently.
      let raw;
      if (failure) {
        await page.locator('.tutor-error').waitFor();
        raw = await r.text().catch(()=>null);
        if(raw!==null) assert.ok(!raw.includes('event: done'));
      } else {
        raw = await r.text();
        assert.equal(r.status(), 200); assert.ok(raw.includes('event: done'));
        assert.ok(raw.includes(expected));
        await page.locator('.tutor-panel').getByText(expected, { exact: false }).first().waitFor();
      }
      return { question: text, status: r.status(), raw_sse_or_error: raw,
        visible_error: failure ? await page.locator('.tutor-error').innerText() : null };
    }
    for (let round = 1; round <= 3; round++) {
      await check(`concurrent_browser_round_${round}`, async () => {
        return await Promise.all(pages.map((page, i) => ask(page,
          `${config.students[i].marker} round ${round}: Explain the lecture rule.`,
          `${config.students[i].scope} verified ${config.students[i].marker}`)));
      });
    }
    await check('browser_histories_are_separate', async () => {
      const histories = await Promise.all(pages.map(page => page.evaluate(() =>
        Object.keys(sessionStorage).filter(k => k.startsWith('ai-edu:tutor:')).map(k => ({ key: k, value: JSON.parse(sessionStorage[k]) })))));
      for (let i=0;i<2;i++) {
        const own=JSON.stringify(histories[i]), other=config.students[1-i].marker;
        assert.ok(own.includes(config.students[i].marker)); assert.ok(!own.includes(other));
        assert.equal(histories[i][0].value.messages.length, 6);
        await pages[i].screenshot({ path: path.join(config.screenshots, `student-${i+1}.png`), fullPage: true });
      }
      return histories;
    });
    for (const fault of ['FAULT_RETRIEVAL', 'FAULT_PROVIDER', 'FAULT_TIMEOUT', 'FAULT_SILENT_END', 'FAULT_STREAM_STALL', 'FAULT_BROKEN_STREAM']) {
      // Reset browser history so a previous fault marker cannot affect another case.
      await pages[0].locator('.tutor-panel button[aria-label="Очистить диалог"]').click();
      await check(`browser_${fault.toLowerCase()}`, () => ask(pages[0], `${fault}: Explain the lecture rule.`, null, true));
    }
    await contexts[0].close(); await contexts[1].close();
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode=1; });
