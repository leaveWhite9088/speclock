<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import VersionChip from './components/VersionChip.vue'
import { APP_VERSION } from './version.js'
import { embedded } from './embed.js'
import FreshnessBadge from './components/FreshnessBadge.vue'
import { usePolling } from './composables/usePolling.js'
import { checkOnce } from './composables/useChangeSignal.js'

const route = useRoute()
const router = useRouter()

const mainNav = [
  { to: '/', label: '总览' },
  { to: '/tree', label: '文档树' },
  { to: '/change-requests', label: '审核单' },
  { to: '/work', label: '待办' },
  { to: '/activity', label: '活动' },
  { to: '/agents', label: 'Agent' },
  { to: '/archive', label: '归档' },
]

const bottomNav = [
  { to: '/mcp', label: 'AI 接入' },
  { to: '/embed', label: '嵌入' },
]

// ---------- 自动刷新：全站一个定时器，每 5 秒看一眼有没有新的变化 ----------
usePolling(checkOnce, 5000, { immediate: true })

// ---------- 全局搜索：回车跳到 /search，「/」键聚焦 ----------
const searchText = ref('')
const searchInput = ref(null)

watch(
  () => route.query.q,
  (q) => {
    if (route.name === 'search') searchText.value = typeof q === 'string' ? q : ''
  },
  { immediate: true },
)

function goSearch() {
  const q = searchText.value.trim()
  if (q) router.push({ name: 'search', query: { q } })
}

function onKeydown(e) {
  if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return
  const el = e.target
  const typing = el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
  if (typing) return
  e.preventDefault()
  searchInput.value?.focus()
  searchInput.value?.select()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="shell" :class="{ embedded }">
    <a v-if="!embedded" href="#main" class="skip-link">跳到主要内容</a>
    <aside v-if="!embedded" class="sidebar">
      <nav class="side-nav" aria-label="主导航">
        <RouterLink
          v-for="item in mainNav"
          :key="item.to"
          :to="item.to"
          class="side-link"
          >{{ item.label }}</RouterLink
        >
      </nav>

      <nav class="side-nav side-bottom" aria-label="辅助导航">
        <RouterLink
          v-for="item in bottomNav"
          :key="item.to"
          :to="item.to"
          class="side-link"
          >{{ item.label }}</RouterLink
        >
      </nav>
    </aside>

    <div class="main">
      <header v-if="!embedded" class="topbar">
        <div class="brand">
          <span class="brand-name">SpecLock</span>
          <VersionChip :version="APP_VERSION" />
        </div>
        <form class="search" role="search" @submit.prevent="goSearch">
          <input
            ref="searchInput"
            v-model="searchText"
            class="input search-input"
            type="search"
            placeholder="搜索规格与审核单（按 / 聚焦）"
            aria-label="搜索规格与审核单"
          />
        </form>
        <div class="topbar-right">
          <FreshnessBadge />
          <span class="key-hint" title="网页只读，不能修改任何东西">只读</span>
        </div>
      </header>

      <main id="main" class="content" tabindex="-1">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
}

/* 嵌入模式：只剩内容，高度跟着内容走（外层页面据此调整 iframe 高度） */
.shell.embedded {
  min-height: 0;
}

.shell.embedded .main {
  margin-left: 0;
}

/* 键盘用户的「跳到主要内容」：平时藏起来，Tab 聚焦时出现 */
.skip-link {
  position: fixed;
  top: var(--sp-2);
  left: var(--sp-2);
  z-index: 100;
  padding: var(--sp-2) var(--sp-4);
  background: var(--contract);
  color: #fff;
  border-radius: var(--radius);
  transform: translateY(-200%);
}

.skip-link:focus {
  transform: none;
}

.content:focus {
  outline: none;
}

/* ---------- 侧边栏 ---------- */

.sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  width: var(--sidebar-w);
  display: flex;
  flex-direction: column;
  background: var(--card);
  border-right: 1px solid var(--hairline);
  padding: var(--sp-5) var(--sp-4) var(--sp-4);
}

.side-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.side-link {
  display: block;
  padding: 7px var(--sp-3);
  border-radius: var(--radius);
  color: var(--ink-2);
  font-size: var(--text-sm);
  transition:
    color var(--dur) var(--ease),
    background var(--dur) var(--ease);
}

.side-link:hover {
  color: var(--ink);
  background: var(--paper);
}

.side-link.is-active {
  color: var(--contract);
  background: var(--contract-wash);
  font-weight: 500;
}

.side-bottom {
  margin-top: auto;
  border-top: 1px solid var(--hairline);
  padding-top: var(--sp-4);
}

/* ---------- 主区 ---------- */

.main {
  flex: 1;
  margin-left: var(--sidebar-w);
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  height: var(--topbar-h);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--sp-8);
  background: var(--card);
  border-bottom: 1px solid var(--hairline);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.brand-name {
  font-family: var(--font-mono);
  font-size: var(--text-md);
  font-weight: 600;
  letter-spacing: 0.02em;
}

.search {
  flex: 1;
  max-width: 420px;
  margin: 0 var(--sp-4);
}

.search-input {
  padding: 5px var(--sp-3);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}

.key-hint {
  font-size: var(--text-xs);
  color: var(--ink-2);
  padding: 3px var(--sp-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--paper);
}

.content {
  flex: 1;
}

/* 窄屏：侧边栏收成顶部的一条横向导航（可左右滑动），主区占满宽度 */
@media (max-width: 900px) {
  .shell {
    flex-direction: column;
  }

  .sidebar {
    position: sticky;
    top: 0;
    z-index: 20;
    inset: auto;
    width: auto;
    flex-direction: row;
    align-items: center;
    gap: var(--sp-3);
    padding: var(--sp-2) var(--sp-3);
    border-right: none;
    border-bottom: 1px solid var(--hairline);
    overflow-x: auto;
  }

  .side-nav {
    flex-direction: row;
    flex: none;
  }

  .side-link {
    white-space: nowrap;
  }

  .side-bottom {
    margin-top: 0;
    margin-left: auto;
    border-top: none;
    padding-top: 0;
  }

  .main {
    margin-left: 0;
  }

  .topbar {
    position: static;
    padding: 0 var(--sp-4);
  }
}
</style>
