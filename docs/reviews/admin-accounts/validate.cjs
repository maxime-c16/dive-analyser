const { chromium } = require(process.cwd() + '/frontend/node_modules/playwright');
const assert = require('node:assert/strict');
require('node:fs').mkdirSync('/tmp/admin-account-ui', {recursive:true});
const baseUrl=process.env.ADMIN_REVIEW_URL || 'http://127.0.0.1:3016/e2e/fixtures/admin-account-review.html';
const tabs=['Identity','Security','Audit trail','Lifecycle'];
async function assertTab(page, name) {
 const tab = page.getByRole('tab',{name,exact:true});
 await tab.click();
 assert.equal(await tab.getAttribute('aria-selected'),'true');
 assert.equal(await page.getByRole('tabpanel').count(),1);
 assert.equal(await page.getByRole('dialog').count(),0,`${name} must be an inline tab page`);
 assert.equal(await page.locator('.pro-drawer-backdrop').count(),0);
}
async function assertFit(page, context) {
 const overflow = await page.evaluate(()=>{
  const issues=[];
  if(document.documentElement.scrollWidth>innerWidth+1)issues.push('document overflows');
  for(const card of document.querySelectorAll('.pro-card,.pro-node,.pro-change-tray,.pro-tools,.pro-capability-card')){
   const box=card.getBoundingClientRect();
   if(!box.width || !box.height)continue;
   if(box.left < -1 || box.right > innerWidth+1)issues.push(`${card.className} outside viewport`);
   if(innerWidth<=760 && card.scrollWidth>card.clientWidth+1)issues.push(`${card.className} content clipped`);
  }
  return issues;
 });
 assert.deepEqual(overflow,[],context);
}
(async () => {
 const browser = await chromium.launch({headless:true});
 const errors=[];
 for (const layout of process.env.ADMIN_REVIEW_LAYOUT ? [process.env.ADMIN_REVIEW_LAYOUT] : ['command','support','access']) {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`${baseUrl}?layout=${layout}`);
  await page.getByRole('heading',{name:'Camille Martin',exact:true}).waitFor();
  const studioName=layout==='access'?'Access studio':layout==='support'?'Investigation':'Command center';
  const studio=()=>assertTab(page,studioName);
  await page.screenshot({path:`/tmp/admin-account-ui/${layout}-desktop.png`,fullPage:true});
  await page.getByRole('button',{name:'Test failure',exact:true}).click();
  await assertTab(page,'Identity');
  await page.getByLabel('Display name',{exact:true}).fill('Camille Updated');
  await assertTab(page,'Security');
  await assertTab(page,'Identity');
  assert.equal(await page.getByLabel('Display name',{exact:true}).inputValue(),'Camille Updated','Draft survives tab changes');
  await page.getByRole('button',{name:'Save profile',exact:true}).click();
  assert.equal(await page.getByRole('alert').count(),1);
  assert.equal(await page.getByLabel('Display name',{exact:true}).inputValue(),'Camille Updated');
  await page.getByRole('button',{name:'Save profile',exact:true}).click();
  await page.getByRole('heading',{name:'Camille Updated',exact:true}).waitFor();
  assert.equal(await page.getByRole('tab',{name:'Identity',exact:true}).getAttribute('aria-selected'),'true','Saving stays on Identity');
  await studio();
  await page.getByRole('button',{name:'Run access check',exact:true}).click();
  await page.getByText('Viewing blocked',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Preview resolution',exact:true}).click();
  await page.getByRole('button',{name:'Review & apply',exact:true}).click();
  assert((await page.getByRole('dialog').innerText()).includes('24 competition dives'));
  await page.getByRole('button',{name:'Confirm change',exact:true}).click();
  await page.getByRole('button',{name:'Run access check',exact:true}).click();
  await page.getByText('Viewing allowed',{exact:true}).waitFor();
  await page.getByLabel('Resource to investigate').selectOption('public');
  await page.getByRole('button',{name:'Run access check',exact:true}).click();
  await page.getByText('Management denied · viewing does not grant editing',{exact:false}).waitFor();
  await assertTab(page,'Security');
  await page.getByRole('button',{name:'Revoke',exact:true}).first().click();
  await page.getByRole('button',{name:'Confirm change',exact:true}).click();
  assert.equal(await page.locator('.pro-session').count(),1);
  await assertTab(page,'Audit trail');
  await page.getByLabel('Filter audit history').selectOption('security');
  assert((await page.locator('.pro-tab-main .pro-timeline').innerText()).includes('Session revoked'));
  await assertTab(page,'Lifecycle');
  await page.getByLabel('Reason for account action').fill('Temporary support review');
  await page.getByRole('button',{name:'Review suspension',exact:true}).click();
  await page.getByRole('button',{name:'Confirm change',exact:true}).click();
  assert.equal(await page.getByRole('tab',{name:'Lifecycle',exact:true}).getAttribute('aria-selected'),'true');
  await studio();
  await page.getByRole('button',{name:'Run access check',exact:true}).click();
  await page.getByText('Viewing blocked',{exact:true}).waitFor();
  await assertTab(page,'Lifecycle');
  await page.getByRole('button',{name:'Review restoration',exact:true}).click();
  await page.getByRole('button',{name:'Confirm change',exact:true}).click();
  for(const width of [320,360,390,430,768,1440]){
   await page.setViewportSize({width,height:width>760?1000:844});
   await studio();
   await assertFit(page,`${layout} studio ${width}px`);
   if(width<=760 && layout!=='support'){
    assert.equal(await page.locator('.pro-table').isVisible(),false,'Mobile uses capability cards instead of a scrolling table');
    assert.equal(await page.locator('.pro-capability-card').count(),4);
   }
   for(const tab of tabs){
    await assertTab(page,tab);
    await assertFit(page,`${layout} ${tab} ${width}px`);
    if(width===390)await page.screenshot({path:`/tmp/admin-account-ui/${layout}-${tab.replace(/ /g,'-').toLowerCase()}-mobile.png`,fullPage:true});
   }
  }
  await page.setViewportSize({width:390,height:844});
  await studio();
  await page.getByRole('button',{name:'Review removal',exact:true}).first().click();
  await assertFit(page,`${layout} staged change mobile`);
  await page.getByRole('button',{name:'Discard',exact:true}).click();
  await page.screenshot({path:`/tmp/admin-account-ui/${layout}-mobile.png`,fullPage:true});
  await assertTab(page,'Identity');
  await page.getByLabel('Email address',{exact:true}).fill('invalid');
  await page.getByRole('button',{name:'Save profile',exact:true}).click();
  assert.equal(await page.getByRole('dialog').count(),0);
  assert.equal(await page.getByLabel('Email address').evaluate(input=>input.checkValidity()),false);
  await page.getByRole('button',{name:'Discard',exact:true}).click();
  await page.getByRole('tab',{name:'Identity',exact:true}).focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.getByRole('tab',{name:'Security',exact:true}).getAttribute('aria-selected'),'true');
  assert(new URL(page.url()).searchParams.get('tab')==='security');
  await page.goBack();
  assert.equal(await page.getByRole('tab',{name:'Identity',exact:true}).getAttribute('aria-selected'),'true');
  await page.close();
  console.log(`${layout}: inline tabs, draft retention, profile error/retry, binding impact/apply, policy checks, sessions, audit, lifecycle, keyboard/back navigation and 320–1440px card bounds passed`);
 }
 const page=await browser.newPage();
 await page.goto(`${baseUrl}?layout=access&tab=security`);
 await page.getByRole('heading',{name:'Security control',exact:true}).waitFor();
 assert.equal(await page.getByRole('tab',{name:'Security',exact:true}).getAttribute('aria-selected'),'true');
 await page.reload();
 await page.getByRole('heading',{name:'Security control',exact:true}).waitFor();
 assert.deepEqual(errors,[]);
 await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
