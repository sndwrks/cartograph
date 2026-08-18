/* Ambient declaration so tsc understands `import styles from './X.module.css'`.
   The consuming app's bundler (Vite) does the real CSS-Modules transform. */
declare module "*.module.css" {
  const classes: { readonly [key: string]: string };
  export default classes;
}
