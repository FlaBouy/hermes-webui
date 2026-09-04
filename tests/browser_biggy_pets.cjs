/* Isolated real-browser checks. No agent, production session, or credentials. */
const { chromium } = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const repo = path.resolve(__dirname, '..');
const pet = id => ({id, displayName:id === 'bones' ? 'Bones' : 'Second', spriteVersionNumber:2,
  columns:8, rows:11, idleFrames:7, frameWidth:192, frameHeight:208, frameDurations:Array(7).fill(160), spriteUrl:`/api/biggy/pets/${id}/sprite?v=abcd`});
const biggy = {...pet('biggy'),displayName:'Biggy',spriteVersionNumber:null,columns:6,rows:1,idleFrames:6,
  frameWidth:362,frameHeight:724,frameDurations:[280,110,110,140,140,320],defaultAnchor:'dialog-right'};
let catalog = {pets:[pet('bones'),pet('second')]}, fail = false, sprite, strip;
const html = `<!doctype html><style>
body{margin:0;background:#05070b}#composerWrap{position:fixed;bottom:12px;width:100%}
.biggy-prompt-deck{width:680px;max-width:calc(100% - 140px)!important;margin:auto;height:38px;display:flex}
#composerBox{width:100%;height:38px;border:1px solid #205a50}
#biggyCategoryRail{position:fixed;right:0;top:0;bottom:0;width:48px;display:flex;flex-direction:column;z-index:119}
#mainChat:not(.biggy-pa-rail-open) #biggyCategoryRail{visibility:hidden}
#biggyArgusConversationLane{position:fixed;left:20px;top:50px;width:300px;height:400px}
</style><link rel="stylesheet" href="/static/biggy-pets.css">
<div id="mainChat" class="biggy-brand-iwo biggy-pa-rail-open"><nav id="biggyCategoryRail"></nav><div id="biggyArgusConversationLane"></div><div id="composerWrap"><div id="biggyPromptDeck" class="biggy-prompt-deck"><textarea id="composerBox" aria-label="Message"></textarea></div></div></div>
<script src="/static/biggy-pets.js"></script><script>BiggyPets.mount(document.getElementById('biggyPromptDeck'));</script>`;
const server = http.createServer((req,res) => {
  if(req.url === '/api/biggy/pets') {res.writeHead(fail?503:200, {'Content-Type':'application/json'});return res.end(JSON.stringify(catalog));}
  if(req.url.includes('/sprite?')) {res.writeHead(200,{'Content-Type':'image/png'});return res.end(req.url.includes('/biggy/sprite?') ? strip : sprite);}
  if(req.url.startsWith('/static/')) {res.writeHead(200,{'Content-Type':req.url.endsWith('.js')?'application/javascript':'text/css'});return res.end(fs.readFileSync(path.join(repo,req.url)));}
  res.writeHead(200,{'Content-Type':'text/html'});res.end(html);
});
(async()=>{
  const browser = await chromium.launch({headless:true, executablePath:process.env.BIGGY_TEST_CHROMIUM || undefined});
  try {
    const page = await browser.newPage({viewport:{width:1366,height:768}});
    // Synthetic sprite fixture; the supplied Bones asset can be used for visual evidence.
    sprite = process.env.BIGGY_PET_TEST_SPRITE ? fs.readFileSync(process.env.BIGGY_PET_TEST_SPRITE) : Buffer.from(await page.evaluate(()=>{
      const c=document.createElement('canvas');c.width=1536;c.height=2288;
      const ctx=c.getContext('2d');ctx.fillStyle='cyan';ctx.fillRect(20,20,120,170);return c.toDataURL().split(',')[1];
    }),'base64');
    strip = process.env.BIGGY_TEST_STRIP ? fs.readFileSync(process.env.BIGGY_TEST_STRIP) : Buffer.from(await page.evaluate(()=>{
      const c=document.createElement('canvas');c.width=2172;c.height=724;
      const ctx=c.getContext('2d');ctx.fillStyle='cyan';ctx.fillRect(20,20,320,680);return c.toDataURL().split(',')[1];
    }),'base64');
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const url=`http://127.0.0.1:${server.address().port}`;
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(url);
    await page.waitForFunction(()=>document.querySelector('#biggyPetPanel [role="status"]').textContent.startsWith('Local objects'));
    assert.equal(await page.locator('.biggy-pet-sprite').count(),0);
    const before = await page.locator('#composerBox').boundingBox();
    await page.getByRole('button',{name:'Pet and object controls: 0 visible',exact:true}).click();
    await page.getByRole('button',{name:'Add object',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.biggy-pet-sprite:not([hidden])').length===1);
    const firstId=await page.locator('#biggyPetInstanceSelect').inputValue();
    await page.getByRole('button',{name:'Add object',exact:true}).click();
    assert.equal(await page.locator('.biggy-pet-sprite').count(),2,'Two independent pet instances are mounted');
    assert.equal(await page.locator('.biggy-pet-sprite:visible').count(),2,'Both pet instances can remain on screen');
    const secondId=await page.locator('#biggyPetInstanceSelect').inputValue();
    assert.notEqual(firstId,secondId,'Each copy has a stable instance identity');
    await page.locator('#biggyPetSize').fill('224');
    assert.equal((await page.locator(`[data-instance-id="${secondId}"]`).boundingBox()).height,224);
    await page.getByRole('button',{name:'Hide selected',exact:true}).click();
    assert.equal(await page.locator('.biggy-pet-sprite:visible').count(),1,'Selected visibility does not affect siblings');
    await page.getByRole('button',{name:'Show selected',exact:true}).click();
    await page.keyboard.press('Escape');
    assert.deepEqual(await page.locator('#composerBox').boundingBox(),before);
    assert.equal(await page.locator('#biggyPromptDeck #biggyPets').count(),0);
    assert.equal(await page.locator('#biggyCategoryRail #biggyPets').count(),1);
    assert.ok((await page.locator('.biggy-pets-button').boundingBox()).y > 700);
    assert.ok((await page.locator('.biggy-pets-button').boundingBox()).x >= before.x+before.width);
    const second=page.locator(`[data-instance-id="${secondId}"]`);
    const start = await second.boundingBox();
    await page.mouse.move(start.x+start.width/2,start.y+start.height/2);
    await page.mouse.down();
    await page.mouse.move(420,400,{steps:8});
    await page.mouse.up();
    const moved = await second.boundingBox();
    assert.ok(Math.abs(moved.x+ moved.width/2-420)<2,'Pet follows drag');
    await page.reload();
    await page.waitForFunction(()=>document.querySelectorAll('.biggy-pet-sprite:not([hidden])').length===2);
    assert.equal((await second.boundingBox()).height,224);
    assert.deepEqual(await second.boundingBox(),moved);
    await second.focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(Math.round((await second.boundingBox()).x-moved.x),8);
    const adjusted=await second.boundingBox();
    await page.mouse.move(adjusted.x+adjusted.width/2,adjusted.y+adjusted.height/2);
    await page.mouse.down();await page.mouse.move(100,100,{steps:4});
    await page.keyboard.press('Escape');await page.mouse.up();
    assert.deepEqual(await second.boundingBox(),adjusted,'Escape cancels drag');
    await page.getByRole('button',{name:/Pet and object controls/}).click();
    await page.selectOption('#biggyPetInstanceSelect',firstId);
    await page.locator('#biggyPetSize').fill('160');
    assert.equal((await page.locator(`[data-instance-id="${firstId}"]`).boundingBox()).height,160,'Each instance has independent sizing');
    await page.selectOption('#biggyPetInstanceSelect',secondId);
    assert.equal(await page.locator('#biggyPetSize').inputValue(),'224','Selected controls follow the selected instance');
    await page.getByRole('button',{name:'Hide selected',exact:true}).click();
    const offPosition=await second.evaluate(el=>el.style.backgroundPosition);
    await page.waitForTimeout(400);
    assert.equal(await second.evaluate(el=>el.style.backgroundPosition),offPosition);
    await page.getByRole('button',{name:'Show selected',exact:true}).click();
    await page.emulateMedia({reducedMotion:'reduce'});
    const still=await second.evaluate(el=>el.style.backgroundPosition);
    await page.waitForTimeout(400);
    assert.equal(await second.evaluate(el=>el.style.backgroundPosition),still);
    await page.getByRole('button',{name:'Hide all',exact:true}).click();
    assert.equal(await page.locator('.biggy-pet-sprite:visible').count(),0);
    await page.getByRole('button',{name:'Show all',exact:true}).click();
    assert.equal(await page.locator('.biggy-pet-sprite:visible').count(),2);
    for(const width of [1920,1366,390]) {
      await page.setViewportSize({width,height:width===390?844:1080});
      await page.waitForTimeout(60);
      for(const selector of ['.biggy-pets-button','.biggy-pet-panel']) {
        const box=await page.locator(selector).boundingBox();assert.ok(box.x>=0 && box.x+box.width<=width+1,`${selector} fits ${width}`);
      }
      for(const object of await page.locator('.biggy-pet-sprite').all()){const box=await object.boundingBox();assert.ok(box.x>=0&&box.x+box.width<=width+1,'Every object fits viewport');}
      const a=await page.locator('.biggy-pet-panel').boundingBox(), b=await second.boundingBox();
      assert.ok(a.x+a.width<=b.x || b.x+b.width<=a.x || a.y+a.height<=b.y || b.y+b.height<=a.y,'Preview clears settings');
    }
    catalog={pets:[]};await page.getByRole('button',{name:'Refresh local objects'}).click();
    await page.waitForFunction(()=>document.querySelector('#biggyPetCatalogSelect').disabled);
    assert.equal(await page.getByRole('button',{name:'Add object',exact:true}).isDisabled(),true);
    assert.equal(await page.locator('.biggy-pet-sprite:visible').count(),0,'Missing catalog hides retained instances');
    fail=true;await page.getByRole('button',{name:'Refresh local objects'}).click();
    await page.getByText('Local objects unavailable. Refresh to retry.').waitFor();
    fail=false;catalog={pets:[pet('bones'),biggy]};await page.getByRole('button',{name:'Refresh local objects'}).click();
    await page.getByText('Local objects ready. No voice or AI calls.').waitFor();
    assert.equal(await page.locator('.biggy-pet-sprite:visible').count(),2,'Instances return when their catalog returns');
    await page.setViewportSize({width:1366,height:768});
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.selectOption('#biggyPetCatalogSelect','biggy');
    await page.getByRole('button',{name:'Add object',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('.biggy-pet-sprite:not([hidden])').length===3);
    const biggyId=await page.locator('#biggyPetInstanceSelect').inputValue(),biggySprite=page.locator(`[data-instance-id="${biggyId}"]`);
    assert.equal(await page.locator('#biggyPetSpeed').inputValue(),'50');
    assert.equal(await page.locator('#biggyPetPause').inputValue(),'8');
    assert.equal(await page.locator('#biggyPetRandom').isChecked(),true);
    await page.keyboard.press('Escape');
    const biggyBox=await biggySprite.boundingBox();
    assert.equal(biggyBox.height,256);assert.equal(biggyBox.width,128);
    assert.equal(biggyBox.x,332,'Default sits to right of dialog');
    assert.equal(biggyBox.y,194,'Default aligns with dialog bottom');
    await page.waitForTimeout(650);
    assert.equal(await biggySprite.evaluate(el=>el.style.backgroundPosition),'0% 0%','Rest between sips');
    await page.locator('.biggy-pets-button').click();
    await page.locator('#biggyPetSpeed').fill('150');
    await page.locator('#biggyPetPause').fill('0');
    await page.locator('#biggyPetRandom').uncheck();
    await page.waitForFunction(id=>document.querySelector(`[data-instance-id="${id}"]`).style.backgroundPosition!=='0% 0%',biggyId);
    await page.locator('#biggyPetSize').fill('448');
    await page.reload();
    await page.waitForFunction(id=>!document.querySelector(`[data-instance-id="${id}"]`).hidden,biggyId);
    assert.equal((await biggySprite.boundingBox()).height,448,'Biggy instance size persists');
    await page.locator('.biggy-pets-button').click();
    assert.equal(await page.locator('#biggyPetSpeed').inputValue(),'150');
    assert.equal(await page.locator('#biggyPetPause').inputValue(),'0');
    assert.equal(await page.locator('#biggyPetRandom').isChecked(),false);
    await page.selectOption('#biggyPetInstanceSelect',firstId);
    assert.equal(await page.locator('#biggyPetSpeed').inputValue(),'100','Bones animation stays independent');
    await page.selectOption('#biggyPetInstanceSelect',biggyId);
    await page.getByRole('button',{name:'Remove selected',exact:true}).click();
    assert.equal(await page.locator('.biggy-pet-sprite').count(),2,'Removing one object leaves its siblings');
    await page.evaluate(()=>{BiggyPets.mount(document.getElementById('biggyPromptDeck'));BiggyPets.mount(document.getElementById('biggyPromptDeck'));});
    assert.equal(await page.locator('#biggyPets').count(),1);
    await page.evaluate(()=>document.getElementById('mainChat').classList.remove('biggy-pa-rail-open'));
    await page.waitForFunction(()=>document.getElementById('biggyPetPanel').hidden);
    assert.equal(await page.locator('.biggy-pets-button').isVisible(),false);
    await page.evaluate(()=>BiggyPets.unmount());
    assert.equal(await page.locator('.biggy-pet-sprite').count(),0);
    await page.evaluate(()=>{localStorage.removeItem('biggy:pets:v2');localStorage.setItem('biggy:pets:v1',JSON.stringify({id:'bones',enabled:true,size:136,position:{x:.2,y:.3},animations:{bones:{speed:75,pause:3,random:true}}}));});
    await page.reload();
    await page.waitForFunction(()=>document.querySelectorAll('.biggy-pet-sprite:not([hidden])').length===1);
    assert.equal((await page.locator('.biggy-pet-sprite').boundingBox()).height,136,'Single-pet state migrates to one object instance');
    await page.getByRole('button',{name:'Pet and object controls: 1 visible',exact:true}).click();
    assert.equal(await page.locator('#biggyPetSpeed').inputValue(),'75');
    assert.equal(await page.locator('#biggyPetPause').inputValue(),'3');
    assert.deepEqual(errors,[]);
    console.log('PASS: multiple independent objects, selection, show/hide all, resize, persistence/migration, drag/keys, reduced motion, catalog recovery, removal, teardown; 1920/1366/390 widths');
  } finally { await browser.close();server.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
