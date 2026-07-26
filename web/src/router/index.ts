import { createRouter, createWebHashHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import RhoCaseView from '../views/RhoCaseView.vue'
import CaseCreateView from '../views/CaseCreateView.vue'
import DatasetWizardView from '../views/DatasetWizardView.vue'
import MicroseismicImportView from '../views/MicroseismicImportView.vue'
import ExperimentView from '../views/ExperimentView.vue'
import ResultWorkbenchView from '../views/ResultWorkbenchView.vue'

// 构建产物由 FastAPI StaticFiles 直接托管，hash 模式可避免刷新深链 404。
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/case/resistivity', name: 'rho-case', component: RhoCaseView },
    { path: '/cases/new', name: 'case-create', component: CaseCreateView },
    {
      path: '/cases/:caseId/microseismic/import',
      name: 'microseismic-import',
      component: MicroseismicImportView,
    },
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
      path: '/experiments/:experimentId',
      name: 'experiment-detail',
      component: ExperimentView,
    },
    {
      path: '/results/:resultId',
      name: 'result-workbench',
      component: ResultWorkbenchView,
    },
  ],
})

export default router
