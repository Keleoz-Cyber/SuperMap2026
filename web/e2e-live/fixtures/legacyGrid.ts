// 共享确定性合成 legacy 网格：supermap-volume-frame-live（CLI 登记 + 隔离帧渲染）
// 与 legacy-volume-live（产品页渲染门）共用同一字节内容；live 套件共享一个隔离
// GEOMODELING_DATA_DIR，builtin_legacy/resistivity 是单例——同一 CSV 保证并发或
// 乱序执行时登记恒幂等（同网格同身份），绝不触发 LEGACY_RENDER_SOURCE_CONFLICT。
export const LEGACY_GRID_SHAPE: [number, number, number] = [6, 7, 8]

export function syntheticLegacyGridCsv(): string {
  const rows = ['x,y,z,value']
  for (let ix = 0; ix < LEGACY_GRID_SHAPE[0]; ix += 1) {
    for (let iy = 0; iy < LEGACY_GRID_SHAPE[1]; iy += 1) {
      for (let iz = 0; iz < LEGACY_GRID_SHAPE[2]; iz += 1) {
        const x = ix * 100
        const y = iy * 100
        const z = -800 + iz * 100
        const value = 310 + 280 * Math.sin(x / 220) * Math.cos(y / 260) + 20 * Math.sin(z / 90)
        rows.push(`${x},${y},${z},${value.toFixed(6)}`)
      }
    }
  }
  return `${rows.join('\n')}\n`
}
