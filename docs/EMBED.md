# 把 SpecLock 的网页嵌进别的前端

SpecLock 的网页有两种用法：

- **单独打开**：`speclock serve` 之后访问它自己的地址（端口见 `.speclock/config.toml`），不用登录。
- **嵌进别的页面**：放进你自己的前端的 iframe 里，只显示内容，没有侧栏和顶栏。

嵌进去的网页是**只读**的，什么都改不了（和单独打开时一样，它自动使用一把只读 key）。

## 最简单：一段 script

```html
<script src="http://127.0.0.1:端口/embed.js"></script>
<div data-speclock="overview"></div>
```

`/embed.js` 是 SpecLock 服务自己提供的统一入口。`data-speclock` 写要显示的**页面名**，
脚本会自动创建 iframe，**高度跟着内容自适应**，不用你管。同一页里可以放多个。

网页里的「嵌入」页（`/embed`）有这些代码，地址已经替你填好，可以直接复制。

## 页面名

| 页面名 | 路径 | 内容 |
|---|---|---|
| `overview` | `/` | 总览：现在有什么需要关注的 |
| `tree` | `/tree` | 文档树：大业务 → 小业务 → 模块 |
| `change-requests` | `/change-requests` | 审核单 |
| `work` | `/work` | 待办与执行状态 |
| `activity` | `/activity` | 活动时间线 |
| `agents` | `/agents` | Agent 与密钥 |
| `search` | `/search` | 搜索 |
| `mcp` | `/mcp` | AI 接入 |

详情页也可以，直接给路径：`/blocks/3`、`/capabilities/2`、`/change-requests/5`。

```html
<div data-speclock="overview" data-path="/blocks/3"></div>   <!-- data-path 优先于页面名 -->
<div data-speclock="tree" data-height="600px"></div>         <!-- 固定高度，不自适应 -->
```

## 用代码控制

```html
<script src="http://127.0.0.1:端口/embed.js"></script>
<div id="spec"></div>
<script>
  var box = SpecLock.mount('#spec', {
    view: 'tree',                       // 或 path: '/blocks/3'
    height: 'auto',                     // 默认；也可以是 '600px' / 600
    onReady: function (path) {},        // 里面的页面准备好了
    onNavigate: function (path) {       // 用户在里面点了链接，跳到了 path
      history.replaceState(null, '', '#' + path)
    },
  })

  box.navigate('/blocks/3')   // 让里面跳转（路径必须以 / 开头）
  box.destroy()               // 移除
</script>
```

`SpecLock.views` 是页面名到路径的对照表，`SpecLock.origin` 是 SpecLock 服务的地址。

## 纯 iframe（不想引脚本）

地址后面加 `?embed=1`，就是嵌入模式：

```html
<iframe src="http://127.0.0.1:端口/?embed=1" style="border:0;width:100%;height:600px"></iframe>
<iframe src="http://127.0.0.1:端口/blocks/3?embed=1" style="border:0;width:100%;height:600px"></iframe>
```

这种方式高度要自己定。里面站内跳转时 `embed=1` 会一直带着。

## 想自己处理消息？（不用 embed.js 时）

嵌入模式下，网页会向父窗口 `postMessage`，数据里 `source` 都是 `"speclock"`：

| `type` | 附带 | 什么时候 |
|---|---|---|
| `ready` | `path` | 页面可以用了 |
| `navigate` | `path` | 里面跳转到了别的页面 |
| `height` | `height`（像素） | 内容高度变了，可据此调整 iframe 高度 |

要让里面跳转，向 iframe 的 `contentWindow` 发：

```js
iframe.contentWindow.postMessage({ source: 'speclock-host', type: 'navigate', path: '/blocks/3' }, origin)
```

网页只接受来自父窗口、以 `/` 开头的路径。发出去的消息里只有路径和高度，没有任何规格内容。

## 谁能嵌：`embed_origins`

为了防止被恶意页面套壳，**默认只有本机上的页面（任意端口）能嵌**。要嵌进别的地址，
在 `.speclock/config.toml` 里加上，**重启服务**后生效：

```toml
embed_origins = ["http://localhost:*", "http://127.0.0.1:*", "https://my.app"]
# 写 "*" 表示任何来源都可以嵌
```

SpecLock 把它写进响应头 `Content-Security-Policy: frame-ancestors 'self' …`。注意：IPv6 地址（`[::1]`）这种写法浏览器不认，
会让整条指令失效，所以请用 `localhost` 或 `127.0.0.1`。

## 常见问题

- **嵌进去是空白，控制台提示 frame-ancestors**：你的页面来源不在 `embed_origins` 里，加上并重启服务。
- **从 https 页面嵌 `http://127.0.0.1`**：浏览器对 localhost / 127.0.0.1 放行混合内容，可以；其他 http 地址会被拦。
- **想让嵌入页看到别的项目的数据**：网页用的是只读 key，能看到整个库里所有项目；嵌入页和单独打开看到的内容一样。
- **SpecLock 服务没启动**：iframe 里是浏览器的连接失败页。服务启动、网页构建好（`apps/web/dist`）才有内容。
