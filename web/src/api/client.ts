import type {
  AnalysisJobRecord,
  AnomalyExtractionAccepted,
  AnomalyExtractionPayload,
  AnomalyExtractionRecord,
  ApiErrorBody,
  CandidateComparisonResult,
  CandidatesResponse,
  CaseDatasetsResponse,
  CasesResponse,
  DatasetVersionRecord,
  ExperimentCreatePayload,
  ExperimentRecord,
  FoldEvidence,
  ProfessionalResultEvidence,
  ResidualEvidence,
  UncertaintyLayerKind,
  UncertaintyPreview,
  FieldMappingPayload,
  HealthResponse,
  InspectionResult,
  DatasetPoints,
  ExportRecord,
  FormalSelectionRecord,
  FormalSelectionsResponse,
  MicroseismicDerivation,
  MicroseismicImportResponse,
  MicroseismicPointLayer,
  MicroseismicPointLayerName,
  PlatformCaseRecord,
  ProfessionalConfirmationPayload,
  ProfessionalConfirmationRecord,
  ProfessionalDiagnosisAccepted,
  ProfessionalDiagnosisRecord,
  ProfessionalDiagnosisRequestPayload,
  PublicationRecord,
  PublishStatus,
  QualityReport,
  RenderAssetRecord,
  RenderCapability,
  ResultMetadata,
  ResultPreview,
  RhoCaseDetail,
  RhoPoints,
  RunRecord,
  SliceResponse,
  VariogramEvidence,
  VoxelCells,
} from './types'

const BASE = '/api'

// 唯一权威演示数据的稳定下载地址（不暴露本机路径）
export const PLATFORM_DEMO_3D_DOWNLOAD_URL = '/api/demo/datasets/platform-demo-3d'

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

// ---------------------------------------------------------- v0.4 results

export function fetchResult(resultId: string): Promise<ResultMetadata> {
  return getJson<ResultMetadata>(`/results/${resultId}`)
}

export function fetchResultPreview(resultId: string): Promise<ResultPreview> {
  return getJson<ResultPreview>(`/results/${resultId}/preview`)
}

export function fetchResultSlice(resultId: string, axis: string, index: number): Promise<SliceResponse> {
  return getJson<SliceResponse>(`/results/${resultId}/slices?axis=${axis}&index=${index}`)
}

export function selectFormal(
  resultId: string,
  note: string,
  selectedBy?: string,
): Promise<FormalSelectionRecord> {
  return postJson<FormalSelectionRecord>(`/results/${resultId}/select-formal`, {
    note,
    selected_by: selectedBy ?? null,
  })
}

export function fetchFormalSelections(caseId: string): Promise<FormalSelectionsResponse> {
  return getJson<FormalSelectionsResponse>(`/cases/${caseId}/formal-selections`)
}

export function createExport(resultId: string): Promise<ExportRecord> {
  return requestJson<ExportRecord>(`/results/${resultId}/exports`, { method: 'POST' })
}

export function createPublication(resultId: string): Promise<PublicationRecord> {
  return requestJson<PublicationRecord>(`/results/${resultId}/publications`, { method: 'POST' })
}

export function fetchDatasetPoints(datasetId: string, decimate = 1): Promise<DatasetPoints> {
  return getJson<DatasetPoints>(`/datasets/${datasetId}/points?decimate=${decimate}`)
}

// ---------------------------------------------------------- v0.5 microseismic

// 微震派生证据只在数据集 profile.source_kind 为该值时存在；
// 成果工作台据此决定是否为成果加载领域证据图层。
export const MICROSEISMIC_SOURCE_KIND = 'microseismic_dat_bundle'

export function importMicroseismic(caseId: string, files: File[]): Promise<MicroseismicImportResponse> {
  const form = new FormData()
  for (const file of files) form.append('files', file, file.name)
  // 不设置 Content-Type，由浏览器生成 multipart 边界
  return requestJson<MicroseismicImportResponse>(`/cases/${caseId}/microseismic-imports`, {
    method: 'POST',
    body: form,
  })
}

export function fetchMicroseismicDerivation(datasetId: string): Promise<MicroseismicDerivation> {
  return getJson<MicroseismicDerivation>(`/datasets/${datasetId}/derivation`)
}

export function fetchMicroseismicDerivationPoints(
  datasetId: string,
  layer: MicroseismicPointLayerName,
  decimate = 1,
): Promise<MicroseismicPointLayer> {
  return getJson<MicroseismicPointLayer>(
    `/datasets/${datasetId}/derivation/points?layer=${layer}&decimate=${decimate}`,
  )
}

// ---------------------------------------------------------- v0.6 professional

// 诊断/异常提取是长任务：POST 返回 202 + 任务身份（幂等成功 200，reused=true），
// 前端只轮询任务与读取证据，绝不在浏览器计算统计结果。

export function requestProfessionalDiagnosis(
  datasetId: string,
  payload: ProfessionalDiagnosisRequestPayload,
): Promise<ProfessionalDiagnosisAccepted> {
  return postJson<ProfessionalDiagnosisAccepted>(
    `/datasets/${datasetId}/professional-diagnostics`,
    payload,
  )
}

