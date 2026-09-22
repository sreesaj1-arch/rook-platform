/** Optional Windows Edge browser checks. Vite and the real API must be running.
 * No browser library or application dependency required. Fixtures below are test-only.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';

const delay = (ms: number) => new Promise(r => setTimeout(r, ms));
test('live dashboard, incident interactions, themes, keyboard and responsive layout', { timeout: 90000 }, async () => {
  const directory = resolve('node_modules/.cache');
  await mkdir(directory, { recursive: true });
  const profile = await mkdtemp(join(directory, 'rook-edge-'));
  const edge = spawn(process.env.EDGE_PATH ?? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    ['--headless=new', '--no-first-run', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'],
    { windowsHide: true, stdio: 'ignore' });
  let socket: WebSocket | undefined;
  let next = 0;
  const pending = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void }>();
  async function call(method: string, params: object = {}, sessionId?: string): Promise<any> {
    const id = ++next;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
      pending.set(id, { resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); } });
      socket!.send(JSON.stringify({ id, method, params, sessionId }));
    });
  }
  try {
    let endpoint = '';
    for (let attempt = 0; attempt < 100; attempt++) {
      try { const [port, path] = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).trim().split(/\r?\n/); endpoint = `ws://127.0.0.1:${port}${path}`; break; }
      catch { await delay(100); }
    }
    assert.ok(endpoint, 'Edge remote debugging did not start');
    socket = new WebSocket(endpoint);
    await new Promise<void>((resolve, reject) => { socket!.onopen = () => resolve(); socket!.onerror = () => reject(new Error('Edge connection failed')); });
    socket.onmessage = event => {
      const response = JSON.parse(String(event.data));
      const waiting = pending.get(response.id);
      if (waiting) { pending.delete(response.id); if (response.error) waiting.reject(new Error(response.error.message)); else waiting.resolve(response.result); }
    };
    const { targetId } = await call('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await call('Target.attachToTarget', { targetId, flatten: true });
    const page = (method: string, params: object = {}) => call(method, params, sessionId);
    const evaluate = async (expression: string) => {
      const response = await page('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      assert.ok(!response.exceptionDetails, JSON.stringify(response.exceptionDetails));
      return response.result.value;
    };
    const wait = async (expression: string) => {
      for (let i = 0; i < 100; i++) { if (await evaluate(`Boolean(${expression})`)) return; await delay(100); }
      throw new Error(`Browser condition failed: ${expression}`);
    };
    const screenshotIncidents = async (name: string) => {
      const clip = await evaluate(`(() => { const r=document.querySelector('.incidents-section').getBoundingClientRect(); return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1}; })()`);
      await writeFile(join(directory, name), Buffer.from((await page('Page.captureScreenshot', { captureBeyondViewport: true, clip })).data, 'base64'));
    };
    await page('Page.enable');
    await page('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
    await page('Page.navigate', { url: process.env.ROOK_FRONTEND_URL ?? 'http://127.0.0.1:5173' });
    await wait(`document.querySelector('.card-request_rate .value') && !document.querySelector('.incidents-section [aria-busy="true"]')`);
    const live = await evaluate(`fetch('/api/services/frontend/metrics').then(r=>r.json())`);
    console.log('Real API evidence:', JSON.stringify(live));
    assert.equal(live.metrics.request_rate.status, 'measured');
    assert.equal(live.metrics.p95_latency.status, 'measured');
    console.log('Real incident count:', await evaluate(`fetch('/api/incidents').then(r=>r.json()).then(rows=>rows.length)`));
    await writeFile(join(directory, 'incidents-live-dark.png'), Buffer.from((await page('Page.captureScreenshot', { captureBeyondViewport: true })).data, 'base64'));
    await screenshotIncidents('incidents-live-register.png');
    // Following fixture responses exist only in this browser test. No DB writes.
    const fixture = { id: '11111111-1111-4111-8111-111111111111', service_name: 'browser-test-only',
      service_namespace: 'test-only', state: 'open', reason: 'Test-only threshold breach', value: 0.6,
      unit: 'seconds', threshold: 0.5, opened_at: 1000, evaluation_timestamp: 1100,
      oldest_latest_sample_timestamp: 1090, data_quality: 'measured' };
    await evaluate(`(() => {
      const realFetch = window.fetch; window.testIncident = ${JSON.stringify(fixture)}; window.incidentMode = 'normal'; window.listCalls = 0;
      window.fetch = async (url, options) => {
        if (!String(url).startsWith('/api/incidents')) return realFetch(url, options);
        if (window.incidentMode === 'unavailable') return new Response('', {status:503});
        if (String(url).includes('?')) { window.listCalls++; return Response.json(window.incidentMode === 'empty' ? [] : [window.testIncident]); }
        if (options?.method === 'POST') {
          if (window.incidentMode === 'conflict') return new Response('', {status:409});
          window.testIncident.state = String(url).endsWith('/acknowledge') ? 'acknowledged' : 'resolved';
        }
        return Response.json(window.testIncident);
      };
      document.querySelector('.incidents-section .section-heading button').click();
    })()`);
    await wait(`document.querySelector('.incident-select')`);
    await evaluate(`document.querySelector('.incident-select').click()`);
    await wait(`document.querySelector('.incident-detail .incident-open')`);
    assert.match(await evaluate(`document.querySelector('.incident-detail').textContent`), /State updated.*Not provided by API/);
    await screenshotIncidents('incidents-test-dark-detail.png');
    await evaluate(`document.querySelector('.incident-actions button').click()`);
    await wait(`document.querySelector('.incident-detail .incident-acknowledged') && !document.querySelector('#incident-detail[aria-busy="true"]')`);
    await evaluate(`document.querySelector('.incident-actions button:last-child').click()`);
    await wait(`document.querySelector('.incident-detail .incident-resolved') && !document.querySelector('#incident-detail[aria-busy="true"]')`);
    assert.equal(await evaluate(`document.querySelector('.incident-actions button:last-child').disabled`), true);
    await evaluate(`window.testIncident.state='open'; document.querySelector('.incidents-section .section-heading button').click()`);
    await wait(`document.querySelector('.incident-detail .incident-open')`);
    await evaluate(`window.incidentMode='conflict'; document.querySelector('.incident-actions button').click()`);
    await wait(`document.querySelector('.incidents-section [role="alert"]')?.textContent.includes('HTTP 409')`);
    await evaluate(`window.incidentMode='empty'; document.querySelector('.incidents-section .section-heading button').click()`);
    await wait(`document.querySelector('.incidents-section').textContent.includes('No incidents recorded.')`);
    await evaluate(`window.incidentMode='unavailable'; document.querySelector('.incidents-section .section-heading button').click()`);
    await wait(`document.querySelector('.incidents-section').textContent.includes('Incident API unavailable')`);
    await evaluate(`window.incidentMode='normal'; document.querySelector('.incidents-section .section-heading button').click()`);
    await wait(`document.querySelector('.incident-select')`);
    const before = await evaluate('window.listCalls');
    await evaluate(`document.querySelector('.toolbar form button').click()`);
    await wait(`window.listCalls > ${before}`);
    await wait(`document.querySelector('.incident-detail .incident-open') && !document.querySelector('#incident-detail[aria-busy="true"]')`);
    await evaluate(`document.querySelector('.theme-toggle').click()`);
    await wait(`document.documentElement.dataset.theme === 'light'`);
    await page('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
    assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true);
    await page('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
    assert.equal(await evaluate(`getComputedStyle(document.querySelector('.rook-scene .rook-mark')).animationName`), 'none');
    await evaluate(`document.querySelector('.theme-toggle').focus()`);
    await page('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    await page('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    assert.equal(await evaluate('getComputedStyle(document.activeElement).outlineStyle'), 'solid');
    await writeFile(join(directory, 'incidents-test-light-mobile.png'), Buffer.from((await page('Page.captureScreenshot', { captureBeyondViewport: true })).data, 'base64'));
    await screenshotIncidents('incidents-test-light-detail.png');
    console.log('PASS: live API, fixture-only states/actions/409/unavailable, refresh, theme, mobile, reduced motion and focus');
  } finally {
    if (socket?.readyState === WebSocket.OPEN) { await call('Browser.close').catch(() => {}); socket.close(); }
    else edge.kill();
  }
});
