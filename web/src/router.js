import { createRouter, createWebHistory } from 'vue-router'

import OverviewView from './views/OverviewView.vue'
import HomeView from './views/HomeView.vue'
import CapabilityView from './views/CapabilityView.vue'
import BlockView from './views/BlockView.vue'
import BlockDiffView from './views/BlockDiffView.vue'
import CRListView from './views/CRListView.vue'
import CRDetailView from './views/CRDetailView.vue'
import WorkView from './views/WorkView.vue'
import ActivityView from './views/ActivityView.vue'
import AgentsView from './views/AgentsView.vue'
import SearchView from './views/SearchView.vue'
import ArchiveView from './views/ArchiveView.vue'
import McpView from './views/McpView.vue'
import EmbedView from './views/EmbedView.vue'
import { embedded } from './embed.js'

const routes = [
  { path: '/', name: 'home', component: OverviewView, meta: { title: '总览' } },
  { path: '/tree', name: 'tree', component: HomeView, meta: { title: '文档树' } },
  {
    path: '/capabilities/:id',
    name: 'capability',
    component: CapabilityView,
    meta: { title: '小业务' },
  },
  {
    path: '/blocks/:id',
    name: 'block',
    component: BlockView,
    meta: { title: '模块' },
  },
  {
    path: '/blocks/:id/diff',
    name: 'block-diff',
    component: BlockDiffView,
    meta: { title: '版本对比' },
  },
  {
    path: '/change-requests',
    name: 'change-requests',
    component: CRListView,
    meta: { title: '审核单' },
  },
  {
    path: '/change-requests/:id',
    name: 'change-request',
    component: CRDetailView,
    meta: { title: '审核单详情' },
  },
  { path: '/work', name: 'work', component: WorkView, meta: { title: '待办' } },
  { path: '/activity', name: 'activity', component: ActivityView, meta: { title: '活动' } },
  { path: '/agents', name: 'agents', component: AgentsView, meta: { title: 'Agent 与密钥' } },
  { path: '/search', name: 'search', component: SearchView, meta: { title: '搜索' } },
  {
    path: '/archive',
    name: 'archive',
    component: ArchiveView,
    meta: { title: '归档' },
  },
  { path: '/mcp', name: 'mcp', component: McpView, meta: { title: 'AI 接入' } },
  { path: '/embed', name: 'embed', component: EmbedView, meta: { title: '嵌入' } },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  linkActiveClass: 'is-active',
  linkExactActiveClass: 'is-exact',
})

// 嵌入模式（地址带 ?embed=1）：站内跳转一直带着 embed 参数
router.beforeEach((to) => {
  if (embedded && !('embed' in to.query)) {
    return { path: to.path, query: { ...to.query, embed: '1' }, hash: to.hash, replace: true }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} · SpecLock`
    : 'SpecLock · 需求规格'
})
