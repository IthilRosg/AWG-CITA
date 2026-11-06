const {spawn} = require('node:child_process');
const net = require('node:net');
const assert = require('node:assert/strict');
const {chromium} = require('@playwright/test');
const pause = ms => new Promise(r => setTimeout(r, ms));
async function main() {
 const port = await new Promise(resolve => { const s=net.createServer(); s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));}); });
 const url=`http://127.0.0.1:${port}/`;
 const child=spawn(process.env.AWG_TEST_PYTHON || 'python3',['tests/real_fixture_server.py'],{stdio:'ignore',env:{...process.env,AWG_FIXTURE_PORT:String(port)}});
 let browser;
 try {
  let ready=false;
  for(let i=0;i<60;i++){try{ready=(await fetch(url+'api/status')).ok;}catch{}if(ready)break;await pause(100);}
  assert(ready);
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let unavailable=false;
  const events=Array.from({length:200},(_,i)=>({checked_at:'2026-01-01T00:00:00+00:00',phase:i%2?'RESULT':'INTENT',correlation_id:String(i).padStart(32,'0'),actor:'operator',operation:'create',client_id:'peer-0123456789abcdef',...(i%2?{result:'OK'}:{})}));
  await page.route('**/api/actions',route=>unavailable ? route.fulfill({status:503,json:{error_code:'audit_read_failed'}}) : route.fulfill({json:{schema_version:1,source:'server_audit',events,truncated:true}}));
  await page.goto(url+'#journal');
  await page.waitForFunction(()=>document.querySelector('#app').getAttribute('aria-busy')==='false');
  assert.equal(await page.locator('#journal-retention').textContent(),'Серверный журнал');
  assert.equal(await page.locator('#journal-events .audit-row').count(),200);
  assert((await page.locator('#journal-events .audit-row').first().textContent()).includes(events[199].correlation_id));
  assert((await page.locator('[data-i18n="retentionDescription"]').textContent()).includes('Более ранние'));
  assert((await page.locator('#journal-events').textContent()).includes('Это не подтверждение выполнения'));
  unavailable=true;
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#app').getAttribute('aria-busy')==='false');
  assert.equal(await page.locator('#journal-retention').textContent(),'Журнал недоступен');
  assert.equal(await page.locator('#journal-events .audit-row').count(),0);
  assert(await page.locator('#export-json').isDisabled());
  assert.equal(await page.locator('#client-rows .client-row').count(),1);
  unavailable=false;
  await page.reload();
  await page.waitForFunction(()=>document.querySelectorAll('#journal-events .audit-row').length===200);
  assert.equal(errors.length,0);
  console.log('PASS server audit: bounded events, order, intent, unavailable isolation and recovery');
 } finally { if(browser)await browser.close();child.kill(); }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
