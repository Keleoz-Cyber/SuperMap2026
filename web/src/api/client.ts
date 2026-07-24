import type {
  ApiErrorBody,
  BrowserLoadReport,
  CandidatesResponse,
  CaseDatasetsResponse,
  CasesResponse,
  DatasetVersionRecord,
  ExperimentCreatePayload,
  ExperimentRecord,
  FieldMappingPayload,
  HealthResponse,
  InspectionResult,
  PlatformCaseRecord,
  PublishStatus,
  QualityReport,
  RhoCaseDetail,
  RhoPoints,
  RunRecord,
  VoxelCells,
} from './types'

const BASE = '/api'

// 统一的后端错误封套解析：{"error": {"code", "message", "details"}}。
// 任何非 2xx 响应都转 ApiError；成功判定由调用方检查资源状态字段，
// 不能只看 HTTP 200。
export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details: Record<string, unknown>

  constructor(code: string, message: string, status: number, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

async function parseError(resp: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await resp.json()
  } catch {
    // 非 JSON 错误体（代理/网关），落入兜底分支
  }
  const envelope = (body as Partial<ApiErrorBody> | null)?.error
  if (envelope?.code) {
    return new ApiError(envelope.code, envelope.message, resp.status, envelope.details ?? {})
  }
  const detail = (body as { detail?: unknown } | null)?.detail
  const message =
    typeof detail === 'string' ? detail : `请求失败（HTTP ${resp.status}）`
  return new ApiError(`HTTP_${resp.status}`, message, resp.status)
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, init)
  if (!resp.ok) {
    throw await parseError(resp)
  }
  return (await resp.json()) as T
}

function getJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, { headers: { Accept: 'application/json' } })
}

function postJson<T>(path: string, payload: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
  })
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
  await requestJson('/evidence/browser-load', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(report),
  })
}

// ---------------------------------------------------------- v0.4 platform

export function createCase(name: string, caseType = 'generic'): Promise<PlatformCaseRecord> {
  return postJson<PlatformCaseRecord>('/cases', { name, case_type: caseType })
}

export function fetchCase(caseId: string): Promise<PlatformCaseRecord> {
  return getJson<PlatformCaseRecord>(`/cases/${caseId}`)
}

export function uploadDataset(caseId: string, file: File): Promise<DatasetVersionRecord> {
  const form = new FormData()
  form.append('file', file)
  // 不设置 Content-Type，由浏览器生成 multipart 边界
  return requestJson<DatasetVersionRecord>(`/cases/${caseId}/datasets/uploads`, {
    method: 'POST',
    body: form,
  })
}

export function fetchDataset(datasetId: string): Promise<DatasetVersionRecord> {
  return getJson<DatasetVersionRecord>(`/datasets/${datasetId}`)
}

export function fetchInspection(datasetId: string, sheet?: string | null): Promise<InspectionResult> {
  const query = sheet ? `?sheet=${encodeURIComponent(sheet)}` : ''
  return getJson<InspectionResult>(`/datasets/${datasetId}/inspection${query}`)
}

export function postMapping(
  datasetId: string,
  mapping: FieldMappingPayload,
  sheet?: string | null,
): Promise<DatasetVersionRecord> {
  const query = sheet ? `?sheet=${encodeURIComponent(sheet)}` : ''
  return postJson<DatasetVersionRecord>(`/datasets/${datasetId}/mapping${query}`, mapping)
}

export function validateDataset(datasetId: string): Promise<QualityReport> {
  return postJson<QualityReport>(`/datasets/${datasetId}/validate`, {})
}

export function fetchQuality(datasetId: string): Promise<QualityReport> {
  return getJson<QualityReport>(`/datasets/${datasetId}/quality`)
}

export function confirmWarnings(datasetId: string, issueCodes: string[]): Promise<QualityReport> {
  return postJson<QualityReport>(`/datasets/${datasetId}/quality/confirm-warnings`, {
    issue_codes: issueCodes,
  })
}

// ---------------------------------------------------------- v0.4 experiments

export function fetchCaseDatasets(caseId: string): Promise<CaseDatasetsResponse> {
  return getJson<CaseDatasetsResponse>(`/cases/${caseId}/datasets`)
}

export function createExperiment(payload: ExperimentCreatePayload): Promise<ExperimentRecord> {
  return postJson<ExperimentRecord>('/experiments', payload)
}

export function fetchExperiment(experimentId: string): Promise<ExperimentRecord> {
  return getJson<ExperimentRecord>(`/experiments/${experimentId}`)
}

export function startRun(experimentId: string): Promise<RunRecord> {
  return requestJson<RunRecord>(`/experiments/${experimentId}/runs`, { method: 'POST' })
}

export function fetchRun(runId: string): Promise<RunRecord> {
  return getJson<RunRecord>(`/runs/${runId}`)
}

export function cancelRun(runId: string): Promise<RunRecord> {
  return requestJson<RunRecord>(`/runs/${runId}/cancel`, { method: 'POST' })
}

export function retryRun(runId: string): Promise<RunRecord> {
  return requestJson<RunRecord>(`/runs/${runId}/retry`, { method: 'POST' })
}

export function fetchCandidates(experimentId: string): Promise<CandidatesResponse> {
  return getJson<CandidatesResponse>(`/experiments/${experimentId}/candidates`)
}
