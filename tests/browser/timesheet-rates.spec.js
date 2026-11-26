const {test,expect}=require('@playwright/test');
for(const role of ['HR','TU','super']){
 test('hourly rate controls '+role,async({page})=>{
  if(role==='TU')await page.setViewportSize({width:390,height:844});
  const writes=[];
  await page.addInitScript(()=>sessionStorage.setItem('wokker_timesheet_token','test-token'));
  await page.route('**/api/timesheet/**',async route=>{
   const req=route.request(),path=new URL(req.url()).pathname.split('/').pop();
   const data={
    restaurants:{restaurants:[{key:'a',name:'Ресторан А'}]},
    matrix:{employees:[]},
    'rate-employees':{can_manage:role!=='TU',can_request:role==='TU',employees:[{user_id:12,full_name:'Тест Сотрудник',restaurant_key:'a',restaurant_name:'Ресторан А',rate:400,payment_type:'fixed'}]},
    'rate-requests':{requests:[]},'rate-history':{history:[]}
   };
   if(path==='individual-rate'||(path==='rate-requests'&&req.method()==='POST'))writes.push(req.postDataJSON());
   await route.fulfill({json:data[path]||{}});
  });
  await page.goto('/timesheet.html');
  await page.locator('nav [data-page="7"]').click();
  const row=page.locator('#rates-rows tr');
  await expect(row).toContainText('Тест Сотрудник · Оклад');
  await expect(row).toContainText('400');
  await expect(row.getByRole('button',{name:'Изменить',exact:true})).toHaveCount(role==='TU'?0:1);
  await expect(row.getByRole('button',{name:'Запросить',exact:true})).toHaveCount(role==='TU'?1:0);
  await row.getByRole('button',{name:role==='TU'?'Запросить':'Изменить',exact:true}).click();
  const dialog=page.locator('dialog[open]');
  await expect(dialog).toBeVisible();
  await dialog.locator('input[type=number]').fill('450.50');
  if(role==='TU')await dialog.locator('textarea').fill('Повышение квалификации');
  await dialog.getByRole('button',{name:'Подтвердить'}).click();
  await expect.poll(()=>writes.length).toBe(1);
  expect(writes[0]).toEqual(role==='TU'?{user_id:12,proposed_rate:'450.50',reason:'Повышение квалификации'}:{user_id:12,hourly_rate:'450.50'});
  await expect(dialog).toHaveCount(0);
 });
}
