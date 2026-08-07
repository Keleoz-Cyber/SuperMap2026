import { createRouter, createWebHashHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import CaseWorkspaceView from '../views/CaseWorkspaceView.vue'
import CaseCreateView from '../views/CaseCreateView.vue'
import DatasetUploadView from '../views/DatasetUploadView.vue'
import DatasetWizardView from '../views/DatasetWizardView.vue'
import ExperimentView from '../views/ExperimentView.vue'
import ProfessionalDiagnosisView from '../views/ProfessionalDiagnosisView.vue'
import ProfessionalAnalysisView from '../views/ProfessionalAnalysisView.vue'
import ResultWorkbenchView from '../views/ResultWorkbenchView.vue'
import CandidateComparisonView from '../views/CandidateComparisonView.vue'
import TrashView from '../views/TrashView.vue'

// 构建产物由 FastAPI StaticFiles 直接托管，hash 模式可避免刷新深链 404。
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/trash', name: 'trash', component: TrashView },
    // v0.7.0：统一案例工作台；/case/resistivity 保留为兼容别名（重定向）
    { path: '/case/resistivity', redirect: '/cases/resistivity' },
    { path: '/cases/:caseId', name: 'case-workspace', component: CaseWorkspaceView },
    { path: '/cases/new', name: 'case-create', component: CaseCreateView },
    {
      path: '/cases/:caseId/datasets/new',
      name: 'dataset-upload',
      component: DatasetUploadView,
    },
    // v0.7.0：微震 DAT 导入路由已移除（CSV 预置案例取代）
    {
      path: '/cases/:caseId/datasets/:datasetId/prepare',
      name: 'dataset-prepare',
      component: DatasetWizardView,
    },
    {
      path: '/cases/:caseId/experiments/new',
      name: 'experiment-create',
      component: ExperimentView,
    },
    {
      path: '/datasets/:datasetId/professional-diagnosis',
      name: 'professional-diagnosis',
      component: ProfessionalDiagnosisView,
    },
    {
      path: '/datasets/:datasetId/candidate-comparison',
      name: 'candidate-comparison',
      component: CandidateComparisonView,
    },
    {
      path: '/experiments/:experimentId',
      name: 'experiment-detail',
      component: ExperimentView,
    },
    {
      path: '/results/:resultId',
      name: 'result-workbench',
      component: ResultWorkbenchView,
    },
    {
      path: '/results/:resultId/evaluation',
      name: 'model-evaluation',
      component: ProfessionalAnalysisView,
    },
    {
      path: '/results/:resultId/professional',
      redirect: (to) => ({
        name: 'model-evaluation',
        params: { resultId: to.params.resultId },
        query: to.query,
      }),
    },
  ],
})

export default router
