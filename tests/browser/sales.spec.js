const { test, expect } = require('@playwright/test');

async function openSales(page) {
  await page.addInitScript(() => {
    sessionStorage.setItem('wokker_sales_token', 'test-only-token');
  });
  await page.route('**/api/sales/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/sales/me') {
      return route.fulfill({ json: { full_name: 'Тестовый администратор' } });
    }
    const data = path === '/api/sales/dashboard' ? { overview: {}, imports: [] } : [];
    return route.fulfill({ json: { success: true, data } });
  });
  await page.goto('/sales.html');
  await expect(page.locator('#sales-turnover-chart')).toBeVisible();
}

test('Sales desktop sidebar shows the current section and hides empty reports', async ({ page }) => {
  await openSales(page);
  const sidebar = page.locator('#sales-sidebar');
  await expect(sidebar).toHaveCSS('width', '208px');
  await expect(sidebar.getByRole('button', { name: 'Дашборд' })).toHaveAttribute('aria-current', 'page');
  await expect(sidebar.locator('[data-view="reports"]')).toBeHidden();

  const imports = sidebar.getByRole('button', { name: 'Импорт iiko' });
  await imports.click();
  await expect(imports).toHaveAttribute('aria-current', 'page');
  await expect(page.getByText('История загрузок', { exact: true })).toBeVisible();
});

test('Sales mobile drawer closes by backdrop, Escape and section selection', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openSales(page);
  const menu = page.locator('#menu-toggle');
  const sidebar = page.locator('#sales-sidebar');
  await expect(sidebar).toBeHidden();

  await menu.click();
  await expect(menu).toHaveAttribute('aria-expanded', 'true');
  await expect(sidebar.getByRole('button', { name: 'Закрыть меню' })).toBeFocused();
  await page.mouse.click(380, 200);
  await expect(sidebar).toBeHidden();
  await expect(menu).toBeFocused();

  await menu.click();
  await page.keyboard.press('Escape');
  await expect(sidebar).toBeHidden();
  await expect(menu).toBeFocused();

  await menu.click();
  await sidebar.getByRole('button', { name: 'Импорт iiko' }).click();
  await expect(menu).toHaveAttribute('aria-expanded', 'false');
  await expect(sidebar).toBeHidden();
  await expect(page.getByText('История загрузок', { exact: true })).toBeVisible();
});