export function fetchProfessionalDiagnosis(diagnosisId: string): Promise<ProfessionalDiagnosisRecord> {
  return getJson<ProfessionalDiagnosisRecord>(`/professional-diagnostics/${diagnosisId}`)
}

export function fetchDiagnosisVariogram(diagnosisId: string, decimate = 1): Promise<VariogramEvidence> {
  return getJson<VariogramEvidence>(
    `/professional-diagnostics/${diagnosisId}/variogram?decimate=${decimate}`,
  )
}

// 确认快照只新建（201）：不可变，无任何更新/编辑入口
export function confirmProfessionalDiagnosis(
  diagnosisId: string,
  payload: ProfessionalConfirmationPayload,
): Promise<ProfessionalConfirmationRecord> {
  return postJson<ProfessionalConfirmationRecord>(
    `/professional-diagnostics/${diagnosisId}/confirm`,
    payload,
  )
}

export function fetchAnalysisJob(jobId: string): Promise<AnalysisJobRecord> {
  return getJson<AnalysisJobRecord>(`/analysis-jobs/${jobId}`)
}

// 重试产生新任务身份（retry_of_job_id 回指原任务），原记录不改写
export function retryAnalysisJob(jobId: string): Promise<AnalysisJobRecord> {
  return requestJson<AnalysisJobRecord>(`/analysis-jobs/${jobId}/retry`, { method: 'POST' })
}

// 成果专业证据：legacy 候选 available=false 只携带 reason，绝不伪造能力
export function fetchProfessionalResult(resultId: string): Promise<ProfessionalResultEvidence> {
  return getJson<ProfessionalResultEvidence>(`/results/${resultId}/professional`)
}

export function fetchResultFolds(resultId: string): Promise<FoldEvidence> {
  return getJson<FoldEvidence>(`/results/${resultId}/folds`)
}

export function fetchResultResiduals(resultId: string, decimate = 1): Promise<ResidualEvidence> {
  return getJson<ResidualEvidence>(`/results/${resultId}/residuals?decimate=${decimate}`)
}

// 能力不适用（IDW 请求 kriging_std）后端 409；前端按 capabilities 先验拦截，绝不伪造 0 场
export function fetchResultUncertainty(
  resultId: string,
  kind: UncertaintyLayerKind,
): Promise<UncertaintyPreview> {
  return getJson<UncertaintyPreview>(`/results/${resultId}/uncertainty/${kind}`)
}

export function requestAnomalyExtraction(
  resultId: string,
  payload: AnomalyExtractionPayload,
): Promise<AnomalyExtractionAccepted> {
  return postJson<AnomalyExtractionAccepted>(`/results/${resultId}/anomaly-extractions`, payload)
}

export function fetchAnomalyExtraction(extractionId: string): Promise<AnomalyExtractionRecord> {
  return getJson<AnomalyExtractionRecord>(`/anomaly-extractions/${extractionId}`)
}

// 比较结论以 comparison_fingerprint 登记（幂等）；前端不自行判断兼容
export function createProfessionalComparison(
  firstResultId: string,
  secondResultId: string,
): Promise<CandidateComparisonResult> {
  return postJson<CandidateComparisonResult>('/professional-comparisons', {
    first_result_id: firstResultId,
    second_result_id: secondResultId,
  })
}

export function fetchProfessionalComparison(fingerprint: string): Promise<CandidateComparisonResult> {
  return getJson<CandidateComparisonResult>(`/professional-comparisons/${fingerprint}`)
}

// ---------------------------------------------------------- v0.6.1 native volume rendering

// POST 是唯一显式变异（物化/资产创建/失败重试）；能力与资产状态刷新一律纯 GET，
// 绝不隐式 POST。failed/interrupted 资产只在 retry_failed=true 时重建。

export function materializeResult(resultId: string): Promise<ResultMetadata> {
  return requestJson<ResultMetadata>(`/results/${resultId}/materialize`, { method: 'POST' })
}

export function fetchResultRenderCapability(resultId: string): Promise<RenderCapability> {
  return getJson<RenderCapability>(`/results/${resultId}/render-capability`)
}

export function createResultRenderAsset(resultId: string, retryFailed = false): Promise<RenderAssetRecord> {
  return postJson<RenderAssetRecord>(`/results/${resultId}/render-assets/netcdf`, {
    retry_failed: retryFailed,
  })
}

export function fetchResultRenderAsset(resultId: string): Promise<RenderAssetRecord> {
  return getJson<RenderAssetRecord>(`/results/${resultId}/render-assets/netcdf`)
}

export function fetchLegacyRhoRenderCapability(): Promise<RenderCapability> {
  return getJson<RenderCapability>('/cases/resistivity/render-capability')
}

export function createLegacyRhoRenderAsset(retryFailed = false): Promise<RenderAssetRecord> {
  return postJson<RenderAssetRecord>('/cases/resistivity/render-assets/netcdf', {
    retry_failed: retryFailed,
  })
}

export function fetchLegacyRhoRenderAsset(): Promise<RenderAssetRecord> {
  return getJson<RenderAssetRecord>('/cases/resistivity/render-assets/netcdf')
}
