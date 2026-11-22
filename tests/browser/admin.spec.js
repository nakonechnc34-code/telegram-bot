const { test, expect } = require('@playwright/test');

const admin = {
  full_name: 'Тестовый администратор', login: 'abc12',
  is_super_admin: true, permissions: {},
};
async function mockBackend(page) {
  await page.route('**/api/admin/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/admin/login') {
      return route.fulfill({ json: { token: 'test-only-token' } });
    }
    if (path === '/api/admin/me') {
      return route.fulfill({ json: { profile: admin } });
    }
    // No production data is fetched. Each endpoint receives an empty fixture.
    return route.fulfill({ json: {
      users: [], doctors: [], tests: [], vaccines: [], news: [],
      standards: [], questions: [], restaurants: [], positions: [],
      citizenships: [], admins: [], reports: [], audit: [],
      items: [], data: [], summary: {},
    } });
  });
}
async function login(page) {
  await mockBackend(page);
  await page.goto('/admin.html');
  await page.locator('#login-login').fill('abc12');
  await page.locator('#login-password').fill('test-password');
  await page.locator('#login-btn').click();
  await expect(page.locator('#app')).toBeVisible();
}

test('login and employee tabs work with mocked API', async ({ page }) => {
  await login(page);
  await page.locator('.nav-item[data-page="users"]').click();
  await expect(page.locator('#users-search')).toBeVisible();
  await page.locator('#users-search').fill('Иванов');
  await page.locator('[data-tab="fired"]').click();
  await expect(page.locator('[data-tab="fired"]')).toHaveClass(/active/);
  await expect(page.locator('#page-content')).toHaveAttribute('data-page', 'users');
});

test('medical book tabs and empty states render', async ({ page }) => {
  await login(page);
  await page.locator('.nav-item[data-page="medbooks"]').click();
  for (const tab of ['staff', 'doctors', 'tests', 'vaccines']) {
    await page.locator('[data-mt="' + tab + '"]').click();
    await expect(page.locator('[data-mt="' + tab + '"]')).toHaveClass(/active/);
  }
});

test('mobile navigation opens, switches page and closes', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.locator('#hamburger').click();
  await expect(page.locator('#sidebar')).toHaveClass(/sidebar--open/);
  await page.locator('.nav-item[data-page="users"]').click();
  await expect(page.locator('#page-content')).toHaveAttribute('data-page', 'users');
  await expect(page.locator('#sidebar')).not.toHaveClass(/sidebar--open/);
});

test('restricted admin cannot see administrator navigation', async ({ page }) => {
  await mockBackend(page);
  await page.route('**/api/admin/me', route => route.fulfill({
    json: { profile: { ...admin, is_super_admin: false, is_hr: false, position: 'Менеджер' } },
  }));
  await page.goto('/admin.html');
  await page.locator('#login-login').fill('abc12');
  await page.locator('#login-password').fill('test-password');
  await page.locator('#login-btn').click();
  await expect(page.locator('#app')).toBeVisible();
  await expect(page.locator('#nav-admins')).toBeHidden();
});
