import { createApp } from 'vue'
import App from './App.vue'
import ProjectPicker from './views/ProjectPicker.vue'
import { router } from './router.js'
import './styles/tokens.css'
import './styles/base.css'
import './styles/tree.css'

import { ensureSession } from './api/client.js'
import { setupEmbed } from './embed.js'

// 先取一把只读 key 再挂载（这把 key 绑定了一个项目，网页只看得到它）。
// 库里有多个项目、地址又没指明看哪个时：显示项目选择页，不画任何项目的内容。
// 取不到别的原因：也照常挂载，各页面会把原因显示出来。
ensureSession()
  .then(() => {
    const app = createApp(App).use(router)
    setupEmbed(router) // 被嵌进别的页面时：报告路径和高度、接受外层的跳转指令
    app.mount('#app')
  })
  .catch((err) => {
    if (err && err.code === 'web_project_required') {
      createApp(ProjectPicker).mount('#app')
      return
    }
    const app = createApp(App).use(router)
    setupEmbed(router)
    app.mount('#app')
  })
