import type {
  BrowserLoadReport,
  CasesResponse,
  HealthResponse,
  PublishStatus,
  RhoCaseDetail,
  RhoPoints,
  VoxelCells,
} from './types'

const BASE = '/api'

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, { headers: { Accept: 'application/json' } })
  if (!resp.ok) {
    throw new Error(`请求失败：${path}（HTTP ${resp.status}）`)
  }
  return (await resp.json()) as T
}

export function fetchHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>('/health')
}

export function fetchCases(): Promise<CasesResponse> {
  return getJson<CasesResponse>('/cases')
}

export function fetchRhoCase(): Promise<RhoCaseDetail> {
  return getJson<RhoCaseDetail>('/cases/resistivity')
}

export function fetchRhoPublishStatus(): Promise<PublishStatus> {
  return getJson<PublishStatus>('/cases/resistivity/publish-status')
}

export function fetchRhoPoints(decimate = 4): Promise<RhoPoints> {
  return getJson<RhoPoints>(`/cases/resistivity/points?decimate=${decimate}`)
}

export function fetchVoxelCells(): Promise<VoxelCells> {
  return getJson<VoxelCells>('/cases/resistivity/voxel-cells')
}

export async function postBrowserLoad(report: BrowserLoadReport): Promise<void> {
  const resp = await fetch(`${BASE}/evidence/browser-load`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(report),
  })
  if (!resp.ok) {
    throw new Error(`浏览器加载回执失败（HTTP ${resp.status}）`)
  }
}
