import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router.js'
import './styles/tokens.css'
import './styles/base.css'
import './styles/tree.css'

import { ensureSession } from './api/client.js'
import { setupEmbed } from './embed.js'

const app = createApp(App).use(router)
setupEmbed(router) // 被嵌进别的页面时：报告路径和高度、接受外层的跳转指令
// 先取一把只读 key 再挂载；取不到也照常挂载，各页面会把原因显示出来
ensureSession()
  .catch(() => {})
  .finally(() => app.mount('#app'))
