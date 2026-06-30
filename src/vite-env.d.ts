interface ImportMetaEnv {
  readonly VITE_APP_TARGET?: "scheduling" | "modeling";
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "d3";
declare module "*.png" {
  const src: string;
  export default src;
}
declare module "*.ico" {
  const src: string;
  export default src;
}
