interface ImportMetaEnv {
  readonly VITE_APP_TARGET?: "scheduling" | "modeling";
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "d3";
