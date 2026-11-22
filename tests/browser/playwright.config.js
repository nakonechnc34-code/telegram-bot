const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.js',
  timeout: 20000,
  retries: 1,
  use: { baseURL: 'http://127.0.0.1:8765', browserName: 'chromium', trace: 'retain-on-failure' },
  webServer: {
    command: 'python3 -m http.server 8765 --directory frontend --bind 127.0.0.1',
    url: 'http://127.0.0.1:8765/admin.html',
    reuseExistingServer: !process.env.CI,
    timeout: 15000,
  },
});
