// v0.9.0：案例差异化表达合同。只承载视觉/叙事元数据，绝不承载统计量；
// 统计与结论一律来自分析 DTO（findings.ts），profile 判定以后端 mapping 为准。

export type CaseProfile = 'resistivity' | 'microseismic_velocity' | 'gas_content' | 'generic_3d'

export interface CasePresentation {
  profile: CaseProfile
  accent: 'gold' | 'violet' | 'jade' | 'cyan'
  variableLabel: string
  narrativeLabel: string
  forbiddenClaims: readonly string[]
}

export const CASE_PRESENTATION: Record<CaseProfile, CasePresentation> = {
  resistivity: {
    profile: 'resistivity',
    accent: 'gold',
    variableLabel: '地下电阻率',
    narrativeLabel: '深层电性结构',
    forbiddenClaims: ['含水结论', '成矿结论'],
  },
  microseismic_velocity: {
    profile: 'microseismic_velocity',
    accent: 'violet',
    variableLabel: '微震速度',
    narrativeLabel: '速度场与方向变化',
    forbiddenClaims: ['震源能量', '时间演化'],
  },
  gas_content: {
    profile: 'gas_content',
    accent: 'jade',
    variableLabel: '煤层瓦斯含量',
    narrativeLabel: '分层含量与采样覆盖',
    forbiddenClaims: ['危险等级', '安全等级', '储量'],
  },
  generic_3d: {
    profile: 'generic_3d',
    accent: 'cyan',
    variableLabel: '自定义属性',
    narrativeLabel: '通用三维属性分析',
    forbiddenClaims: ['专业地质结论'],
  },
}
