/**
 * 嵌入模式：网页被放进别的页面的 iframe 里时（地址带 ?embed=1）。
 *
 * - 只显示页面内容，不带侧栏和顶栏（见 App.vue）；站内跳转保持 embed 参数（见 router.js）
 * - 通过 postMessage 向外层页面报告：ready（可以用了）、navigate（当前路径）、height（内容高度，
 *   供外层自适应 iframe 高度）。发出去的只有路径和高度，没有数据，所以 targetOrigin 用 '*'
 * - 接受外层页面的 navigate 指令（只认来自父窗口、以 / 开头的路径）
 *
 * 外层页面不用自己处理这些消息：引入 /embed.js（speclock/static/embed.js）即可，文档见 docs/EMBED.md。
 */

export const embedded = new URLSearchParams(window.location.search).has('embed')

/** 去掉 embed 参数后的路径（报告给外层页面用）。 */
export function withoutEmbed(fullPath) {
  const url = new URL(fullPath, 'http://x')
  url.searchParams.delete('embed')
  const query = url.searchParams.toString()
  return url.pathname + (query ? `?${query}` : '') + url.hash
}

function post(message) {
  window.parent.postMessage({ source: 'speclock', ...message }, '*')
}

export function setupEmbed(router) {
  if (!embedded) return
  document.documentElement.classList.add('embedded')

  router.afterEach((to) => post({ type: 'navigate', path: withoutEmbed(to.fullPath) }))

  const reportHeight = () => post({ type: 'height', height: document.body.offsetHeight })
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(reportHeight).observe(document.body)

  window.addEventListener('message', (e) => {
    if (e.source !== window.parent) return
    const d = e.data || {}
    if (d.source === 'speclock-host' && d.type === 'navigate' && typeof d.path === 'string' && d.path.startsWith('/')) {
      router.push(d.path)
    }
  })

  router.isReady().then(() => {
    post({ type: 'ready', path: withoutEmbed(router.currentRoute.value.fullPath) })
    reportHeight()
  })
}
