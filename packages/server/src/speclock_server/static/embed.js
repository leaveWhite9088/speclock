/*!
 * SpecLock 嵌入脚本：把 SpecLock 的网页嵌进你自己的页面里。
 *
 *   <script src="http://127.0.0.1:端口/embed.js"></script>
 *   <div data-speclock="overview"></div>
 *
 * 或者用代码挂载：
 *   var box = SpecLock.mount('#spec', { view: 'tree', height: 'auto' });
 *   box.navigate('/blocks/3');          // 让里面的页面跳转
 *
 * 选项：view（页面名，见 SpecLock.views）、path（直接给路径，如 /blocks/3，优先于 view）、
 *      height（'auto' 跟随内容自适应，默认；或 '600px' / 600）、className、title、
 *      onReady(path)、onNavigate(path)。
 * 嵌入的页面只读，不能修改任何东西。文档：docs/EMBED.md
 */
(function () {
  'use strict';

  var script = document.currentScript;
  var ORIGIN = script && script.src ? new URL(script.src).origin : window.location.origin;

  var VIEWS = {
    overview: '/',
    tree: '/tree',
    'change-requests': '/change-requests',
    work: '/work',
    activity: '/activity',
    agents: '/agents',
    search: '/search',
    archive: '/archive',
    mcp: '/mcp',
  };

  var instances = [];

  function resolvePath(opts) {
    var path = opts.path || VIEWS[opts.view || 'overview'];
    if (!path || path.charAt(0) !== '/') {
      throw new Error('SpecLock: 未知的页面 ' + (opts.path || opts.view) + '，可选：' + Object.keys(VIEWS).join(', '));
    }
    return path;
  }

  function withEmbed(path) {
    return ORIGIN + path + (path.indexOf('?') === -1 ? '?' : '&') + 'embed=1';
  }

  function cssHeight(h) {
    return typeof h === 'number' ? h + 'px' : h;
  }

  function mount(target, options) {
    var opts = options || {};
    var el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) throw new Error('SpecLock: 找不到挂载的元素 ' + target);

    var auto = opts.height === undefined || opts.height === 'auto';
    var path = resolvePath(opts);
    var iframe = document.createElement('iframe');
    iframe.src = withEmbed(path);
    iframe.title = opts.title || 'SpecLock';
    iframe.className = opts.className || '';
    iframe.setAttribute('loading', 'lazy');
    iframe.style.cssText = 'border:0;width:100%;display:block;height:' + (auto ? '480px' : cssHeight(opts.height));
    el.appendChild(iframe);

    var inst = {
      iframe: iframe,
      path: path,
      auto: auto,
      opts: opts,
      navigate: function (to) {
        if (typeof to !== 'string' || to.charAt(0) !== '/') return;
        iframe.contentWindow.postMessage({ source: 'speclock-host', type: 'navigate', path: to }, ORIGIN);
      },
      destroy: function () {
        iframe.remove();
        instances = instances.filter(function (i) { return i !== inst; });
      },
    };
    instances.push(inst);
    return inst;
  }

  window.addEventListener('message', function (e) {
    if (e.origin !== ORIGIN || !e.data || e.data.source !== 'speclock') return;
    for (var i = 0; i < instances.length; i++) {
      var inst = instances[i];
      if (inst.iframe.contentWindow !== e.source) continue;
      var d = e.data;
      if (d.type === 'height' && inst.auto && typeof d.height === 'number') {
        inst.iframe.style.height = Math.max(120, Math.ceil(d.height)) + 'px';
      } else if (d.type === 'navigate') {
        inst.path = d.path;
        if (inst.opts.onNavigate) inst.opts.onNavigate(d.path);
      } else if (d.type === 'ready') {
        inst.path = d.path;
        if (inst.opts.onReady) inst.opts.onReady(d.path);
      }
    }
  });

  function autoMount() {
    var nodes = document.querySelectorAll('[data-speclock]');
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (n.getAttribute('data-speclock-mounted')) continue;
      n.setAttribute('data-speclock-mounted', '1');
      mount(n, {
        view: n.getAttribute('data-speclock') || 'overview',
        path: n.getAttribute('data-path') || undefined,
        height: n.getAttribute('data-height') || undefined,
      });
    }
  }

  window.SpecLock = { mount: mount, views: VIEWS, origin: ORIGIN, scan: autoMount };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', autoMount);
  else autoMount();
})();
