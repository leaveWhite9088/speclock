<script setup>
// 嵌入：把这个网页放进你自己的页面里。页面本身只是说明和可复制的代码，真正的嵌入脚本是 /embed.js。
import { computed, ref } from 'vue'

const origin = window.location.origin

const VIEWS = [
  ['overview', '/', '总览：现在有什么需要关注的'],
  ['tree', '/tree', '文档树：大业务 → 小业务 → 模块'],
  ['change-requests', '/change-requests', '审核单'],
  ['work', '/work', '待办与执行状态'],
  ['activity', '/activity', '活动时间线'],
  ['agents', '/agents', 'Agent 与密钥'],
  ['search', '/search', '搜索'],
  ['mcp', '/mcp', 'AI 接入'],
]

const scriptSnippet = computed(
  () => `<script src="${origin}/embed.js"><\/script>
<div data-speclock="overview"></div>`,
)

const iframeSnippet = computed(
  () => `<iframe src="${origin}/?embed=1" style="border:0;width:100%;height:600px"></iframe>`,
)

const apiSnippet = computed(
  () => `<script src="${origin}/embed.js"><\/script>
<div id="spec"></div>
<script>
  // height 默认 'auto'：高度跟着内容自适应
  var box = SpecLock.mount('#spec', {
    view: 'tree',
    onNavigate: function (path) { console.log('里面跳到了', path) },
  })
  box.navigate('/blocks/3')   // 让里面的页面跳转（路径以 / 开头）
<\/script>`,
)

const copied = ref('')
async function copy(text, which) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copied.value = which
  setTimeout(() => (copied.value = ''), 1500)
}
</script>

<template>
  <div class="page embed-page">
    <p class="page-eyebrow">Embed</p>
    <h1 class="page-title">嵌入到其他页面</h1>
    <p class="page-desc">
      这个网页既可以单独打开，也可以一键嵌进别的前端里。嵌进去的页面只读，没有侧栏和顶栏，只显示内容。
      完整说明见仓库里的 <code>docs/EMBED.md</code>。
    </p>

    <section class="section">
      <h2 class="section-title">最简单：一段 script</h2>
      <div class="card section-card">
        <p class="step-text">
          放进你页面的 HTML 里。<code>data-speclock</code> 写要显示的页面名，高度会自动跟着内容变。
        </p>
        <pre class="config-pre mono">{{ scriptSnippet }}</pre>
        <button type="button" class="btn" @click="copy(scriptSnippet, 'script')">
          {{ copied === 'script' ? '已复制 ✓' : '复制' }}
        </button>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">纯 iframe（不想引脚本时）</h2>
      <div class="card section-card">
        <p class="step-text">地址后面加 <code>?embed=1</code> 就是嵌入模式。高度要自己定。</p>
        <pre class="config-pre mono">{{ iframeSnippet }}</pre>
        <button type="button" class="btn" @click="copy(iframeSnippet, 'iframe')">
          {{ copied === 'iframe' ? '已复制 ✓' : '复制' }}
        </button>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">用代码控制</h2>
      <div class="card section-card">
        <p class="step-text">
          <code>SpecLock.mount</code> 返回一个对象：<code>navigate(path)</code> 让里面跳转，<code>destroy()</code> 移除。
          还可以传 <code>path</code>（如 <code>/blocks/3</code>，优先于 <code>view</code>）、<code>height</code>、
          <code>onReady</code>、<code>onNavigate</code>。
        </p>
        <pre class="config-pre mono">{{ apiSnippet }}</pre>
        <button type="button" class="btn" @click="copy(apiSnippet, 'api')">
          {{ copied === 'api' ? '已复制 ✓' : '复制' }}
        </button>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">可以嵌哪些页面</h2>
      <div class="card section-card table-wrap">
        <table class="view-table">
          <thead>
            <tr><th>页面名</th><th>路径</th><th>内容</th></tr>
          </thead>
          <tbody>
            <tr v-for="[name, path, desc] in VIEWS" :key="name">
              <td class="mono">{{ name }}</td>
              <td class="mono">{{ path }}</td>
              <td>{{ desc }}</td>
            </tr>
          </tbody>
        </table>
        <p class="step-text muted">
          模块、小业务、审核单的详情页也行，直接给路径：<code>/blocks/3</code>、<code>/capabilities/2</code>、
          <code>/change-requests/5</code>。
        </p>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">只能被谁嵌</h2>
      <div class="card section-card">
        <p class="step-text">
          为了防止被恶意页面套壳，默认只有<strong>本机上的页面</strong>（任意端口）能嵌。要嵌进别的地址，在
          <code>.speclock/config.toml</code> 里加上，然后重启服务：
        </p>
        <pre class="config-pre mono">embed_origins = ["http://localhost:*", "http://127.0.0.1:*", "https://my.app"]</pre>
      </div>
    </section>
  </div>
</template>

<style scoped>
.config-pre {
  margin: var(--sp-3) 0;
  padding: var(--sp-3);
  background: var(--paper);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.step-text {
  margin: 0 0 var(--sp-2);
}

.view-table {
  width: 100%;
  border-collapse: collapse;
}

.view-table th,
.view-table td {
  padding: var(--sp-2) var(--sp-3);
  text-align: left;
  border-bottom: 1px solid var(--hairline);
}
</style>
