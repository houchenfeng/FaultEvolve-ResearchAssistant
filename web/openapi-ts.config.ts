import { defineConfig } from '@hey-api/openapi-ts';

/**
 * Generates the typed API client from the Python-exported contract.
 *
 * The input is committed (web/openapi/faultevolve.openapi.json) and produced by
 * scripts/export_web_contracts.py, so the generated client can always be
 * regenerated from a clean checkout without a running server.
 */
export default defineConfig({
  input: './openapi/faultevolve.openapi.json',
  output: {
    path: './src/generated/api',
    clean: true,
  },
});
