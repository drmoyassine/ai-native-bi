import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    fileParallelism: false,
    testTimeout: 20000,
    hookTimeout: 30000,
    include: ['{apps,packages}/*/src/**/*.test.ts'],
    env: {
      TEST_DATABASE_ADMIN_URL: process.env.TEST_DATABASE_ADMIN_URL ?? 'postgres://postgres:postgres@localhost:5432/postgres',
    },
  },
});
