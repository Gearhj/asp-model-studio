interface ImportMetaEnv {
  readonly VITE_APP_TARGET?: "scheduling" | "modeling";
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*.png" {
  const src: string;
  export default src;
}
declare module "*.ico" {
  const src: string;
  export default src;
}
// @types/d3 (installed for the Visual Intelligence Foundation, Phase B) now provides
// real types for "d3" -- the previous `declare module "d3";` ambient shim silently
// widened every d3 import to `any` and has been removed so real type-checking applies.
declare module "*?url" {
  const src: string;
  export default src;
}
