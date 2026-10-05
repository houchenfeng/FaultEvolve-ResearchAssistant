/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Web API 基地址。留空表示同源（默认走 Vite proxy / 与前端同域部署）。 */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
