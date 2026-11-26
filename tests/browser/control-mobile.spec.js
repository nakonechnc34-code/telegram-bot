const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'../../frontend');
for(const width of [320,375,390,430]){
 test('Control mobile navigation '+width,async({page})=>{
 await page.setViewportSize({width,height:844});
 await page.route('http://control.test/**',async route=>{
 const url=new URL(route.request().url());
 if(url.pathname.startsWith('/api/')){const key=url.pathname.split('/').pop();const data=key==='me'?{full_name:'Test',template_editor:true}:key==='restaurants'?{restaurants:[]}:key==='checks'?{checks:[]}:key==='tasks'?{tasks:[]}:key==='equipment'?{equipment:[]}:key==='rating'?{restaurants:[]}:{};return route.fulfill({json:data});}
 const name=url.pathname==='/'?'control.html':url.pathname.slice(1);
 return route.fulfill({body:fs.readFileSync(path.join(root,name)),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
 await page.addInitScript(()=>sessionStorage.setItem('wokker_control_token','test'));
 await page.goto('http://control.test/');
 await expect(page.locator('.mobile-nav')).toBeVisible();
 await expect(page.locator('.overview-rating')).toBeVisible();
 await page.getByRole('button',{name:'Требуют внимания',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'Требуют внимания'})).toBeVisible();
 await expect(page.getByRole('dialog').getByRole('button',{name:/Просроченные проверки/})).toBeVisible();
 await page.getByRole('dialog').getByRole('button',{name:'Закрыть'}).click();
 await expect(page.getByRole('dialog')).toBeHidden();
 await expect(page.locator('aside')).toBeHidden();
 await page.locator('#mobileMore').click();
 await expect(page.locator('aside')).toBeVisible();
 await page.keyboard.press('Escape');
 await expect(page.locator('aside')).toBeHidden();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
 await page.evaluate(()=>{document.getElementById('home').hidden=true;document.getElementById('tasks').hidden=true;document.getElementById('haccp').hidden=true;});
 await expect(page.locator('.mobile-nav [data-target="tasks"]')).toBeHidden();
 await expect(page.locator('.mobile-overview')).toBeHidden();
 });
}

test('Mystery guest sees only own checks and logout on mobile',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 const calls=[];
 await page.route('http://control.test/**',async route=>{
 const url=new URL(route.request().url());
 if(url.pathname.startsWith('/api/control/')){const key=url.pathname.slice('/api/control/'.length);calls.push(key);if(key==='me')return route.fulfill({json:{full_name:'Тайный гость',mystery_guest:true,template_editor:false}});if(key==='checks')return route.fulfill({json:{checks:[]}});if(key==='logout')return route.fulfill({json:{ok:true}});return route.fulfill({status:403,json:{error:'Нет доступа'}});}
 const name=url.pathname==='/'?'control.html':url.pathname.slice(1);return route.fulfill({body:fs.readFileSync(path.join(root,name)),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
 await page.addInitScript(()=>sessionStorage.setItem('wokker_control_token','guest-test'));
 await page.goto('http://control.test/');
 await expect(page.locator('#checksPanel')).toBeVisible();
 await expect(page.locator('#who')).toHaveText('Тайный гость');
 for(const id of ['home','tasks','haccp'])await expect(page.locator('.mobile-nav [data-target="'+id+'"]')).toBeHidden();
 await expect(page.locator('.mobile-overview')).toBeHidden();
 await page.locator('#mobileMore').click();
 await expect(page.locator('#logout')).toBeVisible();
 await expect(page.locator('#analytics')).toBeHidden();
 await expect(page.locator('#templates')).toBeHidden();
 await page.locator('#logout').click();
 await expect(page.locator('#login')).toBeVisible();
 await expect(page.locator('#who')).toBeEmpty();
 expect(await page.evaluate(()=>sessionStorage.getItem('wokker_control_token'))).toBeNull();
 expect(calls).not.toContain('analytics/rating');
});

for(const [kind,target,list] of [['check_overdue','101','checkList'],['task_critical','202','taskBoard'],['haccp_deviation','303','haccpList']]){
 test('Notification focuses authorized '+kind,async({page})=>{
 await page.setViewportSize({width:390,height:844});
 const notification={id:'1',source_id:kind==='haccp_deviation'?'999':target,equipment_id:kind==='haccp_deviation'?target:null,event_kind:kind,restaurant_key:'a',restaurant_name:'Test restaurant',created_at:'2026-11-26T08:00:00Z',read_at:null};
 await page.route('http://control.test/**',async route=>{
 const url=new URL(route.request().url());
 if(url.pathname.startsWith('/api/control/')){
 const key=url.pathname.slice('/api/control/'.length);
 const data=key==='me'?{full_name:'Test',template_editor:false}:key==='restaurants'?{restaurants:[]}:key==='notifications'?{notifications:[notification],unread:1}:key==='checks'?{checks:[{id:'101',definition:{title:'Target check',sections:[]},restaurant_key:'a',due_at:'2026-11-25T08:00:00Z'}]}:key==='tasks'?{tasks:[{id:'202',status:'new',description:'Target task',restaurant_key:'a',critical:true}],manager:false,user_id:'7'}:key==='haccp/equipment'?{equipment:[{id:'303',name:'Target fridge',restaurant_key:'a',kind:'fridge',unit:'C',lower_limit:2,upper_limit:6}],manager:false}:key==='analytics/rating'?{restaurants:[]}:null;
 return data?route.fulfill({json:data}):route.fulfill({status:403,json:{error:'Нет доступа'}});
 }
 const name=url.pathname==='/'?'control.html':url.pathname.slice(1);
 return route.fulfill({body:fs.readFileSync(path.join(root,name)),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
 await page.addInitScript(()=>sessionStorage.setItem('wokker_control_token','test'));
 await page.goto('http://control.test/');
 await page.getByRole('button',{name:/^Требуют внимания/}).click();
 await expect(page.locator('.notification-history')).toContainText('Test restaurant');
 await page.locator('.notification-history').getByRole('button',{name:'Перейти в раздел'}).click();
 const row=page.locator('#'+list+' [data-notification-source="'+target+'"]');
 await expect(row).toBeVisible();
 await expect(row).toBeFocused();
 await expect(row).toHaveCSS('outline-style','solid');
 await expect(page.getByRole('dialog')).toBeHidden();
 });
}

test('Mobile overview coalesces refresh events with delayed API',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 const calls={};
 await page.route('http://control.test/**',async route=>{
 const url=new URL(route.request().url());
 if(url.pathname.startsWith('/api/control/')){
 const key=url.pathname.slice('/api/control/'.length);
 calls[key]=(calls[key]||0)+1;
 const data=key==='me'?{full_name:'Test',template_editor:false}:key==='restaurants'?{restaurants:[]}:key==='checks'?{checks:[]}:key==='tasks'?{tasks:[]}:key==='haccp/equipment'?{equipment:[]}:key==='analytics/rating'?{restaurants:[]}:key==='notifications'?{notifications:[],unread:0}:{};
 if(key==='analytics/rating')await new Promise(resolve=>setTimeout(resolve,500));
 return route.fulfill({json:data});
 }
 const name=url.pathname==='/'?'control.html':url.pathname.slice(1);
 return route.fulfill({body:fs.readFileSync(path.join(root,name)),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
 await page.addInitScript(()=>sessionStorage.setItem('wokker_control_token','test'));
 await page.goto('http://control.test/');
 await expect(page.locator('.overview-rating')).toBeVisible();
 const before=calls['analytics/rating'];
 await page.evaluate(()=>{
 const title=document.getElementById('title'),home=document.getElementById('home');
 title.textContent='Главная';
 home.hidden=true;
 home.hidden=false;
 title.textContent='Главная';
 });
 await expect.poll(()=>calls['analytics/rating']).toBe(before+1);
 await expect(page.locator('.overview-rating')).toBeVisible();
 expect(calls['analytics/rating']).toBe(before+1);
});
