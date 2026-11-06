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
  await page.clock.install();
  const clients=Array.from({length:124},(_,i)=>({id:`peer-synthetic-${i}`,name:`Device ${String(i).padStart(3,'0')}`,status:'NEVER',lastHandshakeAt:null,lastSeenAt:null,createdAt:null,expiration:'',rxBytes:0,txBytes:0,notes:'',tags:[],warning:''}));
  const config='[Interface]\nPrivateKey = SYNTHETIC-ONLY\nAddress = 127.0.0.2/32\nDNS = 127.0.0.1\nMTU = 1420\n\n[Peer]\nPublicKey = SYNTHETIC-SERVER\nAllowedIPs = 0.0.0.0/0\nPersistentKeepalive = 25\nEndpoint = vpn.example.test:51820\n';
  const qr='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC';
  let expired=false, hold=false, release, requested=false, holdCreate=false,releaseCreate,createRequested=false,holdList=false,releaseList,listRequested=false;
  await page.route('**/api/clients',async route=>{
   if(expired){await route.fulfill({status:401,contentType:'text/html',body:'Sign in'});return;}
   if(route.request().method()==='POST'){
    createRequested=true;
    if(holdCreate)await new Promise(r=>releaseCreate=r);
    await route.fulfill({status:201,contentType:'application/json',body:JSON.stringify({schema_version:1,client:clients[0],configText:config,qrDataUri:qr,oneTime:false})}).catch(()=>{});return;
   }
   if(holdList){listRequested=true;await new Promise(r=>releaseList=r);}
   await route.fulfill({json:{schema_version:1,clients}});
  });
  await page.route('**/api/clients/*/config',async route=>{
   requested=true;if(hold)await new Promise(r=>release=r);
   await route.fulfill({json:{schema_version:1,client:clients[0],configText:config,qrDataUri:qr,revision:'a'.repeat(64)}});
  });
  await page.goto(url+'#clients');
  await page.waitForFunction(()=>document.querySelectorAll('#client-rows .client-row').length===124);
  async function open(wait=true){await page.locator('[data-action-menu-toggle="peer-synthetic-0"]').click();await page.locator('#client-action-config').click();if(wait)await page.waitForFunction(()=>!document.querySelector('#config-preview-download').disabled);}
  async function clean(){assert.equal(await page.locator('#config-preview-modal').isHidden(),true);assert(!(await page.locator('body').textContent()).includes('SYNTHETIC-ONLY'));assert.equal(await page.locator('#create-config-text').inputValue(),'');assert.equal(await page.locator('#config-preview-qr img').count(),0);}
  async function hide(){await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});}
  async function show(){await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));});}
  await open();assert((await page.locator('#config-safety').textContent()).includes('IPv6'));
  const downloadPromise=page.waitForEvent('download');await page.locator('#config-preview-download').click();
  assert.equal((await downloadPromise).suggestedFilename(), clients[0].name+'.conf');
  await page.screenshot({path:'.ops-tmp/awg-cita-browser-artifacts/privacy-overview.png'});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({path:'.ops-tmp/awg-cita-browser-artifacts/privacy-mobile.png'});
  await page.setViewportSize({width:1280,height:800});
  await page.locator('#config-preview-tab-config').click();assert((await page.locator('#config-preview-text').textContent()).includes('SYNTHETIC-ONLY'));
  await hide();await clean();await show();
  await open();await page.clock.runFor(120001);await clean();
  await open();await page.clock.runFor(90000);await page.locator('#config-preview-close').click();
  await page.locator('#add-client-button').click();await page.locator('#preview-name').fill('Unsaved draft');
  await page.clock.runFor(31000);assert.equal(await page.locator('#preview-name').inputValue(),'Unsaved draft');assert(await page.locator('#create-preview-modal').isVisible());await page.locator('#preview-close').click();

  hold=true;requested=false;await open(false);while(!requested)await pause(10);await hide();release();await pause(100);await clean();await show();hold=false;
  holdCreate=true;await page.locator('#add-client-button').click();await page.locator('#preview-name').fill(clients[0].name);await page.locator('#preview-submit').click();
  while(!createRequested)await pause(10);await hide();releaseCreate();await pause(100);await clean();assert(await page.locator('#create-preview-modal').isHidden());await show();

  holdCreate=false;holdList=true;
  await page.route('**/api/profiles/wg/clients',route=>route.fulfill({json:{schema_version:1,clients:[]}}));
  await page.locator('#add-client-button').click();await page.locator('#preview-name').fill(clients[0].name);await page.locator('#preview-submit').click();
  while(!listRequested)await pause(10);await hide();await show();
  await page.locator('[data-client-profile="wg"]').click();await page.waitForFunction(()=>document.querySelector('#app').getAttribute('aria-busy')==='false');
  releaseList();await pause(100);assert.equal(await page.locator('#client-rows .client-row').count(),0,'stale creation readback overwrote new profile');
  holdList=false;await page.locator('[data-client-profile="awg3"]').click();await page.waitForFunction(()=>document.querySelectorAll('#client-rows .client-row').length===124);

  createRequested=false;holdCreate=true;
  await page.locator('#add-client-button').click();await page.locator('#preview-name').fill(clients[0].name);await page.locator('#preview-submit').click();
  while(!createRequested)await pause(10);
  await page.clock.runFor(45001);assert(await page.locator('#preview-submit').isDisabled(),'mutation aborted before server deadline');
  await page.clock.runFor(300000);await page.waitForFunction(()=>!document.querySelector('#preview-submit').disabled);
  assert((await page.locator('#preview-form-error').textContent()).includes('не подтверждён'));
  releaseCreate();await pause(100);await page.locator('#preview-close').click();
  await open();await page.locator('#config-preview-tab-config').click();
  expired=true;await page.locator('#refresh-button').evaluate(e=>e.click());await page.waitForFunction(()=>!document.querySelector('#session-expired').hidden);await clean();
  assert.deepEqual(errors,[]);
  console.log('browser_privacy=PASS 124_clients hidden TTL late_config late_create expired_session');
 } finally {if(browser)await browser.close();child.kill();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
