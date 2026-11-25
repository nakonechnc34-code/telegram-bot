const { test, expect } = require('@playwright/test');

for (const viewport of [{width:1440,height:900},{width:390,height:844}]) {
  test('attendance upload and deletion at '+viewport.width, async ({page}) => {
    await page.setViewportSize(viewport);
    await page.addInitScript(() => sessionStorage.setItem('wokker_timesheet_token','test-token'));
    let saved = false, deletes = 0;
    const record = {id:42,restaurant_key:'a',date_from:'2026-11-16',date_to:'2026-11-16',created_at:'2026-11-16',record_count:1,total_minutes:495};
    await page.route('**/api/timesheet/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let data;
      if(path.endsWith('/restaurants')) data={restaurants:[{key:'a',name:'A'}]};
      else if(path.endsWith('/matrix')) data={employees:[{user_id:1,full_name:'Test Cook',main_restaurant_key:'a',data_by_date:{},imported_by_date:saved?{'2026-11-16':{a:{h:8.25,minutes:495,s:'work',rk:'a',imported:true}}}:{}}]};
      else if(path.endsWith('/preview')) data={ok:true,errors:[],total_minutes:495,records:[{personnel_number:'021',date:'2026-11-16',restaurant_key:'a',shifts:['09:00-17:15'],minutes:495}]};
      else if(path.endsWith('/stage')) {saved=true;data={ok:true,import_id:42,success_count:1};}
      else if(path.endsWith('/history')) data={records:saved?[record]:[]};
      else if(path.endsWith('/delete')) {expect(route.request().postDataJSON()).toEqual({import_id:42,restaurant_key:'a'});deletes++;saved=false;data={ok:true};}
      else return route.abort();
      await route.fulfill({json:data});
    });
    await page.goto('/timesheet.html');
    await page.locator('nav [data-page="6"]').click();
    await page.locator('#import-form input[type=file]').setInputFiles({name:'attendance.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:Buffer.from('mock upload')});
    await page.locator('#import-form button[type=submit]').click();
    await expect(page.locator('#preview-summary')).toContainText('8 ч 15 мин');
    await page.locator('#confirm-attendance').click();
    await expect(page.locator('#attendance-history-rows')).toContainText('№42');
    await page.locator('nav [data-page="1"]').click();
    await page.locator('#date').fill('2026-11-16');
    await page.locator('#date').dispatchEvent('change');
    await expect(page.getByRole('button',{name:'Test Cook 2026-11-16 8:15'})).toBeDisabled();
    await page.locator('#period').selectOption('month');
    await expect(page.getByRole('button',{name:'Test Cook 2026-11-16 8:15'})).toBeDisabled();
    await page.locator('nav [data-page="6"]').click();
    page.once('dialog', d=>d.dismiss());
    await page.getByRole('button',{name:'Удалить отчёт №42 — A'}).click();
    expect(deletes).toBe(0);
    page.once('dialog', d=>d.accept());
    await page.getByRole('button',{name:'Удалить отчёт №42 — A'}).click();
    await expect(page.locator('#attendance-history-status')).toHaveText('Нет загруженных отчётов');
    expect(deletes).toBe(1);
  });
}
