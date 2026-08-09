// v0.8.0 第三批 Task 9：瓦斯含量预置（case_id=gas）的 live 进程夹具。
//
// 与电阻率/微震 live 规格内联 seed 同一纪律，抽成夹具供
// gas-preset-live.spec.ts 的渲染门与四缓存场景门共用：
//   1. seedGasPreset——execFileSync 调用唯一生产入口
//      `python -m geomodeling.preset_cli seed-gas --data-dir <隔离目录>`
//      （PYTHONPATH 钉住仓库 src；--source 缺省为项目内 example_data/
//      瓦斯含量_合格样品.csv 内置源，无需任何外部私有源或环境变量），
//      解析输出最后一行 JSON 并校验官方成果身份；
//   2. ensureGasRenderAsset——POST /api/results/<id>/render-assets/netcdf
//      （201 首建 / 200 幂等），返回 ready 资产身份；任何非 ready/身份缺失
//      直接抛错——空资产标 ready 绝不允许。
//
// 输出校验沿用 CLI 公共合同：JSON 只含逻辑身份与 SHA-256，绝无本机绝对
// 路径；瓦斯官方成果 seed 即物化（materialized=true）。

import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
// 夹具位于 e2e-live/fixtures/（比规格文件深一级）：仓库根需上溯三级；
// 错误的仓库根会把 PYTHONPATH 指到 web/src，使 python 回落到可编辑安装的
// 旧 worktree（其 preset_cli 没有 seed-gas 命令）。
const REPO_ROOT = path.resolve(HERE, '../../..')

export interface GasSeedRecord {
  case_id: string
  workspace_kind: string
  dataset_version_id: string
  experiment_id: string
  run_id: string
  official_result: { result_id: string; url: string; materialized: boolean }
  source_sha256: string
  baseline_sha256: string
}

export interface GasAssetIdentity {
  id: string
  source_kind: string
  source_id: string
  renderer: string
  status: string
  grid_sha256: string
  netcdf_sha256: string
  manifest_url: string
  netcdf_url: string
}

/** seed-gas（幂等）：在隔离数据目录建立只读瓦斯预置官方链并返回官方成果身份。 */
export function seedGasPreset(dataDir: string): GasSeedRecord {
  const stdout = execFileSync(
    process.env.PYTHON ?? 'python',
    ['-m', 'geomodeling.preset_cli', 'seed-gas', '--data-dir', dataDir],
    {
      cwd: REPO_ROOT,
      encoding: 'utf8',
      env: { ...process.env, PYTHONPATH: path.join(REPO_ROOT, 'src') },
      timeout: 600_000,
    },
  )
  const seeded = JSON.parse(stdout.trim().split('\n').pop()!) as GasSeedRecord
  if (seeded.case_id !== 'gas' || seeded.workspace_kind !== 'builtin_preset') {
    throw new Error(`seed-gas 身份不符：${JSON.stringify(seeded)}`)
  }
  if (!seeded.official_result?.result_id || seeded.official_result.materialized !== true) {
    throw new Error(`seed-gas 官方成果缺失或未物化：${JSON.stringify(seeded.official_result)}`)
  }
  if (!/^[0-9a-f]{64}$/.test(seeded.source_sha256)) {
    throw new Error(`seed-gas 源 SHA-256 非法：${seeded.source_sha256}`)
  }
  // CLI 公共合同：输出只含逻辑身份与哈希，绝无本机绝对路径
  if (/[A-Za-z]:[\\/]/.test(JSON.stringify(seeded))) {
    throw new Error('seed-gas 输出泄露本机绝对路径')
  }
  return seeded
}

/** 显式创建/复用官方成果的 NetCDF 渲染资产；status 必须为 ready（空资产标 ready 判失败）。 */
export async function ensureGasRenderAsset(
  baseUrl: string,
  resultId: string,
): Promise<GasAssetIdentity> {
  const resp = await fetch(`${baseUrl}/api/results/${resultId}/render-assets/netcdf`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: '{}',
  })
  if (resp.status !== 200 && resp.status !== 201) {
    throw new Error(`POST render-assets/netcdf 非 200/201：${resp.status} ${await resp.text()}`)
  }
  const asset = (await resp.json()) as GasAssetIdentity
  if (asset.status !== 'ready') {
    throw new Error(`瓦斯渲染资产未 ready：${JSON.stringify(asset)}`)
  }
  if (asset.source_kind !== 'candidate_result' || asset.source_id !== resultId) {
    throw new Error(`瓦斯渲染资产源身份不符：${JSON.stringify(asset)}`)
  }
  if (!/^nc-[0-9a-f]{32}$/.test(asset.id)) {
    throw new Error(`瓦斯渲染资产 ID 形态非法：${asset.id}`)
  }
  if (!/^[0-9a-f]{64}$/.test(asset.grid_sha256) || !/^[0-9a-f]{64}$/.test(asset.netcdf_sha256)) {
    throw new Error(`瓦斯渲染资产哈希非法：${JSON.stringify(asset)}`)
  }
  return asset
}
