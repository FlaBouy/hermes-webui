/* Local multi-object companion manager: no model, microphone, or external calls. */
(() => {
  'use strict';
  if (window.BiggyPets) return;
  const KEY='biggy:pets:v2', LEGACY_KEY='biggy:pets:v1', ID=/^[a-z0-9][a-z0-9_-]{0,63}$/, INSTANCE_ID=/^[a-z0-9][a-z0-9_-]{0,95}$/;
  const clampSize=value=>Math.min(448,Math.max(64,Number(value)||128));
  const validPosition=value=>value&&Number.isFinite(value.x)&&Number.isFinite(value.y)&&value.x>=0&&value.x<=1&&value.y>=0&&value.y<=1;
  const node=(tag,attrs={},text='')=>{const result=document.createElement(tag);Object.entries(attrs).forEach(([key,value])=>result.setAttribute(key,value));result.textContent=text;return result;};
  const readJson=key=>{try{return JSON.parse(localStorage.getItem(key)||'null');}catch(_){return null;}};
  const newId=catalogId=>`${catalogId}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,8)}`;
  const animationDefault=id=>({speed:id==='biggy'?50:100,pause:id==='biggy'?8:0,random:id==='biggy'});
  const normalizeAnimation=(value,id)=>{const fallback=animationDefault(id);return{speed:Math.max(25,Math.min(150,Number(value?.speed)||fallback.speed)),pause:Math.max(0,Math.min(20,Number.isFinite(value?.pause)?value.pause:fallback.pause)),random:typeof value?.random==='boolean'?value.random:fallback.random};};
  const normalizeInstance=value=>!value||typeof value!=='object'||!ID.test(value.catalogId||'')||!INSTANCE_ID.test(value.instanceId||'')?null:{instanceId:value.instanceId,catalogId:value.catalogId,enabled:value.enabled===true,size:clampSize(value.size),position:validPosition(value.position)?value.position:null,animation:normalizeAnimation(value.animation,value.catalogId)};
  function initialState(){
    const saved=readJson(KEY);
    if(saved&&Array.isArray(saved.instances)){
      const instances=saved.instances.map(normalizeInstance).filter(Boolean);
      return{catalogId:ID.test(saved.catalogId||'')?saved.catalogId:'',selectedInstanceId:instances.some(item=>item.instanceId===saved.selectedInstanceId)?saved.selectedInstanceId:(instances[0]?.instanceId||''),instances};
    }
    const old=readJson(LEGACY_KEY);if(!old||!ID.test(old.id||''))return{catalogId:'',selectedInstanceId:'',instances:[]};
    const position=validPosition(old.positions?.[old.id])?old.positions[old.id]:(validPosition(old.position)?old.position:null);
    const instance=normalizeInstance({instanceId:newId(old.id),catalogId:old.id,enabled:old.enabled===true,size:old.sizes?.[old.id]||old.size||(old.id==='biggy'?256:128),position,animation:old.animations?.[old.id]});
    return{catalogId:old.id,selectedInstanceId:instance.instanceId,instances:[instance]};
  }
  const state=initialState(), runtimes=new Map(), reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  let root,button,panel,catalogSelect,addButton,instanceSelect,toggle,removeButton,range,output,speed,speedOutput,pause,pauseOutput,random,resetPosition,status,showAllButton,hideAllButton,observer,visibilityObserver;
  let pets=[],loading=false,destroyed=false,catalogRequest=0,catalogAbort,drag=null;
  const persist=()=>{try{localStorage.setItem(KEY,JSON.stringify(state));}catch(_){}};
  const selectedInstance=()=>state.instances.find(item=>item.instanceId===state.selectedInstanceId);
  const petFor=instance=>pets.find(pet=>pet.id===instance?.catalogId);
  const widthFor=(instance,pet)=>instance.size*(pet?.frameWidth||192)/(pet?.frameHeight||208);
  const displayLabel=instance=>{const pet=petFor(instance),same=state.instances.filter(item=>item.catalogId===instance.catalogId);return`${pet?.displayName||instance.catalogId}${same.length>1?` ${same.indexOf(instance)+1}`:''}`;};
  function stop(runtime){if(runtime){clearTimeout(runtime.timer);runtime.timer=0;}}
  function animate(instance,runtime){
    stop(runtime);if(!runtime.loaded||!instance.enabled||document.hidden||reduced.matches)return;
    const pet=petFor(instance);if(!pet)return;const settings=normalizeAnimation(instance.animation,instance.catalogId);
    const delay=()=>pet.frameDurations[runtime.frame]*100/settings.speed+(runtime.frame===0?settings.pause*1000*(settings.random?.5+Math.random():1):0);
    const tick=()=>{runtime.frame=(runtime.frame+1)%pet.idleFrames;runtime.stage.style.backgroundPosition=`${pet.columns>1?runtime.frame/(pet.columns-1)*100:0}% 0%`;runtime.timer=setTimeout(tick,delay());};
    runtime.timer=setTimeout(tick,delay());
  }
  function defaultCoordinates(instance,pet){
    const prompt=(document.getElementById('msg')||document.getElementById('composerBox')||button).getBoundingClientRect();
    const lane=document.getElementById('biggyArgusConversationLane'),laneBox=lane?.getBoundingClientRect(),dialog=pet?.defaultAnchor==='dialog-right';
    const visible=dialog&&laneBox?.width&&laneBox?.height&&getComputedStyle(lane).visibility!=='hidden';
    const offset=Math.max(0,state.instances.filter(item=>item.catalogId===instance.catalogId).indexOf(instance))*20;
    return{x:(dialog?(visible?laneBox.right:prompt.right)+12:prompt.left+12)+offset,y:((visible?laneBox.bottom:prompt.top-8)-instance.size)-offset};
  }
  function positionOne(instance,runtime,avoidPanel=false){
    const pet=petFor(instance);if(!pet||!runtime)return;const width=widthFor(instance,pet),maxX=Math.max(8,innerWidth-width-8),maxY=Math.max(8,innerHeight-instance.size-8),fallback=defaultCoordinates(instance,pet);
    runtime.stage.style.width=`${width}px`;runtime.stage.style.height=`${instance.size}px`;
    const x=instance.position?8+instance.position.x*(maxX-8):fallback.x,y=instance.position?8+instance.position.y*(maxY-8):fallback.y;
    runtime.stage.style.left=`${Math.max(8,Math.min(maxX,x))}px`;runtime.stage.style.top=`${Math.max(8,Math.min(maxY,y))}px`;runtime.stage.style.bottom='auto';
    if(!avoidPanel||panel.hidden||drag)return;const popup=panel.getBoundingClientRect(),box=runtime.stage.getBoundingClientRect();
    if(box.right<=popup.left||box.left>=popup.right||box.bottom<=popup.top||box.top>=popup.bottom)return;
    if(popup.right+width+20<=innerWidth)runtime.stage.style.left=`${popup.right+12}px`;else if(popup.left>=width+20)runtime.stage.style.left=`${popup.left-width-12}px`;else runtime.stage.style.top=`${Math.max(8,popup.top-instance.size-10)}px`;
  }
  function positionAll(){if(!panel)return;panel.style.right='56px';panel.style.bottom='12px';state.instances.forEach(instance=>positionOne(instance,runtimes.get(instance.instanceId),instance.instanceId===state.selectedInstanceId));}
  function rememberPosition(instance,x,y){const width=widthFor(instance,petFor(instance));instance.position={x:Math.max(0,Math.min(1,(x-8)/Math.max(1,innerWidth-width-16))),y:Math.max(0,Math.min(1,(y-8)/Math.max(1,innerHeight-instance.size-16)))};}
  function endDrag(cancel=false){if(!drag)return;const current=drag,instance=state.instances.find(item=>item.instanceId===current.instanceId),runtime=runtimes.get(current.instanceId);drag=null;if(cancel&&instance)instance.position=current.previous;if(runtime?.stage.hasPointerCapture(current.id))runtime.stage.releasePointerCapture(current.id);runtime?.stage.classList.remove('is-dragging');persist();positionAll();}
  function selectInstance(id){if(!state.instances.some(item=>item.instanceId===id))return;state.selectedInstanceId=id;if(instanceSelect)instanceSelect.value=id;persist();renderControls();positionAll();}
  function startDrag(instance,runtime,event){if(event.button!==0||!event.isPrimary)return;selectInstance(instance.instanceId);const rect=runtime.stage.getBoundingClientRect();drag={instanceId:instance.instanceId,id:event.pointerId,dx:event.clientX-rect.left,dy:event.clientY-rect.top,previous:instance.position};rememberPosition(instance,rect.left,rect.top);setOpen(false);runtime.stage.setPointerCapture(event.pointerId);runtime.stage.classList.add('is-dragging');runtime.stage.focus({preventScroll:true});event.preventDefault();}
  function moveDrag(event){if(!drag||event.pointerId!==drag.id)return;const instance=state.instances.find(item=>item.instanceId===drag.instanceId);if(!instance)return;rememberPosition(instance,event.clientX-drag.dx,event.clientY-drag.dy);positionAll();event.preventDefault();}
  function moveKeys(instance,runtime,event){if(event.key==='Escape'&&drag?.instanceId===instance.instanceId){endDrag(true);event.preventDefault();return;}const steps={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]},step=steps[event.key];if(!step)return;selectInstance(instance.instanceId);const rect=runtime.stage.getBoundingClientRect(),pixels=event.shiftKey?24:8;rememberPosition(instance,rect.left+step[0]*pixels,rect.top+step[1]*pixels);persist();positionAll();event.preventDefault();event.stopPropagation();}
  function makeRuntime(instance){
    const stage=node('div',{class:'biggy-pet-sprite',role:'img',tabindex:'0','data-instance-id':instance.instanceId,'aria-description':'Drag to move. Use arrow keys to adjust position; Shift moves faster.',title:'Drag to move object'});stage.hidden=true;document.body.appendChild(stage);
    const runtime={stage,timer:0,frame:0,loaded:false,serial:0,spriteUrl:''};runtimes.set(instance.instanceId,runtime);
    stage.addEventListener('pointerdown',event=>startDrag(instance,runtime,event));stage.addEventListener('pointermove',moveDrag);
    stage.addEventListener('pointerup',event=>{if(drag?.instanceId===instance.instanceId&&drag.id===event.pointerId)endDrag();});
    stage.addEventListener('pointercancel',event=>{if(drag?.instanceId===instance.instanceId&&drag.id===event.pointerId)endDrag(true);});
    stage.addEventListener('lostpointercapture',event=>{if(drag?.instanceId===instance.instanceId&&drag.id===event.pointerId)endDrag(true);});stage.addEventListener('keydown',event=>moveKeys(instance,runtime,event));return runtime;
  }
  function removeRuntime(id){const runtime=runtimes.get(id);stop(runtime);runtime?.stage.remove();runtimes.delete(id);}
  async function loadSprite(instance){
    const runtime=runtimes.get(instance.instanceId)||makeRuntime(instance),pet=petFor(instance),serial=++runtime.serial;runtime.loaded=false;runtime.frame=0;stop(runtime);runtime.stage.style.backgroundImage='none';if(!pet){render();return;}
    const img=new Image();img.src=pet.spriteUrl;
    try{await img.decode();if(destroyed||serial!==runtime.serial||!state.instances.includes(instance))return;if(img.naturalWidth!==pet.columns*pet.frameWidth||img.naturalHeight!==pet.rows*pet.frameHeight)throw new Error('grid');runtime.stage.style.backgroundImage=`url("${pet.spriteUrl}")`;runtime.stage.style.backgroundSize=`${pet.columns*100}% ${pet.rows*100}%`;runtime.stage.style.backgroundPosition='0% 0%';runtime.spriteUrl=pet.spriteUrl;runtime.loaded=true;status.textContent='Local objects ready. No voice or AI calls.';}
    catch(_){if(destroyed||serial!==runtime.serial)return;runtime.loaded=false;status.textContent=`${displayLabel(instance)} sprite is unavailable or does not match its manifest.`;}render();
  }
  function syncRuntimes(){const ids=new Set(state.instances.map(item=>item.instanceId));[...runtimes.keys()].filter(id=>!ids.has(id)).forEach(removeRuntime);state.instances.forEach(instance=>{const runtime=runtimes.get(instance.instanceId)||makeRuntime(instance),pet=petFor(instance);if(pet&&runtime.spriteUrl!==pet.spriteUrl){runtime.spriteUrl=pet.spriteUrl;loadSprite(instance);}});}
  function addObject(){const pet=pets.find(item=>item.id===catalogSelect.value);if(!pet)return;const instance={instanceId:newId(pet.id),catalogId:pet.id,enabled:true,size:pet.id==='biggy'?256:128,position:null,animation:animationDefault(pet.id)};state.instances.push(instance);state.catalogId=pet.id;state.selectedInstanceId=instance.instanceId;persist();render();}
  function removeSelected(){const instance=selectedInstance();if(!instance)return;if(drag?.instanceId===instance.instanceId)endDrag(true);state.instances=state.instances.filter(item=>item!==instance);removeRuntime(instance.instanceId);state.selectedInstanceId=state.instances[0]?.instanceId||'';persist();render();}
  function renderControls(){
    if(!panel)return;const instance=selectedInstance(),pet=petFor(instance);instanceSelect.replaceChildren();state.instances.forEach(item=>instanceSelect.appendChild(node('option',{value:item.instanceId},`${displayLabel(item)} — ${item.enabled?'on':'off'}`)));if(!state.instances.length)instanceSelect.appendChild(node('option',{},'No objects on screen'));instanceSelect.disabled=!state.instances.length;instanceSelect.value=state.selectedInstanceId;
    [toggle,removeButton,range,speed,pause,random,resetPosition].forEach(control=>{control.disabled=!instance;});toggle.textContent=instance?.enabled?'Hide selected':'Show selected';toggle.setAttribute('aria-pressed',String(instance?.enabled===true));
    if(instance){range.value=String(instance.size);output.textContent=`${instance.size}px`;const settings=normalizeAnimation(instance.animation,instance.catalogId);speed.value=String(settings.speed);speedOutput.textContent=`${settings.speed}%`;pause.value=String(settings.pause);pauseOutput.textContent=`${settings.pause}s`;random.checked=settings.random;resetPosition.textContent=pet?.defaultAnchor==='dialog-right'?'Place right of dialog':'Place above Message Biggy';}else{output.textContent='—';speedOutput.textContent='—';pauseOutput.textContent='—';random.checked=false;}
    showAllButton.disabled=!state.instances.length;hideAllButton.disabled=!state.instances.length;
  }
  function render(){
    if(!root)return;syncRuntimes();renderControls();const visible=state.instances.filter(instance=>instance.enabled&&runtimes.get(instance.instanceId)?.loaded).length;button.classList.toggle('is-active',visible>0);button.setAttribute('aria-label',`Pet and object controls: ${visible} visible`);
    runtimes.forEach((runtime,id)=>{const instance=state.instances.find(item=>item.instanceId===id),pet=petFor(instance);runtime.stage.hidden=!instance?.enabled||!runtime.loaded||!pet;runtime.stage.setAttribute('aria-label',instance?displayLabel(instance):'Object');runtime.stage.classList.toggle('is-selected',id===state.selectedInstanceId);if(instance)animate(instance,runtime);});positionAll();
  }
  async function refresh(){
    if(loading)return;const serial=++catalogRequest,controller=new AbortController();catalogAbort=controller;const timeout=setTimeout(()=>controller.abort(),5000);loading=true;status.textContent='Loading local objects…';
    try{const response=await fetch('/api/biggy/pets',{cache:'no-store',signal:controller.signal});if(!response.ok)throw new Error('catalog');const payload=await response.json();if(destroyed||serial!==catalogRequest)return;pets=(Array.isArray(payload.pets)?payload.pets:[]).filter(pet=>ID.test(pet.id)&&Number.isInteger(pet.columns)&&pet.columns>=1&&pet.columns<=32&&Number.isInteger(pet.rows)&&pet.rows>=1&&pet.rows<=11&&Number.isInteger(pet.idleFrames)&&pet.idleFrames>=1&&pet.idleFrames<=pet.columns&&[pet.frameWidth,pet.frameHeight].every(n=>Number.isInteger(n)&&n>=1&&n<=2048)&&Array.isArray(pet.frameDurations)&&pet.frameDurations.length===pet.idleFrames&&pet.frameDurations.every(n=>Number.isInteger(n)&&n>=40&&n<=10000)&&new RegExp(`^/api/biggy/pets/${pet.id}/sprite\\?v=[a-f0-9]+$`).test(pet.spriteUrl));catalogSelect.replaceChildren();pets.forEach(pet=>catalogSelect.appendChild(node('option',{value:pet.id},pet.displayName)));if(!pets.length)catalogSelect.appendChild(node('option',{},'No compatible objects'));if(!pets.some(pet=>pet.id===state.catalogId))state.catalogId=pets[0]?.id||'';catalogSelect.value=state.catalogId;catalogSelect.disabled=!pets.length;addButton.disabled=!pets.length;runtimes.forEach(runtime=>{runtime.spriteUrl='';});syncRuntimes();status.textContent=pets.length?'Local objects ready. No voice or AI calls.':'Add a compatible local object, then refresh.';persist();render();}
    catch(_){if(destroyed||serial!==catalogRequest)return;pets=[];runtimes.forEach(runtime=>{stop(runtime);runtime.loaded=false;});status.textContent='Local objects unavailable. Refresh to retry.';render();}
    finally{clearTimeout(timeout);if(serial===catalogRequest){loading=false;if(!destroyed)render();}}
  }
  function setOpen(open){panel.hidden=!open;button.setAttribute('aria-expanded',String(open));positionAll();if(open)(instanceSelect.disabled?catalogSelect:instanceSelect).focus();}
  function outside(event){if(root&&!root.contains(event.target)&&!panel.contains(event.target))setOpen(false);}
  function keydown(event){if(event.key==='Escape'&&panel&&!panel.hidden){setOpen(false);button.focus();}}
  function mount(deck){
    const rail=document.getElementById('biggyCategoryRail');if(!deck||!rail)return;if(root){if(root.parentElement!==rail)rail.appendChild(root);positionAll();return;}destroyed=false;root=node('div',{id:'biggyPets',class:'biggy-pets'});button=node('button',{type:'button',class:'biggy-pets-button','aria-expanded':'false','aria-controls':'biggyPetPanel'},'PET');panel=node('section',{id:'biggyPetPanel',class:'biggy-pet-panel biggy-pets','aria-label':'Pet and object controls'});panel.hidden=true;
    catalogSelect=node('select',{id:'biggyPetCatalogSelect','aria-label':'Available object'});addButton=node('button',{type:'button'},'Add object');const addRow=node('div',{class:'biggy-pet-actions'});addRow.append(catalogSelect,addButton);
    instanceSelect=node('select',{id:'biggyPetInstanceSelect','aria-label':'On-screen object'});const actions=node('div',{class:'biggy-pet-actions'});toggle=node('button',{type:'button','aria-pressed':'false'},'Show selected');removeButton=node('button',{type:'button'},'Remove selected');actions.append(toggle,removeButton);
    const allActions=node('div',{class:'biggy-pet-actions'});showAllButton=node('button',{type:'button'},'Show all');hideAllButton=node('button',{type:'button'},'Hide all');allActions.append(showAllButton,hideAllButton);const reload=node('button',{type:'button',class:'biggy-pet-reset','aria-label':'Refresh local objects'},'Refresh local objects');resetPosition=node('button',{type:'button',class:'biggy-pet-reset'},'Place above Message Biggy');
    range=node('input',{id:'biggyPetSize',type:'range',min:'64',max:'448',step:'8','aria-label':'Object size'});output=node('output',{for:'biggyPetSize'});speed=node('input',{id:'biggyPetSpeed',type:'range',min:'25',max:'150',step:'5','aria-label':'Animation speed'});speedOutput=node('output',{for:'biggyPetSpeed'});pause=node('input',{id:'biggyPetPause',type:'range',min:'0',max:'20',step:'1','aria-label':'Pause between animations'});pauseOutput=node('output',{for:'biggyPetPause'});random=node('input',{id:'biggyPetRandom',type:'checkbox'});const randomLabel=node('label',{for:'biggyPetRandom',class:'biggy-pet-random'});randomLabel.append(random,document.createTextNode(' Random timing'));status=node('p',{role:'status'});
    panel.append(node('label',{for:'biggyPetCatalogSelect'},'ADD PET / OBJECT'),addRow,node('label',{for:'biggyPetInstanceSelect'},'ON-SCREEN OBJECTS'),instanceSelect,actions,allActions,node('label',{for:'biggyPetSize'},'SELECTED SIZE'),range,output,resetPosition,node('label',{for:'biggyPetSpeed'},'ANIMATION SPEED'),speed,speedOutput,node('label',{for:'biggyPetPause'},'PAUSE BETWEEN ANIMATIONS'),pause,pauseOutput,randomLabel,node('p',{},'Each object keeps its own size, position, visibility and timing. Drag or use arrow keys to place the selected object.'),reload,status);
    root.append(button);rail.appendChild(root);document.body.appendChild(panel);button.addEventListener('click',()=>setOpen(panel.hidden));catalogSelect.addEventListener('change',()=>{state.catalogId=catalogSelect.value;persist();});addButton.addEventListener('click',addObject);instanceSelect.addEventListener('change',()=>selectInstance(instanceSelect.value));toggle.addEventListener('click',()=>{const instance=selectedInstance();if(!instance)return;instance.enabled=!instance.enabled;persist();render();});removeButton.addEventListener('click',removeSelected);showAllButton.addEventListener('click',()=>{state.instances.forEach(item=>{item.enabled=true;});persist();render();});hideAllButton.addEventListener('click',()=>{state.instances.forEach(item=>{item.enabled=false;});persist();render();});reload.addEventListener('click',refresh);resetPosition.addEventListener('click',()=>{const instance=selectedInstance();if(!instance)return;instance.position=null;persist();positionAll();});range.addEventListener('input',()=>{const instance=selectedInstance();if(!instance)return;instance.size=clampSize(range.value);persist();render();});const updateAnimation=()=>{const instance=selectedInstance();if(!instance)return;instance.animation={speed:Number(speed.value),pause:Number(pause.value),random:random.checked};persist();render();};speed.addEventListener('input',updateAnimation);pause.addEventListener('input',updateAnimation);random.addEventListener('change',updateAnimation);
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',keydown);document.addEventListener('visibilitychange',render);window.addEventListener('resize',positionAll);reduced.addEventListener('change',render);observer=new ResizeObserver(positionAll);observer.observe(deck);const lane=document.getElementById('biggyArgusConversationLane');if(lane)observer.observe(lane);visibilityObserver=new MutationObserver(()=>{if(!document.getElementById('mainChat')?.classList.contains('biggy-pa-rail-open'))setOpen(false);positionAll();});const main=document.getElementById('mainChat');if(main)visibilityObserver.observe(main,{attributes:true,attributeFilter:['class']});refresh();
  }
  function unmount(){endDrag(true);destroyed=true;catalogRequest+=1;catalogAbort?.abort();loading=false;runtimes.forEach(runtime=>{stop(runtime);runtime.stage.remove();});runtimes.clear();observer?.disconnect();visibilityObserver?.disconnect();document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',keydown);document.removeEventListener('visibilitychange',render);window.removeEventListener('resize',positionAll);reduced.removeEventListener('change',render);root?.remove();panel?.remove();root=null;}
  window.BiggyPets={mount,unmount};
})();
