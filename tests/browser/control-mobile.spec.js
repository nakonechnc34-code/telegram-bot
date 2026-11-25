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
