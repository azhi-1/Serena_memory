import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// Initialize i18next with resource bundles BEFORE any component renders.
// Tests bypass main.jsx where this normally happens.
import i18n from '../i18n/index.js';
import zh from '../i18n/zh.json';

// Overwrite specific English translations with Chinese text that tests assert.
// Tests expect Chinese for auth/error keys, but English for nav keys (app.nav.*).
// By adding to 'en' locale, nav keys keep their English values from en.json,
// while auth/error keys get Chinese translations — no language change needed.
i18n.addResourceBundle('en', 'translation', {
  auth: zh.auth,
  app: {
    error: zh.app.error,
    loading: zh.app.loading,
  },
}, true, true);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});
