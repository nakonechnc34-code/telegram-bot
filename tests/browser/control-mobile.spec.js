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
