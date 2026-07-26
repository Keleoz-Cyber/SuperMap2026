// 便携合成 22-DAT 生成器：测试运行时现造字节与夹具配置，绝不嵌入私有字节。
//
// DAT 格式与后端 parser 合同一致（tests/microseismic_fixtures.py 同款）：
// ASCII 表头、空白分隔行、CRLF 行尾、每个文件末尾恰好一个 NUL 终止伪行；
// W8.dat 第 2 个数据行的 Vx 为 1.#QNAN0。文件名清单即 config/microseismic.yaml
// 的 expected 清单（公开合同）。夹具期望计数是本夹具自己的 45/44/1/0/44/44，
// 绝不冒充私有 2,006/1,925 证据；黄金哈希由同目录
// calibrate_microseismic_config.py 用真实派生两遍标定（见该文件 docstring）。

import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const CALIBRATOR = path.join(HERE, 'calibrate_microseismic_config.py')

export interface DatSpec {
  fileName: string
  pointId: string
  lineId: string
}

function buildManifest(): DatSpec[] {
  const specs: DatSpec[] = []
  for (let i = 1; i <= 9; i++) specs.push({ fileName: `W${i}.dat`, pointId: `W${i}`, lineId: 'L1' })
  for (let i = 12; i <= 20; i++)
    specs.push({ fileName: `WD${i}-Vx.dat`, pointId: `W${i}`, lineId: 'L2' })
  for (let i = 24; i <= 27; i++)
    specs.push({ fileName: `WD${i}-Vx.dat`, pointId: `W${i}`, lineId: 'L3' })
  return specs
}

export const DAT_MANIFEST: readonly DatSpec[] = buildManifest()

export const DAT_HEADER = '         WL/2(km)          Vx'
export const ROW_A = '        0.050000        0.524804'
export const ROW_B = '        0.055556        0.438684'
export const ROW_QNAN = '        0.060000        1.#QNAN0'
export const QNAN_POINT_ID = 'W8'

// 夹具计数合同：22 文件 × 2 行 + W8 额外 1 个 QNAN 行 = 45 源记录 / 44 有限 /
// 1 无效；取值紧贴使 3σ 零剔除；每点两行深度不同，得 44 个唯一建模节点。
export const FIXTURE_COUNTS = {
  datFiles: 22,
  nulTerminators: 22,
  sourceRecords: 45,
  finiteRecords: 44,
  invalidRecords: 1,
  rejected3sigma: 0,
  acceptedModeling: 44,
  aggregatedNodes: 44,
  lineCounts: { L1: 19, L2: 18, L3: 8 },
} as const

export function datRows(spec: DatSpec): string[] {
  return spec.pointId === QNAN_POINT_ID ? [ROW_A, ROW_QNAN, ROW_B] : [ROW_A, ROW_B]
}

export function datFileBytes(spec: DatSpec): Buffer {
  const text = [DAT_HEADER, ...datRows(spec)].join('\r\n') + '\r\n'
  return Buffer.concat([Buffer.from(text, 'ascii'), Buffer.from([0x00])])
}

/** setInputFiles 直接可用的 22 个 DAT 负载（名字 + 真实合成字节）。 */
export function microseismicUploadPayloads(): Array<{ name: string; mimeType: string; buffer: Buffer }> {
  return DAT_MANIFEST.map((spec) => ({
    name: spec.fileName,
    mimeType: 'application/octet-stream',
    buffer: datFileBytes(spec),
  }))
}

export interface LiveFixturePaths {
  root: string
  configPath: string
  datDir: string
  workDir: string
}

// Live 夹具布局由调用环境钉死：GEOMODELING_MICROSEISMIC_CONFIG 必须指向隔离
// GEOMODELING_DATA_DIR 之内（CI 的 Allocate isolated live runtime 步骤给出）；
// 配置文件允许在服务器启动时尚不存在——后端按请求读取，首个导入请求前现造即可。
export function liveFixturePaths(): LiveFixturePaths {
  const dataDir = process.env.GEOMODELING_DATA_DIR
  const configPath = process.env.GEOMODELING_MICROSEISMIC_CONFIG
  if (!dataDir) {
    throw new Error('Live E2E 微震链路要求调用环境提供唯一的 GEOMODELING_DATA_DIR')
  }
  if (!configPath) {
    throw new Error(
      'Live E2E 微震链路要求调用环境提供 GEOMODELING_MICROSEISMIC_CONFIG（隔离夹具配置路径）',
    )
  }
  const normalizedData = path.resolve(dataDir).toLowerCase()
  const resolvedConfig = path.resolve(configPath)
  if (!resolvedConfig.toLowerCase().startsWith(normalizedData + path.sep)) {
    throw new Error(`GEOMODELING_MICROSEISMIC_CONFIG 必须位于隔离数据目录内：${configPath}`)
  }
  const root = path.dirname(resolvedConfig)
  return {
    root,
    configPath: resolvedConfig,
    datDir: path.join(root, 'dats'),
    workDir: path.join(root, 'calibration'),
  }
}

/** 生成 22 个 DAT 并用真实派生两遍标定夹具配置的黄金哈希（幂等）。 */
export function prepareMicroseismicLiveFixture(): LiveFixturePaths {
  const paths = liveFixturePaths()
  mkdirSync(paths.datDir, { recursive: true })
  for (const spec of DAT_MANIFEST) {
    writeFileSync(path.join(paths.datDir, spec.fileName), datFileBytes(spec))
  }
  try {
    execFileSync('python', [CALIBRATOR, paths.configPath, paths.datDir, paths.workDir], {
      stdio: ['ignore', 'pipe', 'inherit'],
    })
  } catch (error) {
    const stdout = (error as { stdout?: Buffer }).stdout?.toString() ?? ''
    throw new Error(`微震 Live 夹具标定失败：${(error as Error).message}\n${stdout}`)
  }
  if (!existsSync(paths.configPath)) {
    throw new Error(`夹具配置未生成：${paths.configPath}`)
  }
  return paths
}
