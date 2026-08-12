// 最小 Node 环境声明：仅供 vite.config.ts 构建期使用（web 包不依赖 @types/node，
// 避免为配置文件的三个函数引入整个类型包；仅覆盖实际用到的 API 面）
declare module 'node:crypto' {
  export function createHash(algorithm: string): {
    update(data: Uint8Array | string): void
    digest(encoding: 'hex'): string
  }
}
declare module 'node:fs' {
  export function existsSync(path: string): boolean
  export function readFileSync(path: string): Uint8Array
  export function readdirSync(path: string): string[]
}
declare module 'node:path' {
  export function resolve(...segments: string[]): string
}
declare const __dirname: string
