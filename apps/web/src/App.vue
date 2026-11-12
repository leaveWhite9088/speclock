<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { APP_VERSION } from './version.js'
import { embedded } from './embed.js'
import FreshnessBadge from './components/FreshnessBadge.vue'
import { usePolling } from './composables/usePolling.js'
import { checkOnce } from './composables/useChangeSignal.js'

const route = useRoute()
const router = useRouter()

// 侧栏：宽屏常驻，窄屏收成抽屉（顶栏的菜单键打开；点遮罩 / Esc / 跳转后关闭）
const drawerOpen = ref(false)
const closeDrawer = () => (drawerOpen.value = false)
watch(() => route.fullPath, closeDrawer)

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
  if (e.key === 'Escape' && drawerOpen.value) {
    closeDrawer()
    return
  }
  if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return
  const el = e.target
  const typing = el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
  if (typing) return
  e.preventDefault()
  drawerOpen.value = true // 窄屏里搜索框在抽屉里
  nextTick(() => {
    searchInput.value?.focus()
    searchInput.value?.select()
  })
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="shell" :class="{ embedded, 'drawer-open': drawerOpen }">
    <a v-if="!embedded" href="#main" class="skip-link">跳到主要内容</a>

    <!-- 窄屏顶栏：菜单键 + 当前页标题 -->
    <header v-if="!embedded" class="mobilebar">
      <button type="button" class="icon-btn" aria-label="打开菜单" :aria-expanded="drawerOpen" @click="drawerOpen = true">
        <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true">
          <path d="M3 6h14M3 10h14M3 14h14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
        </svg>
      </button>
      <span class="mobilebar-title">{{ route.meta.title || 'SpecLock' }}</span>
      <FreshnessBadge class="mobilebar-fresh" />
    </header>

    <div v-if="!embedded" class="scrim" @click="closeDrawer"></div>

    <aside v-if="!embedded" class="sidebar" aria-label="导航">
      <div class="brand">
        <span class="brand-name">SpecLock</span>
        <button type="button" class="icon-btn close-btn" aria-label="关闭菜单" @click="closeDrawer">
          <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
            <path d="M5 5l10 10M15 5L5 15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <form class="search" role="search" @submit.prevent="goSearch">
        <input
          ref="searchInput"
          v-model="searchText"
          class="input search-input"
          type="search"
          placeholder="搜索  /"
          aria-label="搜索规格与审核单"
        />
      </form>

      <nav class="side-nav" aria-label="主导航">
        <RouterLink v-for="item in mainNav" :key="item.to" :to="item.to" class="side-link">{{ item.label }}</RouterLink>
      </nav>

      <nav class="side-nav side-bottom" aria-label="辅助导航">
        <RouterLink v-for="item in bottomNav" :key="item.to" :to="item.to" class="side-link">{{ item.label }}</RouterLink>
        <div class="side-foot">
          <FreshnessBadge />
          <span class="ver">v{{ APP_VERSION }}</span>
        </div>
      </nav>
    </aside>

    <main id="main" class="content" tabindex="-1">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
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

.content {
  flex: 1;
  min-width: 0;
}

.content:focus {
  outline: none;
}

/* ---------- 侧栏（宽屏常驻） ---------- */

.sidebar {
  position: sticky;
  top: 0;
  align-self: flex-start;
  height: 100vh;
  flex: none;
  width: var(--sidebar-w);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  background: var(--side);
  padding: var(--sp-5) var(--sp-3) var(--sp-4);
  overflow-y: auto;
}

.brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--sp-3);
}

.brand-name {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.brand-name::before {
  content: '';
  display: inline-block;
  width: 9px;
  height: 9px;
  margin-right: var(--sp-2);
  border-radius: 50%;
  background: var(--accent);
}

.search-input {
  background: var(--paper);
  border-color: transparent;
}

.search-input:focus {
  border-color: var(--accent);
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
  font-size: var(--text-md);
  transition:
    color var(--dur) var(--ease),
    background var(--dur) var(--ease);
}

.side-link:hover {
  color: var(--ink);
  background: var(--hover);
}

.side-link.is-active {
  color: var(--ink);
  background: var(--paper);
  font-weight: 600;
}

.side-bottom {
  margin-top: auto;
  padding-top: var(--sp-3);
  border-top: 1px solid var(--hairline-2);
}

.side-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-3) 0;
}

.ver {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--ink-2);
}

/* 窄屏专用的东西，宽屏不显示 */
.mobilebar,
.scrim,
.sidebar .close-btn {
  display: none;
}

.icon-btn {
  appearance: none;
  display: inline-grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: var(--ink);
  cursor: pointer;
}

.icon-btn:hover {
  background: var(--hover);
}

/* ---------- 窄屏：侧栏变抽屉 ---------- */

@media (max-width: 760px) {
  .shell {
    flex-direction: column;
  }

  .mobilebar {
    position: sticky;
    top: 0;
    z-index: 20;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    height: var(--topbar-h);
    padding: 0 var(--sp-2);
    background: var(--paper);
    border-bottom: 1px solid var(--hairline);
  }

  .mobilebar-title {
    flex: 1;
    min-width: 0;
    font-family: var(--font-display);
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .mobilebar-fresh {
    margin-right: var(--sp-2);
  }

  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 40;
    width: min(280px, 84vw);
    height: auto;
    transform: translateX(-102%);
    transition: transform 220ms var(--ease);
  }

  .drawer-open .sidebar {
    transform: none;
    box-shadow: 0 0 40px rgba(31, 30, 29, 0.18);
  }

  .scrim {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 30;
    background: rgba(31, 30, 29, 0.32);
    opacity: 0;
    pointer-events: none;
    transition: opacity 220ms var(--ease);
  }

  .drawer-open .scrim {
    opacity: 1;
    pointer-events: auto;
  }

  .sidebar .close-btn {
    display: inline-grid;
  }
}
</style>
