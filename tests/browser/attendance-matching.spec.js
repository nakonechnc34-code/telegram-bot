const { test, expect } = require('@playwright/test');

async function openRegistry(page, allowed = true) {
  const entries = [{kind:'employees',source:'old',target:'99',stale:true}];
  const history = [];
  const employees = [{id:'1',full_name:'Test Alpha',personnel_number:'021'},{id:'2',full_name:'Test Beta',personnel_number:'042'}];
  const restaurants = [{id:'a',name:'Test Restaurant'}];
  await page.addInitScript(() => sessionStorage.setItem('wokker_timesheet_token','test-token'));
  await page.route('**/api/timesheet/**', async route => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    let data = {};
    if (path.endsWith('/restaurants')) data = {restaurants:[{key:'a',name:'Test Restaurant'}]};
    else if (path.endsWith('/matching')) {
      if (!allowed) return route.fulfill({status:403,json:{error:'Forbidden'}});
      if (req.method() !== 'GET') {
        const value = req.postDataJSON();
        const index = entries.findIndex(e => e.kind === value.kind && e.source === value.source);
        const previous = index < 0 ? null : entries[index].target;
        if (index >= 0) entries.splice(index,1);
        if (req.method() === 'POST') entries.push({...value,stale:false});
        history.unshift({...value,previous_target:previous,new_target:req.method()==='POST'?value.target:null,actor_id:1,created_at:'2026-11-28'});
      }
      data = {entries,history,employees,restaurants};
    } else data = {employees:[],restaurants:[],imports:[],history:[],records:[]};
    await route.fulfill({json:data});
  });
  await page.goto('/timesheet.html');
  await page.locator('nav [data-page="6"]').click();
}

test('matching registry search, create, update, delete and history', async ({page}) => {
  await openRegistry(page);
  const registry = page.locator('#matching-registry');
  await expect(registry).toBeVisible();
  await expect(registry).toContainText('Устарело');
  const search = page.locator('#registry-search');
  const target = registry.locator('select[name="target"]');
  await search.fill('Alpha');
  await expect(target.locator('option')).toHaveCount(2);
  await search.fill('042');
  await expect(target.locator('option')).toHaveCount(2);
  await target.selectOption('2');
  await registry.locator('input[name="source"]').fill('new');
  await registry.getByRole('button',{name:'Сохранить соответствие'}).click();
  const row = page.locator('#registry-rows tr').filter({hasText:'new'});
  await expect(row).toContainText('Активно');
  await row.getByRole('button',{name:'Изменить'}).click();
  await target.selectOption('1');
  await registry.getByRole('button',{name:'Сохранить соответствие'}).click();
  await expect(row.locator('td').nth(2)).toHaveText('1');
  page.once('dialog', dialog => dialog.accept());
  await row.getByRole('button',{name:'Удалить'}).click();
  await expect(row).toHaveCount(0);
  await expect(page.locator('#registry-history tr')).toHaveCount(3);
  await registry.locator('select[name="kind"]').selectOption('restaurants');
  await expect(target.locator('option[value="a"]')).toHaveText('Test Restaurant');
});

test('matching registry remains hidden on forbidden response', async ({page}) => {
  const response = page.waitForResponse(r => r.url().endsWith('/matching'));
  await openRegistry(page,false);
  expect((await response).status()).toBe(403);
  await expect(page.locator('#matching-registry')).toBeHidden();
});
