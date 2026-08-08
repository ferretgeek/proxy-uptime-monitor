(function () {
  "use strict";

  const NODE_STATUS = {
    online: { label: "正常可用", icon: "shield-check", level: "healthy" },
    degraded: { label: "节点连接不稳定", icon: "triangle-alert", level: "warning" },
    offline: { label: "无法使用", icon: "shield-x", level: "critical" },
    pending: { label: "等待首次检测", icon: "shield-question", level: "unknown" },
    unknown: { label: "暂时无法判断", icon: "shield-question", level: "unknown" },
    paused: { label: "已停用", icon: "pause-circle", level: "unknown" },
    removed: { label: "已移除", icon: "shield-x", level: "critical" }
  };

  const SERVICE_STATUS = {
    available: ["正常访问", "healthy", "circle-check"],
    login_required: ["需要登录", "warning", "log-in"],
    region_blocked: ["地区限制", "warning", "map-pin-x"],
    service_blocked: ["访问受限", "warning", "shield-ban"],
    service_error: ["服务异常", "warning", "server-off"],
    response_error: ["响应异常", "warning", "file-warning"],
    content_mismatch: ["结果不确定", "unknown", "circle-help"],
    uncertain: ["结果不确定", "unknown", "circle-help"],
    timeout: ["连接超时", "critical", "timer-off"],
    dns_error: ["DNS 错误", "critical", "globe-lock"],
    tcp_error: ["连接失败", "critical", "unplug"],
    tls_error: ["TLS 错误", "critical", "lock-keyhole"],
    proxy_error: ["代理故障", "critical", "route-off"],
    proxy_configuration: ["配置错误", "critical", "file-x"]
  };

  const ERROR_LABELS = {
    login_required: "目标网站需要登录",
    region_blocked: "目标网站有地区限制",
    service_blocked: "目标网站限制了本次访问",
    service_error: "目标网站自身异常",
    response_error: "目标网站响应异常",
    uncertain: "页面结果暂时无法确认",
    content_mismatch: "页面结果暂时无法确认",
    timeout: "连接超时",
    dns_error: "域名解析失败",
    tcp_error: "网络连接失败",
    tls_error: "安全连接失败",
    proxy_error: "代理通道建立失败",
    proxy_configuration: "节点配置无法使用",
    node_probe_unstable: "节点测速只有部分请求成功，连接存在波动",
    endpoint_probe_unstable: "旧版入口诊断存在波动，等待按真实代理链路重新检测",
    endpoint_probe_failed: "旧版入口诊断未成功，等待按真实代理链路重新检测",
    no_targets: "没有启用检测项"
  };

  const SERVICE_REASON_LABELS = {
    login_required: "需要登录",
    region_blocked: "有地区限制",
    service_blocked: "限制了本次访问",
    service_error: "网站自身异常",
    response_error: "响应异常",
    uncertain: "结果暂时无法确认",
    content_mismatch: "结果暂时无法确认"
  };

  const DEGRADED_STATUS_ORDER = [
    "login_required", "region_blocked", "service_blocked",
    "service_error", "response_error", "uncertain", "content_mismatch"
  ];

  const DEGRADED_PRESENTATION = {
    login_required: { label: "需登录", icon: "log-in" },
    region_blocked: { label: "存在地区限制", icon: "map-pin-x" },
    service_blocked: { label: "访问受限", icon: "shield-ban" },
    service_error: { label: "网站响应异常", icon: "server-off" },
    response_error: { label: "网站响应异常", icon: "file-warning" },
    uncertain: { label: "结果待确认", icon: "circle-help" },
    content_mismatch: { label: "结果待确认", icon: "circle-help" }
  };

  const VIEW_META = {
    dashboard: ["实时节点观测", "节点态势"],
    latency: ["六个时间窗口横向对照", "延迟统计"],
    nodes: ["筛选、批量复测与配置", "节点管理"],
    subscriptions: ["安全刷新与同步", "订阅管理"],
    events: ["故障、恢复与维护轨迹", "事件记录"],
    system: ["资源、检测与存储边界", "系统状态"]
  };

  const COUNTRY_NAMES = {
    AU: "澳大利亚", BR: "巴西", CA: "加拿大", CH: "瑞士", CN: "中国大陆",
    DE: "德国", ES: "西班牙", FI: "芬兰", FR: "法国", GB: "英国",
    HK: "中国香港", ID: "印度尼西亚", IN: "印度", IT: "意大利",
    JP: "日本", KR: "韩国", MO: "中国澳门", MY: "马来西亚",
    NL: "荷兰", NO: "挪威", NZ: "新西兰", PH: "菲律宾", PL: "波兰",
    RU: "俄罗斯", SE: "瑞典", SG: "新加坡", TH: "泰国",
    TR: "土耳其", TW: "中国台湾", UA: "乌克兰", US: "美国",
    VN: "越南", ZZ: "未知地区"
  };

  const COLUMN_WIDTH_STORAGE_KEY = "airport-monitor-node-columns-v1";
  const NODE_COLUMN_LIMITS = Object.freeze({
    select: { label: "选择列", min: 28, max: 64 },
    node: { label: "节点列", min: 110, max: 520 },
    status: { label: "节点连接状态列", min: 132, max: 420 },
    region: { label: "出口国家和地区列", min: 88, max: 300 },
    latency: { label: "两种延迟列", min: 168, max: 380 },
    health: { label: "健康评分列", min: 82, max: 220 },
    availability: { label: "在线率列", min: 92, max: 240 },
    services: { label: "网站访问结果列", min: 82, max: 420 },
    checked: { label: "最近检测列", min: 82, max: 220 },
    actions: { label: "快捷操作列", min: 176, max: 360 }
  });
  const NODE_SORT_OPTIONS = Object.freeze([
    { value: "status", label: "节点状态", detail: "优先查看异常或正常节点", icon: "shield-alert", group: "状态与质量" },
    { value: "health", label: "健康评分", detail: "按综合健康分数排列", icon: "heart-pulse", group: "状态与质量" },
    { value: "website_latency", label: "网站访问 P95", detail: "按尾部网站完整耗时排列", icon: "globe-2", group: "长期质量" },
    { value: "node_latency", label: "代理链路 P95", detail: "按尾部代理通道耗时排列", icon: "radio-tower", group: "长期质量" },
    { value: "checked", label: "最近检测", detail: "按检测完成时间排列", icon: "clock-3", group: "节点信息" },
    { value: "country", label: "国家 / 地区", detail: "按出口地区名称排列", icon: "map-pinned", group: "节点信息" },
    { value: "name", label: "节点名称", detail: "按节点名称排列", icon: "arrow-down-a-z", group: "节点信息" }
  ]);
  const SORT_DEFAULT_DIRECTIONS = Object.freeze({
    status: "asc",
    health: "desc",
    website_latency: "asc",
    node_latency: "asc",
    latency: "asc",
    checked: "desc",
    country: "asc",
    name: "asc"
  });
  let smartSelectSequence = 0;

  const state = {
    me: null,
    view: "dashboard",
    dashboard: null,
    latency: null,
    nodePage: null,
    subscriptions: [],
    events: [],
    system: null,
    settings: null,
    notifications: null,
    targets: [],
    filters: {
      page: 1,
      page_size: 30,
      search: "",
      status: "",
      country: "",
      service: "",
      sort: "status",
      direction: "asc"
    },
    latencyFilters: {
      page: 1,
      page_size: 30,
      search: "",
      country: "",
      sort: "score",
      direction: "desc"
    },
    selected: new Set(),
    expanded: new Map(),
    trendRanges: new Map(),
    trendCache: new Map(),
    trendRequests: new Map(),
    viewController: null,
    pollTimer: null,
    refreshTimer: null,
    activeTasks: false,
    busy: new WeakSet(),
    modalReturnFocus: null,
    resizeTimer: null,
    columnLayouts: null
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function clamp(value, minimum = 0, maximum = 100) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(minimum, Math.min(maximum, number)) : minimum;
  }

  function formatNumber(value, digits = 0) {
    const number = Number(value);
    return Number.isFinite(number)
      ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(number)
      : "—";
  }

  function formatPercent(value, digits = 1) {
    return value === null || value === undefined ? "—" : `${formatNumber(value, digits)}%`;
  }

  function formatLatency(value) {
    if (value === null || value === undefined || value === "") return "— ms";
    const number = Number(value);
    return Number.isFinite(number) ? `${formatNumber(number, number < 100 ? 1 : 0)} ms` : "— ms";
  }

  function formatBytes(value) {
    let number = Number(value);
    if (!Number.isFinite(number)) return "—";
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let index = 0;
    while (number >= 1024 && index < units.length - 1) {
      number /= 1024;
      index += 1;
    }
    return `${formatNumber(number, index ? 2 : 0)} ${units[index]}`;
  }

  function formatTime(value, withSeconds = false) {
    if (!value) return "尚无记录";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "时间未知";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      second: withSeconds ? "2-digit" : undefined, hour12: false
    }).format(date);
  }

  function relativeTime(value) {
    if (!value) return "尚未检测";
    const delta = new Date(value).getTime() - Date.now();
    if (!Number.isFinite(delta)) return "时间未知";
    const seconds = Math.round(delta / 1000);
    const units = [["天", 86400], ["小时", 3600], ["分钟", 60], ["秒", 1]];
    for (const [label, size] of units) {
      if (Math.abs(seconds) >= size || size === 1) {
        const amount = Math.max(1, Math.round(Math.abs(seconds) / size));
        return seconds < 0 ? `${amount} ${label}前` : `${amount} ${label}后`;
      }
    }
    return "刚刚";
  }

  function durationSince(value) {
    if (!value) return "尚未连续在线";
    let seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
    const days = Math.floor(seconds / 86400);
    seconds %= 86400;
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return days ? `${days} 天 ${hours} 小时` : hours ? `${hours} 小时 ${minutes} 分钟` : `${minutes} 分钟`;
  }

  function getCookie(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    const item = document.cookie.split("; ").find((part) => part.startsWith(prefix));
    return item ? decodeURIComponent(item.slice(prefix.length)) : "";
  }

  async function api(path, options = {}) {
    const request = { ...options };
    const method = String(request.method || "GET").toUpperCase();
    request.method = method;
    request.headers = { Accept: "application/json", ...(request.headers || {}) };
    if (request.body && typeof request.body !== "string") {
      request.headers["Content-Type"] = "application/json";
      request.body = JSON.stringify(request.body);
    }
    if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
      request.headers["X-CSRF-Token"] = getCookie("airport_csrf");
    }
    let response;
    try {
      response = await fetch(path, request);
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new Error("无法连接监测服务，请检查局域网连接");
    }
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json().catch(() => ({}))
      : await response.text();
    if (!response.ok) {
      if (response.status === 401 && state.me) showLogin("会话已失效，请重新登录");
      const message = payload && typeof payload === "object" ? payload.detail : "";
      throw new Error(message || `请求未完成（${response.status}）`);
    }
    return payload;
  }

  function selectAccessibleLabel(select) {
    const explicit = select.getAttribute("aria-label");
    if (explicit) return explicit;
    const field = select.closest(".field");
    const fieldLabel = field?.querySelector(":scope > label:first-child, :scope > span:first-child");
    if (fieldLabel?.textContent.trim()) return fieldLabel.textContent.trim();
    const hiddenLabel = select.parentElement?.querySelector(".sr-only");
    return hiddenLabel?.textContent.trim() || select.name || "选项";
  }

  function smartSelectLeadingMarkup(select, option) {
    const kind = select.dataset.selectKind || "default";
    const value = option?.value || "";
    if (kind === "status") {
      const meta = value ? nodeStatusMeta(value) : { icon: "layers-3", level: "unknown" };
      return `<span class="smart-option-leading level-${meta.level}"><i data-lucide="${meta.icon}"></i></span>`;
    }
    if (kind === "country" || kind === "region") {
      if (/^[A-Z]{2}$/.test(value)) {
        return `<span class="smart-option-leading is-flag"><img src="/static/flags/${escapeHtml(value.toLowerCase())}.svg" alt=""></span>`;
      }
      return '<span class="smart-option-leading"><i data-lucide="earth"></i></span>';
    }
    if (kind === "service" && value) return brandLogo(value, "is-smart-option");
    const icons = {
      service: "orbit",
      page_size: "rows-3",
      trend_range: "calendar-range",
      refresh_interval: "clock-3",
      latency_sort: "arrow-up-down"
    };
    return `<span class="smart-option-leading"><i data-lucide="${icons[kind] || "list-filter"}"></i></span>`;
  }

  function syncSmartSelect(shell) {
    const select = $(".smart-select-native", shell);
    const trigger = $(".smart-select-trigger", shell);
    const menu = shell._smartSelectMenu;
    if (!select || !trigger || !menu) return;
    const option = select.selectedOptions[0] || select.options[0];
    const text = option?.textContent.trim() || "请选择";
    const label = selectAccessibleLabel(select);
    $(".smart-select-value", trigger).textContent = text;
    trigger.setAttribute("aria-label", `${label}，当前为${text}`);
    trigger.title = `${label}：${text}`;
    trigger.disabled = select.disabled;
    $$(".smart-select-option", menu).forEach((button) => {
      const selected = button.dataset.value === select.value;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-selected", String(selected));
    });
    if (window.lucide) window.lucide.createIcons({ root: trigger });
  }

  function positionSmartSelect(shell) {
    const trigger = $(".smart-select-trigger", shell);
    const menu = shell._smartSelectMenu;
    if (!trigger || !menu || menu.hidden) return;
    const triggerBox = trigger.getBoundingClientRect();
    const viewportWidth = document.documentElement.clientWidth;
    const viewportHeight = window.innerHeight;
    const edge = 8;
    const preferredWidth = shell.classList.contains("smart-select-compact")
      ? Math.max(132, triggerBox.width)
      : Math.min(520, Math.max(240, triggerBox.width));
    const width = Math.min(preferredWidth, viewportWidth - edge * 2);
    const estimatedHeight = Math.min(menu.scrollHeight, 382);
    const spaceBelow = viewportHeight - triggerBox.bottom - edge;
    const spaceAbove = triggerBox.top - edge;
    const opensUpward = spaceBelow < Math.min(estimatedHeight, 260) && spaceAbove > spaceBelow;
    const available = Math.max(120, (opensUpward ? spaceAbove : spaceBelow) - 6);
    const maxHeight = Math.min(382, available);
    const left = clamp(triggerBox.left, edge, Math.max(edge, viewportWidth - width - edge));
    const top = opensUpward
      ? Math.max(edge, triggerBox.top - Math.min(estimatedHeight, maxHeight) - 6)
      : Math.min(viewportHeight - edge, triggerBox.bottom + 6);
    menu.classList.toggle("opens-upward", opensUpward);
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
    menu.style.width = `${Math.round(width)}px`;
    menu.style.maxHeight = `${Math.round(maxHeight)}px`;
  }

  function scrollSmartOptionIntoView(option, menu) {
    if (!option || !menu) return;
    const scroller = $(".smart-select-options", menu);
    if (!scroller) return;
    const optionTop = option.offsetTop;
    const optionBottom = optionTop + option.offsetHeight;
    if (optionTop < scroller.scrollTop) {
      scroller.scrollTop = optionTop;
    } else if (optionBottom > scroller.scrollTop + scroller.clientHeight) {
      scroller.scrollTop = optionBottom - scroller.clientHeight;
    }
  }

  function setSmartSelectOpen(shell, open, focusOption = false) {
    if (!shell) return;
    const trigger = $(".smart-select-trigger", shell);
    const menu = shell._smartSelectMenu;
    if (!trigger || !menu || trigger.disabled) return;
    $$(".smart-select.is-open").forEach((item) => {
      if (item !== shell) setSmartSelectOpen(item, false);
    });
    shell.classList.toggle("is-open", open);
    trigger.setAttribute("aria-expanded", String(open));
    menu.hidden = !open;
    if (!open) {
      menu.classList.remove("opens-upward");
      menu.style.removeProperty("left");
      menu.style.removeProperty("top");
      menu.style.removeProperty("width");
      menu.style.removeProperty("max-height");
      return;
    }
    positionSmartSelect(shell);
    if (focusOption) {
      requestAnimationFrame(() => {
        const selected = $(".smart-select-option.is-selected:not([disabled])", menu);
        const first = $(".smart-select-option:not([disabled])", menu);
        const option = selected || first;
        option?.focus({ preventScroll: true });
        scrollSmartOptionIntoView(option, menu);
      });
    }
  }

  function closeSmartSelects(returnFocus = false) {
    $$(".smart-select.is-open").forEach((shell) => {
      const trigger = $(".smart-select-trigger", shell);
      setSmartSelectOpen(shell, false);
      if (returnFocus) trigger?.focus({ preventScroll: true });
    });
  }

  function enhanceSelects(root = document) {
    $$(".smart-select-menu[data-owner]", document).forEach((menu) => {
      if (!document.getElementById(menu.dataset.owner)) menu.remove();
    });
    $$("select:not([data-smart-select-ready])", root).forEach((select) => {
      select.dataset.smartSelectReady = "true";
      const sequence = ++smartSelectSequence;
      const shell = document.createElement("span");
      const kind = select.dataset.selectKind || "default";
      shell.id = `smart-select-${sequence}`;
      shell.className = `smart-select smart-select-${kind}${select.dataset.selectCompact === "true" ? " smart-select-compact" : ""}`;
      select.before(shell);
      shell.append(select);
      select.classList.add("smart-select-native");
      select.tabIndex = -1;

      const label = selectAccessibleLabel(select);
      const listboxId = `smart-select-list-${sequence}`;
      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "smart-select-trigger";
      trigger.setAttribute("role", "combobox");
      trigger.setAttribute("aria-haspopup", "listbox");
      trigger.setAttribute("aria-expanded", "false");
      trigger.setAttribute("aria-controls", listboxId);
      trigger.innerHTML = '<span class="smart-select-value"></span><i class="smart-select-chevron" data-lucide="chevron-down"></i>';
      shell.append(trigger);

      const menu = document.createElement("div");
      menu.className = `smart-select-menu smart-select-menu-${kind}`;
      menu.dataset.owner = shell.id;
      menu.hidden = true;
      menu.innerHTML = `
        <header class="smart-select-menu-head" role="presentation">
          <span><strong>${escapeHtml(label)}</strong><small>选择一项后立即应用</small></span>
          <i data-lucide="list-filter"></i>
        </header>
        <div class="smart-select-options" id="${listboxId}" role="listbox" aria-label="${escapeHtml(label)}">
          ${Array.from(select.options).map((option, index) => `
            <button class="smart-select-option${option.selected ? " is-selected" : ""}" type="button"
              id="${listboxId}-option-${index}" role="option" aria-selected="${option.selected}"
              data-value="${escapeHtml(option.value)}" ${option.disabled ? "disabled" : ""}>
              ${smartSelectLeadingMarkup(select, option)}
              <span class="smart-select-option-copy">${escapeHtml(option.textContent.trim())}</span>
              <i class="smart-select-option-check" data-lucide="check"></i>
            </button>`).join("")}
        </div>`;
      document.body.append(menu);
      shell._smartSelectMenu = menu;

      trigger.addEventListener("click", () => setSmartSelectOpen(shell, !shell.classList.contains("is-open")));
      trigger.addEventListener("keydown", (event) => {
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          setSmartSelectOpen(shell, true, true);
        } else if (event.key === "Escape" && shell.classList.contains("is-open")) {
          event.preventDefault();
          event.stopPropagation();
          setSmartSelectOpen(shell, false);
        }
      });
      menu.addEventListener("click", (event) => {
        const button = event.target.closest(".smart-select-option");
        if (!button || button.disabled) return;
        const changed = select.value !== button.dataset.value;
        select.value = button.dataset.value;
        syncSmartSelect(shell);
        setSmartSelectOpen(shell, false);
        trigger.focus({ preventScroll: true });
        if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      menu.addEventListener("keydown", (event) => {
        const option = event.target.closest(".smart-select-option");
        if (!option) return;
        const options = $$(".smart-select-option:not([disabled])", menu);
        const index = options.indexOf(option);
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          const nextIndex = event.key === "Home"
            ? 0
            : event.key === "End"
              ? options.length - 1
              : (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
          options[nextIndex]?.focus({ preventScroll: true });
          scrollSmartOptionIntoView(options[nextIndex], menu);
        } else if (["Enter", " "].includes(event.key)) {
          event.preventDefault();
          option.click();
        } else if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          setSmartSelectOpen(shell, false);
          trigger.focus({ preventScroll: true });
        } else if (event.key === "Tab") {
          setSmartSelectOpen(shell, false);
        }
      });
      select.addEventListener("change", () => syncSmartSelect(shell));
      syncSmartSelect(shell);
      if (window.lucide) window.lucide.createIcons({ root: menu });
    });
  }

  function refreshIcons(root = document) {
    enhanceSelects(root);
    if (window.lucide) window.lucide.createIcons({ root });
  }

  function setBootDone() {
    const boot = $("#boot-screen");
    if (!boot) return;
    boot.classList.add("is-done");
    window.setTimeout(() => { boot.hidden = true; }, 280);
  }

  function setTheme(theme) {
    const themes = ["sky", "jade", "sunset", "dark"];
    const next = themes.includes(theme) ? theme : "sky";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("airport-monitor-theme", next); } catch (_) { /* 浏览器禁用存储时忽略。 */ }
    $$('[data-theme-option]').forEach((button) => {
      button.setAttribute("aria-checked", String(button.dataset.themeOption === next));
    });
    const meta = $('meta[name="theme-color"]');
    if (meta) meta.content = { sky: "#f4f8ff", jade: "#f1f8f5", sunset: "#fff7f1", dark: "#17191d" }[next];
    requestAnimationFrame(redrawVisibleCharts);
  }

  function closeThemePickers(except = null) {
    $$('[data-theme-picker]').forEach((picker) => {
      if (picker === except) return;
      const trigger = $('[data-theme-trigger]', picker);
      const menu = $('[data-theme-menu]', picker);
      if (trigger) trigger.setAttribute("aria-expanded", "false");
      if (menu) menu.hidden = true;
    });
  }

  function setThemePickerOpen(picker, open) {
    if (!picker) return;
    closeThemePickers(open ? picker : null);
    const trigger = $('[data-theme-trigger]', picker);
    const menu = $('[data-theme-menu]', picker);
    if (!trigger || !menu) return;
    trigger.setAttribute("aria-expanded", String(open));
    menu.hidden = !open;
    if (open) {
      requestAnimationFrame(() => $('[aria-checked="true"]', menu)?.focus({ preventScroll: true }));
    }
  }

  function toast(title, message = "", kind = "success", timeout = 4200) {
    const region = $("#toast-region");
    const node = document.createElement("div");
    const icon = kind === "error" ? "circle-alert" : kind === "warning" ? "triangle-alert" : "circle-check";
    node.className = `toast toast-${kind}`;
    node.innerHTML = `<i data-lucide="${icon}"></i><div><strong>${escapeHtml(title)}</strong>${message ? `<p>${escapeHtml(message)}</p>` : ""}</div><button type="button" aria-label="关闭提示"><i data-lucide="x"></i></button>`;
    region.append(node);
    refreshIcons(node);
    const remove = () => {
      node.classList.add("is-leaving");
      window.setTimeout(() => node.remove(), 180);
    };
    $("button", node).addEventListener("click", remove);
    window.setTimeout(remove, timeout);
  }

  function showLogin(message = "") {
    state.me = null;
    stopPolling();
    $("#app-shell").hidden = true;
    $("#login-view").hidden = false;
    $("#login-error").hidden = !message;
    $("#login-error").textContent = message;
    $("#login-password").value = "";
    setTheme(document.documentElement.dataset.theme);
    refreshIcons($("#login-view"));
    setBootDone();
    requestAnimationFrame(() => $("#login-username").focus());
  }

  async function showShell(me) {
    state.me = me;
    $("#login-view").hidden = true;
    $("#app-shell").hidden = false;
    $("#current-user").textContent = me.username;
    try {
      const [targetData, settings] = await Promise.all([api("/api/targets"), api("/api/settings")]);
      state.targets = targetData.items;
      state.settings = settings;
    } catch (error) {
      toast("基础配置读取失败", error.message, "error");
    }
    setTheme(document.documentElement.dataset.theme);
    refreshIcons($("#app-shell"));
    setBootDone();
    const fromHash = location.hash.replace("#", "");
    await switchView(VIEW_META[fromHash] ? fromHash : "dashboard", false);
    startPolling();
  }

  async function bootstrap() {
    bindStaticEvents();
    try {
      const me = await api("/api/auth/me");
      await showShell(me);
    } catch (_) {
      showLogin();
    }
  }

  function setUserMenuOpen(open, returnFocus = false) {
    const menu = $("#user-menu");
    const trigger = $("#user-menu-button");
    if (!menu || !trigger) return;
    menu.hidden = !open;
    trigger.setAttribute("aria-expanded", String(open));
    trigger.classList.toggle("is-open", open);
    if (open) requestAnimationFrame(() => $("button:not([disabled])", menu)?.focus({ preventScroll: true }));
    if (!open && returnFocus) trigger.focus({ preventScroll: true });
  }

  function bindStaticEvents() {
    document.addEventListener("click", (event) => {
      const themeTrigger = event.target.closest("[data-theme-trigger]");
      const themeOption = event.target.closest("[data-theme-option]");
      if (themeTrigger) {
        const picker = themeTrigger.closest("[data-theme-picker]");
        setThemePickerOpen(picker, themeTrigger.getAttribute("aria-expanded") !== "true");
      } else if (themeOption) {
        setTheme(themeOption.dataset.themeOption);
        setThemePickerOpen(themeOption.closest("[data-theme-picker]"), false);
      } else if (!event.target.closest("[data-theme-picker]")) {
        closeThemePickers();
      }
      if (!event.target.closest(".smart-select") && !event.target.closest(".smart-select-menu")) closeSmartSelects();
      if (!event.target.closest("[data-sort-picker]")) closeSortPickers();
      if (!event.target.closest("#user-menu-button") && !event.target.closest("#user-menu")) {
        setUserMenuOpen(false);
      }
    });
    document.addEventListener("scroll", (event) => {
      if (event.target instanceof Element && event.target.closest(".smart-select-options")) return;
      closeSmartSelects();
      closeSortPickers();
    }, true);
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const openTrigger = $('[data-theme-trigger][aria-expanded="true"]');
      if (!openTrigger) return;
      setThemePickerOpen(openTrigger.closest("[data-theme-picker]"), false);
      openTrigger.focus({ preventScroll: true });
    });
    $("#login-form").addEventListener("submit", handleLogin);
    $("#toggle-password").addEventListener("click", () => {
      const field = $("#login-password");
      const visible = field.type === "text";
      field.type = visible ? "password" : "text";
      $("#toggle-password").innerHTML = `<i data-lucide="${visible ? "eye" : "eye-off"}"></i>`;
      $("#toggle-password").setAttribute("aria-label", visible ? "显示密码" : "隐藏密码");
      refreshIcons($("#toggle-password"));
    });
    $$("[data-view]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
    $("#user-menu-button").addEventListener("click", () => {
      const menu = $("#user-menu");
      setUserMenuOpen(menu.hidden);
    });
    $("#user-menu").addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setUserMenuOpen(false, true);
      }
    });
    $("#logout-button").addEventListener("click", handleLogout);
    window.addEventListener("hashchange", () => {
      const view = location.hash.replace("#", "");
      if (VIEW_META[view] && view !== state.view) switchView(view, false);
    });
    window.addEventListener("resize", () => {
      closeSmartSelects();
      closeSortPickers();
      clearTimeout(state.resizeTimer);
      state.resizeTimer = setTimeout(() => {
        redrawVisibleCharts();
        $$(".node-workbench").forEach(applySavedColumnLayout);
      }, 120);
    });
    document.addEventListener("keydown", (event) => {
      if (focusSearchShortcut(event)) return;
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if ($(".smart-select.is-open")) {
        closeSmartSelects(true);
        return;
      }
      if (event.key === "Escape" && $(".sort-picker.is-open")) {
        const trigger = $(".sort-picker.is-open .sort-picker-trigger");
        closeSortPickers();
        trigger?.focus({ preventScroll: true });
        return;
      }
      if (!$("#user-menu").hidden) {
        setUserMenuOpen(false, true);
        return;
      }
      if ($("#modal-root").children.length) closeModal();
    });
  }

  async function handleLogin(event) {
    event.preventDefault();
    const button = $("#login-submit");
    const error = $("#login-error");
    error.hidden = true;
    await busyButton(button, async () => {
      const me = await api("/api/auth/login", {
        method: "POST",
        body: {
          username: $("#login-username").value.trim(),
          password: $("#login-password").value
        }
      });
      await showShell(me);
    }, (failure) => {
      error.textContent = failure.message;
      error.hidden = false;
    });
  }

  async function handleLogout() {
    try { await api("/api/auth/logout", { method: "POST" }); } catch (_) { /* 本地会话仍会回到登录页。 */ }
    showLogin("已安全退出");
  }

  async function switchView(view, updateHash = true) {
    if (!VIEW_META[view]) view = "dashboard";
    closeSmartSelects();
    closeSortPickers();
    setUserMenuOpen(false);
    state.view = view;
    if (state.viewController) state.viewController.abort();
    state.viewController = new AbortController();
    $$(".page").forEach((page) => page.classList.toggle("is-active", page.dataset.page === view));
    $$("[data-view]").forEach((button) => button.classList.toggle("is-active", button.dataset.view === view));
    $("#view-kicker").textContent = VIEW_META[view][0];
    $("#view-title").textContent = VIEW_META[view][1];
    if (updateHash) history.replaceState(null, "", `#${view}`);
    $("#view-root").focus({ preventScroll: true });
    const loaders = {
      dashboard: loadDashboard,
      latency: loadLatency,
      nodes: loadNodes,
      subscriptions: loadSubscriptions,
      events: loadEvents,
      system: loadSystem
    };
    try {
      await loaders[view](false, state.viewController.signal);
    } catch (error) {
      if (error.name !== "AbortError") renderLoadError(view, error.message);
    }
  }

  function renderLoadError(view, message) {
    const target = $(`#${view}-content`);
    target.innerHTML = `<div class="state-panel"><span class="state-icon is-error"><i data-lucide="cloud-off"></i></span><h2>内容暂时无法载入</h2><p>${escapeHtml(message)}</p><button class="button button-secondary" type="button" data-retry-view="${view}"><i data-lucide="refresh-cw"></i>重新加载</button></div>`;
    $("[data-retry-view]", target).addEventListener("click", () => switchView(view, false));
    refreshIcons(target);
  }

  function loadingMarkup() {
    return `<div class="skeleton-toolbar skeleton"></div><div class="skeleton-summary skeleton"></div><div class="skeleton-table">${Array.from({ length: 7 }, () => '<span class="skeleton"></span>').join("")}</div>`;
  }

  function startPolling() {
    stopPolling();
    const tick = async () => {
      if (!state.me || document.hidden) return;
      try {
        const data = await api("/api/tasks");
        updateTaskIndicator(data.items);
      } catch (_) { /* 主界面已有连接错误反馈，轮询保持安静。 */ }
    };
    state.pollTimer = window.setInterval(tick, 5000);
    state.refreshTimer = window.setInterval(() => {
      if (document.hidden || state.activeTasks) return;
      if (state.view === "dashboard") loadDashboard(true).catch(() => {});
      if (state.view === "latency") loadLatency(true).catch(() => {});
      if (state.view === "nodes") loadNodes(true).catch(() => {});
    }, 45000);
    tick();
  }

  function stopPolling() {
    clearInterval(state.pollTimer);
    clearInterval(state.refreshTimer);
    state.pollTimer = null;
    state.refreshTimer = null;
  }

  function updateTaskIndicator(tasks) {
    const active = tasks.filter((task) => ["queued", "running"].includes(task.status));
    const wasActive = state.activeTasks;
    state.activeTasks = active.length > 0;
    const indicator = $("#task-indicator");
    indicator.hidden = !active.length;
    if (active.length) {
      const task = active[0];
      $("#task-indicator-text").textContent = `${taskKindLabel(task.kind)} ${task.completed}/${task.total}`;
    } else if (wasActive) {
      toast("检测任务已完成", "节点状态和趋势数据已更新。");
      state.trendCache.clear();
      if (state.view === "dashboard") loadDashboard(true).catch(() => {});
      if (state.view === "latency") loadLatency(true).catch(() => {});
      if (state.view === "nodes") loadNodes(true).catch(() => {});
    }
  }

  function taskKindLabel(kind) {
    return {
      single_check: "单节点复测",
      batch_check: "批量复测",
      full_check: "全部复测",
      scheduled_check: "定时检测",
      subscription_refresh: "订阅刷新",
      scheduled_refresh: "定时刷新"
    }[kind] || "后台任务";
  }

  function buildNodeQuery() {
    const query = new URLSearchParams();
    Object.entries(state.filters).forEach(([key, value]) => {
      if (value !== "" && value !== null && value !== undefined) query.set(key, String(value));
    });
    return query.toString();
  }

  async function loadDashboard(silent = false, signal) {
    const target = $("#dashboard-content");
    if (!silent) target.innerHTML = loadingMarkup();
    const nodeQuery = new URLSearchParams(buildNodeQuery());
    nodeQuery.set("enabled_only", "true");
    if (nodeQuery.get("status") === "paused") nodeQuery.delete("status");
    const [dashboardData, nodeData] = await Promise.all([
      api("/api/dashboard", { signal }),
      api(`/api/nodes?${nodeQuery.toString()}`, { signal })
    ]);
    state.dashboard = dashboardData;
    state.nodePage = nodeData;
    retainVisibleSelection(nodeData.items);
    renderDashboard();
  }

  async function loadNodes(silent = false, signal) {
    const target = $("#nodes-content");
    if (!silent) target.innerHTML = loadingMarkup();
    state.nodePage = await api(`/api/nodes?${buildNodeQuery()}`, { signal });
    retainVisibleSelection(state.nodePage.items);
    renderNodes();
  }

  function buildLatencyQuery() {
    const query = new URLSearchParams();
    Object.entries(state.latencyFilters).forEach(([key, value]) => {
      if (value !== "" && value !== null && value !== undefined) {
        query.set(key, String(value));
      }
    });
    return query.toString();
  }

  async function loadLatency(silent = false, signal) {
    const target = $("#latency-content");
    if (!silent) target.innerHTML = loadingMarkup();
    state.latency = await api(`/api/latency-summary?${buildLatencyQuery()}`, {
      signal
    });
    renderLatency();
  }

  function scoreMeta(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) {
      return { level: "unknown", label: "暂无评分", icon: "circle-help" };
    }
    if (Number(value) >= 90) {
      return { level: "healthy", label: "表现优秀", icon: "circle-check" };
    }
    if (Number(value) >= 70) {
      return { level: "warning", label: "表现一般", icon: "triangle-alert" };
    }
    return { level: "critical", label: "表现较差", icon: "circle-x" };
  }

  function availabilityLevel(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "unknown";
    return Number(value) >= 95 ? "healthy" : Number(value) >= 80 ? "warning" : "critical";
  }

  function latencyDirectionLabel(sort, direction) {
    const descending = direction === "desc";
    if (sort === "node_latency" || sort === "website_latency") {
      return descending ? "慢到快" : "快到慢";
    }
    if (sort === "name" || sort === "country") {
      return descending ? "倒序" : "正序";
    }
    return descending ? "高到低" : "低到高";
  }

  function periodCoverage(period) {
    const coverage = Number(period?.coverage_percent);
    if (!Number.isFinite(coverage)) return "";
    const confidence = {
      high: "高置信",
      medium: "中置信",
      low: "低置信",
      none: "无有效覆盖"
    }[period?.confidence] || "低置信";
    return `覆盖 ${formatNumber(coverage, 0)}% · ${confidence}`;
  }

  function latencySummaryMetric(label, value, detail, icon, level) {
    return `
      <div class="latency-summary-metric level-${level}">
        <span class="latency-summary-icon"><i data-lucide="${icon}"></i></span>
        <span><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong><em>${escapeHtml(detail)}</em></span>
      </div>`;
  }

  function latencyPeriodCell(period) {
    const noData = period.score === null
      && period.node_latency_p95_ms === null
      && period.website_latency_p95_ms === null
      && period.availability === null;
    if (noData) {
      return `
        <div class="latency-period-cell is-empty" aria-label="${escapeHtml(period.label)}暂无检测样本">
          <i data-lucide="database-zap"></i>
          <strong>暂无样本</strong>
          <small>该时间段尚未检测</small>
        </div>`;
    }
    const nodeLevel = latencyLevel(period.node_latency_p95_ms, [600, 1500]);
    const websiteLevel = latencyLevel(period.website_latency_p95_ms, [1800, 3500]);
    const onlineLevel = availabilityLevel(period.availability);
    const score = scoreMeta(period.score);
    return `
      <div class="latency-period-cell" aria-label="${escapeHtml(period.label)}统计">
        <div class="period-latency level-${nodeLevel}">
          <span><i data-lucide="radio-tower"></i>代理链路 P95</span>
          <strong>${formatLatency(period.node_latency_p95_ms)}</strong>
        </div>
        <div class="period-latency level-${websiteLevel}">
          <span><i data-lucide="globe-2"></i>网站访问 P95</span>
          <strong>${formatLatency(period.website_latency_p95_ms)}</strong>
        </div>
        <div class="period-result">
          <span class="period-online level-${onlineLevel}"><i data-lucide="chart-spline"></i><small>在线率</small><strong>${formatPercent(period.availability, 1)}</strong></span>
          <span class="period-score level-${score.level}" title="${escapeHtml(score.label)}"><i data-lucide="${score.icon}"></i><strong>${period.score === null ? "—" : formatNumber(period.score, 0)}</strong><small>分</small></span>
        </div>
        <small class="period-samples">覆盖 ${formatNumber(period.coverage_percent, 0)}% · 网站抵达 ${formatPercent(period.website_availability, 1)} · 重试 ${formatPercent(period.retry_rate, 1)}</small>
      </div>`;
  }

  function latencyNodeRow(node) {
    const overall = scoreMeta(node.overall_score);
    const onlineLevel = availabilityLevel(node.overall_availability);
    const overallPeriod = node.periods.find((period) => period.key === "720h")
      || node.periods[node.periods.length - 1];
    const coverage = periodCoverage(overallPeriod);
    const flag = /^[A-Z]{2}$/.test(node.country_code || "")
      ? node.country_code.toLowerCase()
      : "zz";
    return `
      <article class="latency-node-row">
        <div class="latency-node-summary">
          <button class="latency-node-identity" type="button" data-latency-open-node="${node.id}" aria-label="查看 ${escapeHtml(node.name)} 的检测详情">
            <img src="/static/flags/${escapeHtml(flag)}.svg" onerror="this.onerror=null;this.src='/static/flags/zz.svg'" alt="">
            <span><strong title="${escapeHtml(node.name)}">${escapeHtml(node.name)}</strong><small>${escapeHtml(node.region_name || "未知地区")} · ${escapeHtml(node.protocol)}</small></span>
            <i data-lucide="chevron-right"></i>
          </button>
          <div class="latency-overall-score level-${overall.level}">
            <span><small>30 天总评分</small><strong>${node.overall_score === null ? "—" : formatNumber(node.overall_score, 0)}<em> / 100</em></strong></span>
            <span><i data-lucide="${overall.icon}"></i>${escapeHtml(overall.label)}</span>
          </div>
          <div class="latency-overall-meta">
            <span class="level-${onlineLevel}"><i data-lucide="chart-spline"></i>30 天在线率 <strong>${formatPercent(node.overall_availability, 1)}</strong></span>
            <small>${node.overall_samples ? `依据 ${node.overall_samples} 次节点测速${coverage ? ` · ${coverage}` : ""}` : "尚无有效节点测速"} · ${relativeTime(node.last_checked_at)}</small>
          </div>
        </div>
        ${node.periods.map(latencyPeriodCell).join("")}
      </article>`;
  }

  function renderLatency() {
    const target = $("#latency-content");
    const data = state.latency || {
      items: [], windows: [], summary: {}, facets: { countries: [] },
      page: 1, pages: 1, total: 0
    };
    const summary = data.summary || {};
    const filters = state.latencyFilters;
    const score = scoreMeta(summary.average_score);
    const overallAvailabilityLevel = availabilityLevel(summary.availability_720h);
    const nodeLatencyLevel = latencyLevel(summary.node_latency_p95_720h_ms, [600, 1500]);
    const websiteLatencyLevel = latencyLevel(summary.website_latency_p95_720h_ms, [1800, 3500]);
    const countryOptions = (data.facets?.countries || []).map((item) => `
      <option value="${escapeHtml(item.code)}" ${filters.country === item.code ? "selected" : ""}>${escapeHtml(item.name)}（${item.count}）</option>`).join("");
    const sortOptions = [
      ["score", "30 天总评分"],
      ["availability", "30 天在线率"],
      ["node_latency", "代理链路 P95"],
      ["website_latency", "网站访问 P95"],
      ["name", "节点名称"],
      ["country", "国家 / 地区"]
    ].map(([value, label]) => `<option value="${value}" ${filters.sort === value ? "selected" : ""}>${label}</option>`).join("");
    const rows = data.items.map(latencyNodeRow).join("");
    const headers = data.windows.map((windowItem) => {
      const longWindow = windowItem.hours >= 168;
      return `<div class="latency-period-head"><strong>${escapeHtml(windowItem.label)}</strong><small>${longWindow ? `${windowItem.hours} 小时` : `最近 ${windowItem.hours}h`}</small></div>`;
    }).join("");
    const directionLabel = latencyDirectionLabel(filters.sort, filters.direction);
    target.innerHTML = `
      <div class="page-intro compact-intro latency-intro">
        <div><p class="eyebrow">真实链路长期表现</p><h2>六段时间，对照每个节点的稳定性</h2><p>在线率按可观测时间加权；监测机断网和数据缺口单独计入覆盖率，不再伪装成节点成功或失败。</p></div>
        <div class="heading-actions">
          <button class="button button-quiet" type="button" data-latency-action="score-guide"><i data-lucide="circle-help"></i>评分规则</button>
          <button class="button button-secondary" type="button" data-latency-action="refresh"><i data-lucide="refresh-cw"></i>刷新统计</button>
        </div>
      </div>
      <section class="latency-summary-ribbon" aria-label="30 天总体统计">
        ${latencySummaryMetric("30 天整体评分", summary.average_score === null || summary.average_score === undefined ? "— / 100" : `${formatNumber(summary.average_score, 0)} / 100`, summary.best_node ? `最佳：${summary.best_node.name} ${formatNumber(summary.best_node.score, 0)} 分` : `${summary.nodes_scored || 0} 个节点已有评分`, "gauge", score.level)}
        ${latencySummaryMetric("30 天时间在线率", formatPercent(summary.availability_720h, 1), `平均覆盖 ${formatPercent(summary.coverage_720h, 0)} · 按节点等权`, "chart-spline", overallAvailabilityLevel)}
        ${latencySummaryMetric("代理链路 P95", formatLatency(summary.node_latency_p95_720h_ms), "完整代理通道的尾部耗时", "radio-tower", nodeLatencyLevel)}
        ${latencySummaryMetric("网站访问 P95", formatLatency(summary.website_latency_p95_720h_ms), `网站抵达率 ${formatPercent(summary.website_availability_720h, 1)}`, "globe-2", websiteLatencyLevel)}
      </section>
      <section class="latency-panel">
        <div class="latency-toolbar">
          <label class="search-control"><i data-lucide="search"></i><input type="search" data-latency-filter="search" value="${escapeHtml(filters.search)}" placeholder="搜索节点、订阅或地区" aria-label="搜索延迟统计节点"><kbd>Ctrl K</kbd></label>
          <div class="select-control"><i data-lucide="map-pinned"></i><select data-latency-filter="country" data-select-kind="country" aria-label="延迟统计地区筛选"><option value="">全部地区</option>${countryOptions}</select></div>
          <div class="select-control"><i data-lucide="arrow-up-down"></i><select data-latency-filter="sort" data-select-kind="latency_sort" aria-label="延迟统计排序依据">${sortOptions}</select></div>
          <button class="button button-quiet latency-direction" type="button" data-latency-action="direction" title="切换排列方向"><i data-lucide="${filters.direction === "desc" ? "arrow-down-wide-narrow" : "arrow-up-narrow-wide"}"></i>${escapeHtml(directionLabel)}</button>
          ${(filters.search || filters.country) ? '<button class="button button-quiet" type="button" data-latency-action="reset"><i data-lucide="filter-x"></i>清除筛选</button>' : ""}
          <span class="latency-toolbar-count">共 <strong>${data.total}</strong> 个启用节点</span>
        </div>
        ${rows ? `
          <div class="latency-table-scroll" tabindex="0" aria-label="可横向滚动查看六个统计周期">
            <div class="latency-table">
              <div class="latency-table-head"><div class="latency-node-head"><strong>节点与总评分</strong><small>30 天窗口 · 标明实际覆盖</small></div>${headers}</div>
              <div class="latency-table-body">${rows}</div>
            </div>
          </div>` : `
          <div class="state-panel"><span class="state-icon"><i data-lucide="chart-no-axes-column-increasing"></i></span><h3>${data.total ? "当前页没有节点" : "没有符合条件的启用节点"}</h3><p>${filters.search || filters.country ? "清除筛选后可以查看其他节点。" : "启用节点并完成首次检测后，这里会生成多周期统计。"}</p>${filters.search || filters.country ? '<button class="button button-secondary" type="button" data-latency-action="reset"><i data-lucide="filter-x"></i>清除筛选</button>' : ""}</div>`}
        <footer class="pagination">
          <span>第 ${data.page} / ${data.pages} 页 · 数据更新于 ${formatTime(data.generated_at)}</span>
          <div class="pagination-size"><span>每页</span><select data-latency-filter="page_size" data-select-kind="page_size" data-select-compact="true" aria-label="延迟统计每页节点数量">${[10, 20, 30, 50, 100].map((value) => `<option value="${value}" ${Number(filters.page_size) === value ? "selected" : ""}>${value} 个节点</option>`).join("")}</select></div>
          <div><button class="icon-button" type="button" data-latency-page="${data.page - 1}" ${data.page <= 1 ? "disabled" : ""} aria-label="上一页"><i data-lucide="chevron-left"></i></button><button class="icon-button" type="button" data-latency-page="${data.page + 1}" ${data.page >= data.pages ? "disabled" : ""} aria-label="下一页"><i data-lucide="chevron-right"></i></button></div>
        </footer>
      </section>`;
    bindLatencyPanel(target);
    refreshIcons(target);
  }

  function bindLatencyPanel(root) {
    const search = $('[data-latency-filter="search"]', root);
    if (search) {
      search.addEventListener("input", debounce(() => {
        state.latencyFilters.search = search.value.trim();
        state.latencyFilters.page = 1;
        loadLatency(true).catch((error) => toast("延迟统计未更新", error.message, "error"));
      }, 280));
    }
    $$("select[data-latency-filter]", root).forEach((select) => {
      select.addEventListener("change", () => {
        const key = select.dataset.latencyFilter;
        state.latencyFilters[key] = key === "page_size" ? Number(select.value) : select.value;
        state.latencyFilters.page = 1;
        loadLatency(true).catch((error) => toast("延迟统计未更新", error.message, "error"));
      });
    });
    root.onclick = (event) => {
      const pageButton = event.target.closest("[data-latency-page]");
      if (pageButton && !pageButton.disabled) {
        state.latencyFilters.page = Number(pageButton.dataset.latencyPage);
        loadLatency(true).catch((error) => toast("延迟统计未更新", error.message, "error"));
        return;
      }
      const nodeButton = event.target.closest("[data-latency-open-node]");
      if (nodeButton) {
        openNodeDetail(Number(nodeButton.dataset.latencyOpenNode));
        return;
      }
      const action = event.target.closest("[data-latency-action]");
      if (!action) return;
      if (action.dataset.latencyAction === "direction") {
        state.latencyFilters.direction = state.latencyFilters.direction === "desc" ? "asc" : "desc";
        state.latencyFilters.page = 1;
        loadLatency(true).catch((error) => toast("延迟统计未更新", error.message, "error"));
      } else if (action.dataset.latencyAction === "reset") {
        state.latencyFilters.search = "";
        state.latencyFilters.country = "";
        state.latencyFilters.page = 1;
        loadLatency(true).catch((error) => toast("延迟统计未更新", error.message, "error"));
      } else if (action.dataset.latencyAction === "score-guide") {
        openLatencyScoreGuide();
      } else if (action.dataset.latencyAction === "refresh") {
        busyButton(action, async () => {
          await loadLatency(true);
          toast("延迟统计已刷新", "六个时间窗口已使用最新检测数据重新计算。");
        });
      }
    };
  }

  function openLatencyScoreGuide() {
    openModal(`
      <section class="modal latency-score-guide" role="dialog" aria-modal="true" aria-labelledby="latency-score-title">
        <header class="modal-head"><div><p class="eyebrow">透明评分</p><h2 id="latency-score-title">总评分如何计算</h2><p>最近 720 小时按真实时间状态、网站抵达、P95 尾部延迟、抖动和重试共同评分；监测机断网只降低覆盖置信度。</p></div><button class="icon-button" type="button" data-modal-close aria-label="关闭"><i data-lucide="x"></i></button></header>
        <div class="modal-body">
          <div class="score-formula" aria-label="评分权重">
            <div><span><i data-lucide="chart-spline"></i>时间在线率</span><strong>45%</strong><small>按状态持续时间计算，离线直到恢复都持续扣分</small></div>
            <div><span><i data-lucide="orbit"></i>网站抵达率</span><strong>20%</strong><small>所有已启用网站的真实可达比例</small></div>
            <div><span><i data-lucide="radio-tower"></i>代理链路 P95</span><strong>15%</strong><small>600 ms 内优秀，超过 1500 ms 明显扣分</small></div>
            <div><span><i data-lucide="globe-2"></i>网站访问 P95</span><strong>10%</strong><small>1800 ms 内优秀，超过 3500 ms 明显扣分</small></div>
            <div><span><i data-lucide="activity"></i>稳定性</span><strong>10%</strong><small>综合 P95 抖动和失败后重试比例</small></div>
          </div>
          <div class="score-explanation">
            <p><i data-lucide="shield-check"></i><span><strong>90–100 分：表现优秀</strong><small>在线率、网站抵达和尾部体验都较稳定。</small></span></p>
            <p><i data-lucide="triangle-alert"></i><span><strong>70–89 分：表现一般</strong><small>节点可能可用，但至少一项稳定性指标需要关注。</small></span></p>
            <p><i data-lucide="circle-x"></i><span><strong>0–69 分：表现较差</strong><small>长期离线、网站不可达或尾部延迟明显偏高。</small></span></p>
            <p><i data-lucide="circle-help"></i><span><strong>覆盖率与置信度</strong><small>未知数据不再重新分配权重抬高总分；覆盖不足会明确显示低置信。</small></span></p>
          </div>
          <p class="modal-note"><i data-lucide="info"></i>代理链路指标通过完整协议通道访问固定轻量 204 目标，并非纯入口 TCP 延迟；网站访问指标是从监测机经节点到目标网站的完整端到端耗时。</p>
        </div>
      </section>
    `);
  }

  function retainVisibleSelection(items = []) {
    const visibleIds = new Set(items.map((node) => node.id));
    state.selected.forEach((nodeId) => {
      if (!visibleIds.has(nodeId)) state.selected.delete(nodeId);
    });
  }

  function nodeStatusMeta(status) {
    return NODE_STATUS[status] || NODE_STATUS.unknown;
  }

  function statusBadge(status, detail = "", presentation = null) {
    const meta = presentation || nodeStatusMeta(status);
    const hint = detail ? ` title="${escapeHtml(detail)}"` : "";
    const accessible = detail ? `${meta.label}。${detail}` : meta.label;
    return `<span class="status-badge level-${meta.level}" aria-label="${escapeHtml(accessible)}"${hint}><i data-lucide="${meta.icon}"></i><span>${escapeHtml(meta.label)}</span></span>`;
  }

  function degradedPresentation(statuses) {
    const items = [];
    for (const status of DEGRADED_STATUS_ORDER) {
      if (!statuses.includes(status)) continue;
      const item = DEGRADED_PRESENTATION[status];
      if (item && !items.some((existing) => existing.label === item.label)) items.push(item);
    }
    if (!items.length) return nodeStatusMeta("degraded");
    return {
      label: `代理可用，${items.map((item) => item.label).join(" / ")}`,
      icon: items[0].icon,
      level: "warning"
    };
  }

  function nodeStatusPresentation(node) {
    const visualStatus = node.enabled ? node.current_status : "paused";
    if (visualStatus !== "degraded") return nodeStatusMeta(visualStatus);
    if (node.node_probe_enabled) return nodeStatusMeta("degraded");
    const statuses = (node.active_tests || [])
      .map((key) => node.services?.[key]?.status)
      .filter(Boolean);
    return degradedPresentation(statuses);
  }

  function runStatusPresentation(run) {
    if (run.status !== "degraded") return nodeStatusMeta(run.status);
    if (run.node_probe_status) return nodeStatusMeta("degraded");
    return degradedPresentation(run.error_type ? [run.error_type] : []);
  }

  function featureBadge(enabled, onLabel, offLabel) {
    return `<span class="status-badge level-${enabled ? "healthy" : "unknown"}"><i data-lucide="${enabled ? "circle-check" : "circle-pause"}"></i><span>${escapeHtml(enabled ? onLabel : offLabel)}</span></span>`;
  }

  function metricMeter(value, label, kind = "health", compact = false) {
    const amount = clamp(value);
    const missing = value === null || value === undefined;
    const display = missing
      ? "—"
      : kind === "health"
        ? `${formatNumber(value, 0)} / 100`
        : formatPercent(value, compact ? 0 : 1);
    const icon = kind === "health" ? "gauge" : "chart-spline";
    return `<span class="metric-meter metric-${kind} ${compact ? "is-compact" : ""}" role="img" aria-label="${escapeHtml(label)} ${escapeHtml(display)}"><span class="metric-symbol"><i data-lucide="${icon}"></i></span><span class="metric-copy"><strong>${escapeHtml(display)}</strong><small>${escapeHtml(label)}</small><span class="metric-track" aria-hidden="true"><i style="width:${missing ? 0 : amount}%"></i></span></span></span>`;
  }

  function brandLogo(targetKey, extra = "") {
    const target = state.targets.find((item) => item.key === targetKey);
    const icon = target?.icon || targetKey;
    const label = target?.label || targetKey;
    return `<span class="brand-logo ${extra}" title="${escapeHtml(label)}"><img src="/static/brand/${escapeHtml(icon)}.svg" alt="${escapeHtml(label)}"></span>`;
  }

  function serviceStatusMarkup(key, result) {
    const status = result?.status || "uncertain";
    const meta = SERVICE_STATUS[status] || SERVICE_STATUS.uncertain;
    const latency = result?.latency_ms === null || result?.latency_ms === undefined ? "" : ` · ${formatLatency(result.latency_ms)}`;
    const description = (state.targets.find((item) => item.key === key)?.label || key) + "：" + meta[0] + latency;
    return `<span class="service-mark level-${meta[1]}" title="${escapeHtml(description)}" role="img" aria-label="${escapeHtml(description)}">${brandLogo(key, "is-tiny")}<span class="service-state-icon"><i data-lucide="${meta[2]}"></i></span></span>`;
  }

  function locationSourceLabel(node) {
    if (node.location_source === "auto") {
      return `出口 IP 自动识别，${node.location_provider_count || 0} 个来源一致`;
    }
    if (node.location_source === "manual") return "管理员手动设置";
    if (node.location_source === "name") return "暂按节点名称推断，复测后会自动核实";
    return "尚未完成出口 IP 识别";
  }

  function flagMarkup(code, region, node = {}) {
    const normalized = /^[A-Z]{2}$/.test(code || "") ? code.toLowerCase() : "zz";
    const label = region || "未知地区";
    return `<span class="region-cell" title="${escapeHtml(locationSourceLabel(node))}"><img class="flag-icon" src="/static/flags/${normalized}.svg" onerror="this.onerror=null;this.src='/static/flags/zz.svg'" alt="${escapeHtml(label)}"><span>${escapeHtml(label)}</span></span>`;
  }

  function nodeStatusExplanation(node) {
    if (!node.enabled) return "该节点已停用，不参加自动检测";
    if (node.node_probe_enabled) {
      const successes = Number(node.last_node_probe_successes || 0);
      const samples = Number(node.last_node_probe_samples || 0);
      const sampleText = samples ? `${successes}/${samples} 次代理通道校验成功` : "等待首次代理通道校验";
      if (node.current_status === "online") {
        return `${sampleText}；各网站访问结果在右侧单独显示`;
      }
      if (node.current_status === "degraded") {
        return `${sampleText}；${ERROR_LABELS[node.last_error_type] || "本地连接节点存在波动"}`;
      }
      if (node.current_status === "offline") {
        return ERROR_LABELS[node.last_error_type] || "本地无法通过该节点完成轻量测速";
      }
      return ERROR_LABELS[node.last_error_type] || sampleText;
    }
    if (node.current_status === "online") return "代理通道和已启用网站均可正常访问";
    if (node.current_status === "offline") {
      return ERROR_LABELS[node.last_error_type] || "代理通道无法建立";
    }
    if (node.current_status === "unknown" || node.current_status === "pending") {
      return ERROR_LABELS[node.last_error_type] || "需要等待下一次检测确认";
    }
    const reasons = [];
    for (const status of DEGRADED_STATUS_ORDER) {
      const names = (node.active_tests || [])
        .filter((key) => node.services?.[key]?.status === status)
        .map((key) => state.targets.find((item) => item.key === key)?.label || key);
      if (names.length) reasons.push(`${names.join("、")} ${SERVICE_REASON_LABELS[status]}`);
    }
    if (reasons.length) return reasons.join("；");
    return "代理通道可用，但网站结果需要进一步确认";
  }

  function latencyLevel(value, thresholds) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "unknown";
    return Number(value) > thresholds[1] ? "critical" : Number(value) > thresholds[0] ? "warning" : "healthy";
  }

  function nodeLatencyMethodDetail(node) {
    const method = node.last_node_latency_method || node.node_latency_method;
    const successes = Number(node.last_node_probe_successes ?? node.node_probe_successes ?? 0);
    const samples = Number(node.last_node_probe_samples ?? node.node_probe_samples ?? 0);
    const sampleText = samples ? `${successes}/${samples} 次成功` : "等待首次测速";
    if (method === "protocol_urltest") {
      return `局域网监测小主机通过该节点的完整代理协议链路，${sampleText}；连续访问固定轻量 204 目标并取中位数，不使用 CDN 或中继入口的裸 TCP 握手`;
    }
    if (method === "endpoint_only_legacy" || method === "tcp_connect") {
      return "这是升级前的入口握手记录，不能代表完整代理节点链路，已从当前延迟和趋势中排除";
    }
    return "等待通过完整代理协议链路完成首次小流量测速";
  }

  function nodeLatencyMethodShort(value) {
    if (value === "protocol_urltest") return "真实代理链路";
    if (value === "endpoint_only_legacy" || value === "tcp_connect") return "旧入口值已排除";
    return "等待首次测速";
  }

  function dualLatencyMarkup(node, extraClass = "") {
    const websiteLevel = latencyLevel(node.last_website_latency_ms, [1800, 3500]);
    const nodeLevel = latencyLevel(
      node.last_latency_ms,
      [800, 1800]
    );
    const nodeValue = node.node_probe_enabled
      ? formatLatency(node.last_latency_ms)
      : "测速已关闭";
    const nodeDetail = node.node_probe_enabled
      ? `${nodeLatencyMethodDetail(node)}${node.last_node_jitter_ms === null || node.last_node_jitter_ms === undefined ? "" : `；抖动 ${formatLatency(node.last_node_jitter_ms)}`}`
      : "可在系统状态的检测策略中重新启用";
    return `<span class="dual-latency ${extraClass}">
      <span class="latency-line is-website level-${websiteLevel}" title="监测小主机通过该节点完整访问当前启用网站的平均耗时"><i data-lucide="globe-2"></i><small>节点 → 网站</small><strong>${formatLatency(node.last_website_latency_ms)}</strong></span>
      <span class="latency-line is-node level-${node.node_probe_enabled ? nodeLevel : "unknown"}" title="${escapeHtml(nodeDetail)}"><i data-lucide="radio-tower"></i><small>本地 → 节点</small><strong>${escapeHtml(nodeValue)}</strong></span>
    </span>`;
  }

  function friendlyDetail(value, fallback = "暂无附加说明") {
    if (!value) return fallback;
    return ERROR_LABELS[value] || String(value);
  }

  function openMetricGuide() {
    openModal(`
      <section class="modal modal-medium metric-guide" role="dialog" aria-modal="true" aria-labelledby="metric-guide-title">
        <header class="modal-head"><div><p class="eyebrow">指标说明</p><h2 id="metric-guide-title">每个状态都代表什么</h2><p>这里没有装饰性圆点；颜色、图标和文字表达同一个结论。</p></div><button class="icon-button" type="button" data-modal-close aria-label="关闭"><i data-lucide="x"></i></button></header>
        <div class="modal-body">
          <div class="guide-status-grid">
            <div class="level-healthy"><i data-lucide="shield-check"></i><span><strong>正常可用</strong><small>完整代理链路测速全部成功；各网站访问结果在节点行中分别显示。</small></span></div>
            <div class="level-warning"><i data-lucide="triangle-alert"></i><span><strong>节点连接不稳定</strong><small>完整代理链路只有部分测速成功，节点仍可能可用，但当前连接存在丢失或明显波动。</small></span></div>
            <div class="level-critical"><i data-lucide="shield-x"></i><span><strong>无法使用</strong><small>本地无法通过该节点建立代理通道，或发生超时、TLS 等明确错误。</small></span></div>
            <div class="level-unknown"><i data-lucide="shield-question"></i><span><strong>暂时无法判断</strong><small>尚未检测，或页面结果不足以得出可靠结论。</small></span></div>
          </div>
          <dl class="guide-metrics">
            <div><dt><i data-lucide="gauge"></i>健康评分</dt><dd>综合真实代理链路成功率、链路延迟和抖动计算，满分为 100；网站限制不会把节点误判为离线。</dd></div>
            <div><dt><i data-lucide="chart-spline"></i>24 小时在线率</dt><dd>过去 24 小时内，代理通道能够完成真实小流量请求的检测占比。</dd></div>
            <div><dt><i data-lucide="radio-tower"></i>本地 → 节点</dt><dd>局域网监测小主机通过节点的完整代理协议链路访问固定轻量 204 目标，连续 3 次取中位数；不会把附近 CDN 或中继入口的几毫秒握手冒充节点延迟。</dd></div>
            <div><dt><i data-lucide="globe-2"></i>节点 → 网站</dt><dd>通过该节点完整打开当前启用网站并读取响应的平均耗时，包含 TLS、网站响应和内容传输。</dd></div>
            <div><dt><i data-lucide="orbit"></i>网站访问结果</dt><dd>网站 Logo 旁的状态图标会明确显示正常、需要登录、地区限制、响应异常或无法连接。</dd></div>
            <div><dt><i data-lucide="map-pinned"></i>出口国家 / 地区</dt><dd>平台通过该节点实际联网，再用多个公开来源核对出口 IP；至少两个来源结论一致才更新。</dd></div>
          </dl>
        </div>
      </section>
    `);
  }

  function performanceMetric(label, value, kind, icon, detail) {
    const available = value !== null && value !== undefined && Number.isFinite(Number(value));
    const number = available ? Number(value) : null;
    const profiles = {
      usage: { warning: 75, critical: 90, maximum: 100, suffix: "%", normal: "占用正常", warned: "占用偏高", failed: "占用过高" },
      disk: { warning: 80, critical: 92, maximum: 100, suffix: "%", normal: "空间充足", warned: "空间趋紧", failed: "空间不足" },
      cpuTemperature: { warning: 80, critical: 95, maximum: 100, suffix: " °C", normal: "温度正常", warned: "温度偏高", failed: "温度过高" },
      diskTemperature: { warning: 55, critical: 70, maximum: 100, suffix: " °C", normal: "温度正常", warned: "温度偏高", failed: "温度过高" }
    };
    const profile = profiles[kind] || profiles.usage;
    const level = !available ? "unknown" : number >= profile.critical ? "critical" : number >= profile.warning ? "warning" : "healthy";
    const stateText = !available
      ? (kind.includes("Temperature") ? "传感器不可用" : "等待采样")
      : level === "critical" ? profile.failed : level === "warning" ? profile.warned : profile.normal;
    const display = available ? `${formatNumber(number, 1)}${profile.suffix}` : "—";
    const meter = available ? clamp(number / profile.maximum * 100) : 0;
    const stateIcon = { healthy: "circle-check", warning: "triangle-alert", critical: "circle-x", unknown: "circle-help" }[level];
    const accessible = `${label} ${display}，${detail}，${stateText}`;
    return `
      <div class="performance-metric level-${level}" role="img" aria-label="${escapeHtml(accessible)}">
        <span class="performance-icon"><i data-lucide="${icon}"></i></span>
        <span class="performance-copy">
          <small>${escapeHtml(label)}</small>
          <strong>${escapeHtml(display)}</strong>
          <span class="performance-track" aria-hidden="true"><i style="width:${meter}%"></i></span>
          <em><i data-lucide="${stateIcon}"></i>${escapeHtml(detail)} · ${escapeHtml(stateText)}</em>
        </span>
       </div>`;
  }

  function hardwareProfile(hardware = {}) {
    const items = [
      ["cpu", "cpu", "处理器", hardware.cpu],
      ["memory-stick", "memory", "内存", hardware.memory],
      ["hard-drive", "disk", "硬盘", hardware.disk]
    ].filter((item) => typeof item[3] === "string" && item[3].trim());
    if (!items.length) return "";
    return `
      <dl class="hardware-profile" aria-label="小主机硬件配置">
        ${items.map(([icon, kind, label, value]) => `
          <div class="hardware-item hardware-${kind}">
            <dt><i data-lucide="${icon}"></i>${escapeHtml(label)}</dt>
            <dd>${escapeHtml(value.trim())}</dd>
          </div>`).join("")}
      </dl>`;
  }

  function performanceRibbon(system = {}, hardware = {}) {
    return `
      <section class="performance-ribbon" aria-label="小主机性能监测">
        <header class="performance-heading">
          <span class="performance-heading-icon"><i data-lucide="server-cog"></i></span>
          <div class="performance-heading-copy">
            <div class="performance-heading-title">
              <strong>小主机性能</strong>
              <span class="performance-sampling"><i data-lucide="clock-3"></i>每 60 秒轻量采样 · ${relativeTime(system.sampled_at)}</span>
            </div>
            ${hardwareProfile(hardware)}
          </div>
        </header>
        ${performanceMetric("整机 CPU", system.system_cpu_percent, "usage", "cpu", "全部核心综合")}
        ${performanceMetric("内存占用", system.system_memory_percent, "usage", "memory-stick", "物理内存总量")}
        ${performanceMetric("硬盘占用", system.disk_percent, "disk", "hard-drive", "系统盘")}
        ${performanceMetric("CPU 温度", system.cpu_temperature_c, "cpuTemperature", "thermometer", "CPU Package")}
        ${performanceMetric("硬盘温度", system.disk_temperature_c, "diskTemperature", "thermometer", "SMART 实测")}
      </section>`;
  }

  function renderDashboard() {
    const summary = state.dashboard.summary;
    const monitoring = state.dashboard.monitoring;
    const serviceValues = Object.values(state.dashboard.service_rates || {});
    const serviceReach = serviceValues.length
      ? serviceValues.reduce((sum, item) => sum + Number(item.rate || 0), 0) / serviceValues.length
      : null;
    const target = $("#dashboard-content");
    const summaryLevel = summary.health === null
      ? "unknown"
      : summary.health >= 90 ? "healthy" : summary.health >= 60 ? "warning" : "critical";
    const onlineLevel = summary.nodes_offline ? "critical" : summary.nodes_online ? "healthy" : "unknown";
    const observer = monitoring.observer || {};
    const observerOffline = observer.status === "offline";
    const monitoringPaused = monitoring.scheduler_paused || observerOffline;
    target.innerHTML = `
      <div class="summary-ribbon">
        <div class="summary-primary">
          <span class="summary-symbol level-${summaryLevel}"><i data-lucide="gauge"></i></span>
          <span><small>节点健康评分</small><strong>${formatNumber(summary.health, 0)}<em> / 100</em></strong><p>${summary.nodes_degraded ? `${summary.nodes_degraded} 个节点连接存在波动` : "轻量节点测速整体稳定"}</p></span>
        </div>
        <div class="summary-stat"><span class="summary-symbol level-${onlineLevel}"><i data-lucide="radio-tower"></i></span><span><small>节点连接可用</small><strong>${summary.nodes_online}<em> / ${summary.nodes_total}</em></strong><p>${summary.nodes_offline ? `${summary.nodes_offline} 个节点测速失败` : "所有启用节点都能连接"}</p></span></div>
        <div class="summary-stat"><span class="summary-symbol level-${summary.availability_24h >= 90 ? "healthy" : summary.availability_24h === null ? "unknown" : "warning"}"><i data-lucide="chart-spline"></i></span><span><small>24 小时时间在线率</small><strong>${formatPercent(summary.availability_24h, 1)}</strong><p>按可观测状态持续时间计算</p></span></div>
        <div class="summary-stat"><span class="summary-symbol level-${serviceReach >= 80 ? "healthy" : serviceReach === null ? "unknown" : "warning"}"><i data-lucide="orbit"></i></span><span><small>目标网站抵达率</small><strong>${formatPercent(serviceReach, 0)}</strong><p>成功取得目标网站响应</p></span></div>
        <div class="summary-monitor ${monitoringPaused ? "is-paused" : ""}"><span class="summary-symbol level-${monitoringPaused ? "warning" : "healthy"}"><i data-lucide="${observerOffline ? "unplug" : monitoring.scheduler_paused ? "pause" : "scan-line"}"></i></span><span><small>${observerOffline ? "监测网络已断开" : monitoring.scheduler_paused ? "自动检测已暂停" : "自动检测运行中"}</small><strong>${observerOffline ? "等待网线恢复" : relativeTime(monitoring.last_check_at)}</strong><p>${observerOffline ? "恢复后立即全量复测" : monitoring.scheduler_paused ? "仍可手动复测" : `在线约 ${monitoring.check_interval_minutes} 分钟；离线约 ${monitoring.offline_check_interval_minutes} 分钟复测`}</p></span></div>
      </div>
      ${performanceRibbon(state.dashboard.system || {}, state.dashboard.hardware || {})}
      ${nodeWorkbench("dashboard")}
    `;
    bindNodeWorkbench(target);
    refreshIcons(target);
    drawExpandedCharts(target);
  }

  function renderNodes() {
    const target = $("#nodes-content");
    target.innerHTML = `
      <div class="page-intro compact-intro">
        <div><p class="eyebrow">节点目录</p><h2>筛选、复测与定位异常链路</h2><p>列表只加载当前页；历史曲线在展开时按需读取。</p></div>
        <div class="heading-actions"><button class="button button-secondary" type="button" data-action="check-all"><i data-lucide="scan-line"></i>复测全部启用节点</button></div>
      </div>
      ${nodeWorkbench("nodes")}
    `;
    bindNodeWorkbench(target);
    refreshIcons(target);
    drawExpandedCharts(target);
  }

  function columnHeaderMarkup(key, label, content = "", extraClass = "") {
    const definition = NODE_COLUMN_LIMITS[key];
    const accessibleLabel = definition?.label || `${label}列`;
    return `<span class="column-head ${extraClass}" data-column-key="${key}">
      ${content || `<span class="column-head-label">${escapeHtml(label)}</span>`}
      <button class="column-resizer" type="button" data-column-resizer="${key}"
        role="separator" aria-orientation="vertical"
        aria-label="调整${escapeHtml(accessibleLabel)}宽度"
        title="拖动调整${escapeHtml(accessibleLabel)}宽度；方向键可微调"></button>
    </span>`;
  }

  function nodeWorkbench(mode) {
    const data = state.nodePage || { items: [], facets: { countries: [] }, page: 1, pages: 1, total: 0 };
    const filters = state.filters;
    const statusValues = mode === "dashboard"
      ? ["online", "degraded", "offline", "unknown", "pending"]
      : ["online", "degraded", "offline", "unknown", "pending", "paused"];
    const selectedStatus = mode === "dashboard" && filters.status === "paused" ? "" : filters.status;
    const selectedVisible = data.items.filter((node) => state.selected.has(node.id)).length;
    const allSelected = data.items.length > 0 && selectedVisible === data.items.length;
    const countryOptions = (data.facets?.countries || []).map((item) => `<option value="${item.code}" ${filters.country === item.code ? "selected" : ""}>${escapeHtml(item.name)} (${item.count})</option>`).join("");
    const serviceOptions = state.targets.filter((item) => state.settings?.enabled_targets?.includes(item.key)).map((item) => `<option value="${item.key}" ${filters.service === item.key ? "selected" : ""}>${escapeHtml(item.label)}</option>`).join("");
    const selectedNodes = data.items.filter((node) => state.selected.has(node.id));
    const canEnableSelected = selectedNodes.some((node) => !node.enabled);
    const canDisableSelected = selectedNodes.some((node) => node.enabled);
    const rows = data.items.length ? data.items.map((node) => nodeRow(node, mode)).join("") : `
      <div class="state-panel is-inline">
        <span class="state-icon"><i data-lucide="search-x"></i></span>
        <h3>没有符合条件的节点</h3>
        <p>调整搜索词或筛选条件后再试。</p>
        <button class="button button-secondary" type="button" data-action="reset-filters"><i data-lucide="rotate-ccw"></i>清除筛选</button>
      </div>`;
    return `
      <section class="node-workbench" data-workbench="${mode}">
        <div class="workbench-toolbar">
          <label class="search-control"><span class="sr-only">搜索节点</span><i data-lucide="search"></i><input type="search" value="${escapeHtml(filters.search)}" placeholder="搜索节点、协议、订阅或地区" data-filter="search" autocomplete="off"><kbd>Ctrl K</kbd></label>
          <div class="filter-group">
            <div class="select-control"><i data-lucide="shield-half"></i><select data-filter="status" data-select-kind="status" aria-label="状态筛选"><option value="" ${selectedStatus === "" ? "selected" : ""}>全部状态</option>${statusValues.map((value) => `<option value="${value}" ${selectedStatus === value ? "selected" : ""}>${nodeStatusMeta(value).label}</option>`).join("")}</select></div>
            <div class="select-control"><i data-lucide="map-pinned"></i><select data-filter="country" data-select-kind="country" aria-label="地区筛选"><option value="">全部地区</option>${countryOptions}</select></div>
            <div class="select-control"><i data-lucide="orbit"></i><select data-filter="service" data-select-kind="service" aria-label="检测项筛选"><option value="">全部检测项</option>${serviceOptions}</select></div>
            ${sortPickerMarkup(filters, mode)}
          </div>
          <div class="toolbar-spacer"></div>
          <div class="trend-global-actions">
            <button class="button button-quiet button-small" type="button" data-action="explain-metrics"><i data-lucide="circle-help"></i>指标说明</button>
            <button class="button button-quiet button-small column-reset-button" type="button" data-action="reset-columns" title="恢复所有列的自适应宽度"><i data-lucide="columns-3"></i>恢复列宽</button>
            <button class="button button-quiet button-small" type="button" data-action="expand-all"><i data-lucide="panel-bottom-open"></i>全部展开</button>
            <button class="button button-quiet button-small" type="button" data-action="collapse-all"><i data-lucide="panel-bottom-close"></i>全部折叠</button>
          </div>
        </div>
        ${mode === "nodes" ? `
        <div class="node-management-bar" role="toolbar" aria-label="节点批量管理">
          <div class="node-selection-cluster">
            <button class="button button-secondary button-small select-visible-button" type="button" data-action="select-visible" ${data.items.length ? "" : "disabled"}>
              <i data-lucide="${allSelected ? "square-x" : "list-checks"}"></i>${allSelected ? "取消全选" : `全选本页（${data.items.length}）`}
            </button>
            <span class="node-selection-copy" aria-live="polite"><strong>${selectedVisible}</strong> 个节点已选</span>
          </div>
          <div class="node-management-actions">
            <button class="button button-enable button-small" type="button" data-action="enable-selected" ${canEnableSelected ? "" : "disabled"}><i data-lucide="circle-play"></i>启用所选</button>
            <button class="button button-disable button-small" type="button" data-action="disable-selected" ${canDisableSelected ? "" : "disabled"}><i data-lucide="circle-pause"></i>停用所选</button>
            <button class="button button-quiet button-small" type="button" data-action="clear-selection" ${selectedVisible ? "" : "disabled"}><i data-lucide="x"></i>取消选择</button>
          </div>
        </div>` : `
        <div class="bulk-bar ${selectedVisible ? "is-active" : ""}">
          <span><strong>${selectedVisible}</strong> 个节点已选</span>
          <button class="button button-primary button-small" type="button" data-action="check-selected" ${selectedVisible ? "" : "disabled"}><i data-lucide="scan-line"></i>复测所选</button>
          <button class="button button-quiet button-small" type="button" data-action="clear-selection"><i data-lucide="x"></i>取消选择</button>
        </div>`}
        <div class="node-table-shell" aria-busy="false">
          <div class="node-table-head">
            ${columnHeaderMarkup("select", "选择", `<label class="check-control"><input type="checkbox" data-action="select-page" ${allSelected ? "checked" : ""}><span></span><span class="sr-only">选择本页节点</span></label>`, "is-select")}
            ${columnHeaderMarkup("node", "节点")}
            ${columnHeaderMarkup("status", "节点连接状态")}
            ${columnHeaderMarkup("region", "出口国家 / 地区")}
            ${columnHeaderMarkup("latency", "两种延迟")}
            ${columnHeaderMarkup("health", "健康评分")}
            ${columnHeaderMarkup("availability", "24 小时在线率")}
            ${columnHeaderMarkup("services", "网站访问结果")}
            ${columnHeaderMarkup("checked", "最近检测")}
            ${columnHeaderMarkup("actions", "快捷操作", "", "align-right")}
          </div>
          <div class="node-list">${rows}</div>
        </div>
        <footer class="pagination">
          <span>共 <strong>${data.total}</strong> 个节点 · 第 ${data.page} / ${data.pages} 页</span>
          <div class="pagination-size"><span>每页</span><select data-filter="page_size" data-select-kind="page_size" data-select-compact="true" aria-label="每页节点数量">${[20, 30, 50, 100].map((value) => `<option value="${value}" ${Number(filters.page_size) === value ? "selected" : ""}>${value} 个节点</option>`).join("")}</select></div>
          <div><button class="icon-button" type="button" data-page="${data.page - 1}" ${data.page <= 1 ? "disabled" : ""} aria-label="上一页"><i data-lucide="chevron-left"></i></button><button class="icon-button" type="button" data-page="${data.page + 1}" ${data.page >= data.pages ? "disabled" : ""} aria-label="下一页"><i data-lucide="chevron-right"></i></button></div>
        </footer>
      </section>
    `;
  }

  function sortOptionMeta(value) {
    const normalized = value === "latency" ? "node_latency" : value;
    return NODE_SORT_OPTIONS.find((item) => item.value === normalized) || NODE_SORT_OPTIONS[0];
  }

  function sortDirectionMeta(sort, direction) {
    const descending = direction === "desc";
    const normalized = sort === "latency" ? "node_latency" : sort;
    const labels = {
      status: descending ? "正常优先" : "异常优先",
      health: descending ? "高分优先" : "低分优先",
      website_latency: descending ? "慢到快" : "快到慢",
      node_latency: descending ? "慢到快" : "快到慢",
      checked: descending ? "最近优先" : "较早优先",
      country: descending ? "倒序" : "正序",
      name: descending ? "倒序" : "正序"
    };
    return {
      label: labels[normalized] || (descending ? "降序" : "升序"),
      icon: descending ? "arrow-down-wide-narrow" : "arrow-up-narrow-wide"
    };
  }

  function sortPickerMarkup(filters, mode) {
    const active = sortOptionMeta(filters.sort);
    const direction = sortDirectionMeta(filters.sort, filters.direction);
    const groups = [...new Set(NODE_SORT_OPTIONS.map((item) => item.group))];
    const options = groups.map((group) => `
      <div class="sort-menu-group">
        <span class="sort-menu-heading">${escapeHtml(group)}</span>
        ${NODE_SORT_OPTIONS.filter((item) => item.group === group).map((item) => {
          const selected = item.value === active.value;
          return `<button class="sort-option ${selected ? "is-selected" : ""}" type="button"
            role="option" aria-selected="${selected}" data-action="set-sort" data-sort-value="${item.value}">
            <span class="sort-option-icon"><i data-lucide="${item.icon}"></i></span>
            <span class="sort-option-copy"><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.detail)}</small></span>
            <i class="sort-option-check" data-lucide="check"></i>
          </button>`;
        }).join("")}
      </div>`).join("");
    return `
      <div class="sort-picker sort-control" data-sort-picker>
        <button class="sort-picker-trigger" type="button" data-action="toggle-sort-menu"
          aria-haspopup="listbox" aria-expanded="false" aria-controls="sort-menu-${mode}">
          <span class="sort-trigger-icon"><i data-lucide="${active.icon}"></i></span>
          <span class="sort-trigger-copy"><small>排序依据</small><strong>${escapeHtml(active.label)}</strong></span>
          <span class="sort-trigger-direction"><i data-lucide="${direction.icon}"></i>${escapeHtml(direction.label)}</span>
          <i class="sort-trigger-chevron" data-lucide="chevron-down"></i>
        </button>
        <div class="sort-menu" id="sort-menu-${mode}" role="listbox" aria-label="节点排序方式" hidden>
          <header class="sort-menu-intro"><span><strong>节点排序</strong><small>选择依据和排列方向</small></span><i data-lucide="list-filter"></i></header>
          <div class="sort-menu-options">${options}</div>
          <div class="sort-direction-panel" aria-label="排列方向">
            <span>排列方向</span>
            <div>
              ${["asc", "desc"].map((value) => {
                const meta = sortDirectionMeta(active.value, value);
                const selected = filters.direction === value;
                return `<button class="${selected ? "is-selected" : ""}" type="button"
                  data-action="set-sort-direction" data-sort-direction="${value}" aria-pressed="${selected}">
                  <i data-lucide="${meta.icon}"></i>${escapeHtml(meta.label)}
                </button>`;
              }).join("")}
            </div>
          </div>
        </div>
      </div>`;
  }

  function setSortPickerOpen(picker, open, focusOption = false) {
    if (!picker) return;
    $$(".sort-picker.is-open").forEach((item) => {
      if (item === picker) return;
      item.classList.remove("is-open");
      $(".sort-picker-trigger", item)?.setAttribute("aria-expanded", "false");
      const otherMenu = $(".sort-menu", item);
      if (otherMenu) otherMenu.hidden = true;
    });
    picker.classList.toggle("is-open", open);
    const trigger = $(".sort-picker-trigger", picker);
    const menu = $(".sort-menu", picker);
    trigger?.setAttribute("aria-expanded", String(open));
    if (menu) menu.hidden = !open;
    picker.classList.remove(
      "opens-upward",
      "sort-space-compact",
      "sort-space-small",
      "sort-space-medium",
      "sort-space-large",
      "sort-space-full"
    );
    if (open && trigger) {
      const triggerBox = trigger.getBoundingClientRect();
      const spaceBelow = Math.max(0, window.innerHeight - triggerBox.bottom - 10);
      const spaceAbove = Math.max(0, triggerBox.top - 10);
      const opensUpward = spaceBelow < 460 && spaceAbove > spaceBelow;
      const availableSpace = opensUpward ? spaceAbove : spaceBelow;
      picker.classList.toggle("opens-upward", opensUpward);
      picker.classList.add(
        availableSpace >= 650
          ? "sort-space-full"
          : availableSpace >= 550
            ? "sort-space-large"
            : availableSpace >= 450
              ? "sort-space-medium"
              : availableSpace >= 350
                ? "sort-space-small"
                : "sort-space-compact"
      );
    }
    if (open && focusOption) {
      requestAnimationFrame(() => $(".sort-option.is-selected", picker)?.focus({ preventScroll: true }));
    }
  }

  function closeSortPickers() {
    $$(".sort-picker.is-open").forEach((picker) => setSortPickerOpen(picker, false));
  }

  function expansionFor(nodeId) {
    if (!state.expanded.has(nodeId)) state.expanded.set(nodeId, { latency: false, health: false });
    return state.expanded.get(nodeId);
  }

  function nodeRow(node, mode = "dashboard") {
    const expanded = expansionFor(node.id);
    const visualStatus = node.enabled ? node.current_status : "paused";
    const meta = nodeStatusPresentation(node);
    const services = (node.active_tests || []).map((key) => serviceStatusMarkup(key, node.services?.[key])).join("");
    const explanation = nodeStatusExplanation(node);
    const statusNote = !node.enabled
      ? "不参加自动检测"
      : node.current_status === "online"
        ? `已连续可用 ${durationSince(node.online_since)}`
        : node.current_status === "degraded"
          ? explanation
          : node.consecutive_failures
            ? `${node.consecutive_failures} 次连续失败`
            : explanation;
    return `
      <article class="node-row level-${meta.level}" data-node-id="${node.id}">
        <div class="node-main">
          <label class="check-control"><input type="checkbox" data-select-node="${node.id}" ${state.selected.has(node.id) ? "checked" : ""}><span></span><span class="sr-only">选择 ${escapeHtml(node.name)}</span></label>
          <button class="node-identity" type="button" data-action="open-node" data-node="${node.id}" aria-label="查看 ${escapeHtml(node.name)} 的详细检测结果">
            <span class="protocol-mark">${escapeHtml(String(node.protocol || "?").slice(0, 3).toUpperCase())}</span>
            <span><strong>${escapeHtml(node.name)}</strong><small><span class="identity-region"><img src="/static/flags/${escapeHtml((node.country_code || "ZZ").toLowerCase())}.svg" onerror="this.onerror=null;this.src='/static/flags/zz.svg'" alt="">${escapeHtml(node.region_name || "未知地区")} · </span>${escapeHtml(node.protocol)} · ${escapeHtml(node.subscription_name)}</small></span>
          </button>
          <div class="node-status-cell">${statusBadge(visualStatus, explanation, meta)}<small class="uptime-note">${escapeHtml(statusNote)}</small></div>
          ${flagMarkup(node.country_code, node.region_name, node)}
          ${dualLatencyMarkup(node)}
          ${metricMeter(node.health_score, "健康评分", "health", true)}
          ${metricMeter(node.availability_24h, "24 小时在线率", "availability", true)}
          <span class="service-strip">${services || '<span class="muted">暂无检测项</span>'}</span>
          <span class="last-check"><strong>${relativeTime(node.last_checked_at)}</strong><small>${formatTime(node.last_checked_at)}</small></span>
          <span class="row-actions">
            <button class="icon-button ${expanded.latency ? "is-active" : ""}" type="button" data-action="toggle-trend" data-kind="latency" data-node="${node.id}" aria-expanded="${expanded.latency}" aria-label="展开延迟趋势" data-tooltip="延迟趋势" title="延迟趋势"><i data-lucide="activity"></i></button>
            <button class="icon-button ${expanded.health ? "is-active" : ""}" type="button" data-action="toggle-trend" data-kind="health" data-node="${node.id}" aria-expanded="${expanded.health}" aria-label="展开健康评分趋势" data-tooltip="评分趋势" title="评分趋势"><i data-lucide="heart-pulse"></i></button>
            <button class="icon-button" type="button" data-action="check-node" data-node="${node.id}" aria-label="立即重新检测" data-tooltip="立即复测" title="立即复测" ${node.enabled ? "" : "disabled"}><i data-lucide="scan-line"></i></button>
            ${mode === "nodes" ? `<button class="button button-small node-state-button ${node.enabled ? "is-disable" : "is-enable"}" type="button" data-action="set-node-enabled" data-node="${node.id}" data-enabled="${node.enabled ? "false" : "true"}" aria-label="${node.enabled ? "停用" : "启用"}节点 ${escapeHtml(node.name)}"><i data-lucide="${node.enabled ? "pause" : "play"}"></i><span>${node.enabled ? "停用" : "启用"}</span></button>` : ""}
            <button class="icon-button" type="button" data-action="open-node" data-node="${node.id}" aria-label="打开节点详情" data-tooltip="查看详情" title="查看详情"><i data-lucide="ellipsis"></i></button>
          </span>
        </div>
        ${(expanded.latency || expanded.health) ? `<div class="trend-deck">${expanded.latency ? trendPanel(node, "latency") : ""}${expanded.health ? trendPanel(node, "health") : ""}</div>` : ""}
      </article>
    `;
  }

  function trendPanel(node, kind) {
    const days = state.trendRanges.get(node.id) || 7;
    const cache = state.trendCache.get(`${node.id}:${days}`);
    const label = kind === "latency" ? "两种延迟波动" : "健康状态波动";
    const icon = kind === "latency" ? "activity" : "heart-pulse";
    return `
      <section class="node-trend-panel trend-${kind}" data-trend-panel="${node.id}:${kind}">
        <header><span><i data-lucide="${icon}"></i><strong>${label}</strong><small>${kind === "latency" ? "蓝色实线：本地真实代理链路；紫色虚线：节点访问网站" : "绿色区间表示节点连接健康"}</small></span><span class="trend-panel-actions"><select data-trend-range="${node.id}" data-select-kind="trend_range" data-select-compact="true" aria-label="${escapeHtml(node.name)}的${label}时间范围">${[[1, "24 小时"], [7, "7 天"], [20, "20 天"], [30, "30 天"]].map(([value, text]) => `<option value="${value}" ${days === value ? "selected" : ""}>${text}</option>`).join("")}</select><button class="icon-button" type="button" data-action="toggle-trend" data-kind="${kind}" data-node="${node.id}" aria-label="折叠${label}"><i data-lucide="x"></i></button></span></header>
        <div class="trend-content">${cache ? trendCanvasMarkup(node.id, kind, cache.points) : `<div class="trend-loading"><i data-lucide="loader-circle"></i><span>读取趋势数据</span></div>`}</div>
      </section>
    `;
  }

  function trendCanvasMarkup(nodeId, kind, points) {
    if (!points?.length) return `<div class="trend-empty"><i data-lucide="chart-no-axes-column-increasing"></i><span>所选范围暂无趋势数据</span></div>`;
    return `<canvas class="mini-trend-canvas" data-chart-node="${nodeId}" data-chart-kind="${kind}" aria-label="${kind === "latency" ? "本地节点测速与网站完整访问耗时趋势图" : "节点健康趋势图"}"></canvas>`;
  }

  function readColumnLayouts() {
    if (state.columnLayouts) return state.columnLayouts;
    const layouts = { wide: {}, compact: {} };
    try {
      const parsed = JSON.parse(localStorage.getItem(COLUMN_WIDTH_STORAGE_KEY) || "{}");
      ["wide", "compact"].forEach((mode) => {
        if (!parsed?.[mode] || typeof parsed[mode] !== "object") return;
        Object.entries(NODE_COLUMN_LIMITS).forEach(([key, limits]) => {
          const width = Number(parsed[mode][key]);
          if (Number.isFinite(width)) layouts[mode][key] = Math.round(clamp(width, limits.min, limits.max));
        });
      });
    } catch (_) {
      /* 浏览器禁用存储或旧数据损坏时使用响应式默认列宽。 */
    }
    state.columnLayouts = layouts;
    return layouts;
  }

  function persistColumnLayouts() {
    const layouts = readColumnLayouts();
    const hasSavedWidth = ["wide", "compact"].some((mode) => Object.keys(layouts[mode] || {}).length);
    try {
      if (hasSavedWidth) localStorage.setItem(COLUMN_WIDTH_STORAGE_KEY, JSON.stringify(layouts));
      else localStorage.removeItem(COLUMN_WIDTH_STORAGE_KEY);
    } catch (_) {
      /* 列宽仍在当前页面有效；浏览器禁用存储时不阻断表格操作。 */
    }
  }

  function columnLayoutMode() {
    if (window.innerWidth <= 1400) return null;
    return window.innerWidth <= 1450 ? "compact" : "wide";
  }

  function visibleColumnCells(head) {
    return $$(".column-head", head).filter((cell) => getComputedStyle(cell).display !== "none");
  }

  function measureColumnWidths(cells) {
    return cells.map((cell) => {
      const limits = NODE_COLUMN_LIMITS[cell.dataset.columnKey];
      const measured = cell.getBoundingClientRect().width;
      return Math.round(clamp(measured, limits?.min || 24, limits?.max || 600));
    });
  }

  function clearColumnLayoutStyles(workbench) {
    workbench.classList.remove("has-custom-columns");
    workbench.style.removeProperty("--node-grid-columns");
    workbench.style.removeProperty("--node-grid-min-width");
  }

  function applyColumnWidths(workbench, cells, widths) {
    const head = $(".node-table-head", workbench);
    if (!head || !cells.length || cells.length !== widths.length) return;
    const safeWidths = widths.map((width, index) => {
      const limits = NODE_COLUMN_LIMITS[cells[index].dataset.columnKey];
      return Math.round(clamp(width, limits.min, limits.max));
    });
    const styles = getComputedStyle(head);
    const gap = Number.parseFloat(styles.columnGap) || 0;
    const horizontalPadding = (Number.parseFloat(styles.paddingLeft) || 0) + (Number.parseFloat(styles.paddingRight) || 0);
    const minimumWidth = Math.ceil(
      safeWidths.reduce((total, width) => total + width, 0)
      + gap * Math.max(0, safeWidths.length - 1)
      + horizontalPadding
    );
    workbench.style.setProperty("--node-grid-columns", safeWidths.map((width) => `${width}px`).join(" "));
    workbench.style.setProperty("--node-grid-min-width", `${minimumWidth}px`);
    workbench.classList.add("has-custom-columns");
    cells.forEach((cell, index) => {
      const handle = $("[data-column-resizer]", cell);
      const limits = NODE_COLUMN_LIMITS[cell.dataset.columnKey];
      if (!handle) return;
      handle.setAttribute("aria-valuemin", String(limits.min));
      handle.setAttribute("aria-valuemax", String(limits.max));
      handle.setAttribute("aria-valuenow", String(safeWidths[index]));
      handle.setAttribute("aria-valuetext", `${safeWidths[index]} 像素`);
    });
  }

  function rememberColumnLayout(mode, cells, widths, persist = false) {
    const layouts = readColumnLayouts();
    layouts[mode] = Object.fromEntries(cells.map((cell, index) => [
      cell.dataset.columnKey,
      Math.round(widths[index])
    ]));
    if (persist) persistColumnLayouts();
  }

  function applySavedColumnLayout(workbench) {
    const mode = columnLayoutMode();
    const head = $(".node-table-head", workbench);
    if (!mode || !head) {
      clearColumnLayoutStyles(workbench);
      return;
    }
    const cells = visibleColumnCells(head);
    const saved = readColumnLayouts()[mode] || {};
    const widths = cells.map((cell) => Number(saved[cell.dataset.columnKey]));
    if (!cells.length || widths.some((width) => !Number.isFinite(width))) {
      clearColumnLayoutStyles(workbench);
      const defaults = measureColumnWidths(cells);
      cells.forEach((cell, index) => {
        const handle = $("[data-column-resizer]", cell);
        const limits = NODE_COLUMN_LIMITS[cell.dataset.columnKey];
        if (!handle || !limits) return;
        handle.setAttribute("aria-valuemin", String(limits.min));
        handle.setAttribute("aria-valuemax", String(limits.max));
        handle.setAttribute("aria-valuenow", String(defaults[index]));
        handle.setAttribute("aria-valuetext", `${defaults[index]} 像素`);
      });
      return;
    }
    applyColumnWidths(workbench, cells, widths);
  }

  function resetColumnLayouts() {
    state.columnLayouts = { wide: {}, compact: {} };
    persistColumnLayouts();
    $$(".node-workbench").forEach(clearColumnLayoutStyles);
    toast("已恢复默认列宽", "桌面节点表已重新按窗口宽度自适应。");
  }

  function bindColumnResizing(workbench) {
    applySavedColumnLayout(workbench);
    $$("[data-column-resizer]", workbench).forEach((handle) => {
      handle.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || !columnLayoutMode()) return;
        const head = $(".node-table-head", workbench);
        const cells = visibleColumnCells(head);
        const cell = handle.closest(".column-head");
        const index = cells.indexOf(cell);
        if (index < 0) return;
        const mode = columnLayoutMode();
        const initialWidths = measureColumnWidths(cells);
        const startX = event.clientX;
        const pointerId = event.pointerId;
        let moved = false;
        let finished = false;
        let nextWidths = initialWidths;
        event.preventDefault();
        event.stopPropagation();
        handle.focus({ preventScroll: true });
        try { handle.setPointerCapture(pointerId); } catch (_) { /* 窗口级监听仍可继续拖动。 */ }
        document.body.classList.add("is-column-resizing");

        const move = (moveEvent) => {
          if (moveEvent.pointerId !== pointerId) return;
          moveEvent.preventDefault();
          const delta = moveEvent.clientX - startX;
          if (Math.abs(delta) < 1) return;
          const limits = NODE_COLUMN_LIMITS[cell.dataset.columnKey];
          nextWidths = [...initialWidths];
          nextWidths[index] = Math.round(clamp(initialWidths[index] + delta, limits.min, limits.max));
          applyColumnWidths(workbench, cells, nextWidths);
          rememberColumnLayout(mode, cells, nextWidths);
          moved = true;
        };
        const finish = () => {
          if (finished) return;
          finished = true;
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", finish);
          window.removeEventListener("pointercancel", finish);
          window.removeEventListener("blur", finish);
          document.body.classList.remove("is-column-resizing");
          if (moved) {
            rememberColumnLayout(mode, cells, nextWidths, true);
            redrawVisibleCharts();
          }
        };
        window.addEventListener("pointermove", move, { passive: false });
        window.addEventListener("pointerup", finish);
        window.addEventListener("pointercancel", finish);
        window.addEventListener("blur", finish);
      });

      handle.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight"].includes(event.key) || !columnLayoutMode()) return;
        const head = $(".node-table-head", workbench);
        const cells = visibleColumnCells(head);
        const cell = handle.closest(".column-head");
        const index = cells.indexOf(cell);
        if (index < 0) return;
        event.preventDefault();
        event.stopPropagation();
        const mode = columnLayoutMode();
        const widths = measureColumnWidths(cells);
        const limits = NODE_COLUMN_LIMITS[cell.dataset.columnKey];
        const step = event.shiftKey ? 24 : 8;
        widths[index] = Math.round(clamp(
          widths[index] + (event.key === "ArrowRight" ? step : -step),
          limits.min,
          limits.max
        ));
        applyColumnWidths(workbench, cells, widths);
        rememberColumnLayout(mode, cells, widths, true);
        redrawVisibleCharts();
      });
    });
  }

  function bindNodeWorkbench(root) {
    const workbench = $(".node-workbench", root);
    if (!workbench) return;
    bindColumnResizing(workbench);
    const externalCheckAll = $('[data-action="check-all"]', root);
    if (externalCheckAll && !workbench.contains(externalCheckAll)) {
      externalCheckAll.addEventListener("click", () => runCheckAll(externalCheckAll));
    }
    const search = $('[data-filter="search"]', workbench);
    const searchHandler = debounce(() => {
      state.filters.search = search.value.trim();
      state.filters.page = 1;
      reloadNodeView();
    }, 280);
    search.addEventListener("input", searchHandler);
    $$("select[data-filter]", workbench).forEach((select) => select.addEventListener("change", () => {
      state.filters[select.dataset.filter] = select.dataset.filter === "page_size" ? Number(select.value) : select.value;
      state.filters.page = 1;
      reloadNodeView();
    }));
    workbench.addEventListener("keydown", (event) => {
      const picker = event.target.closest("[data-sort-picker]");
      if (!picker) return;
      const trigger = event.target.closest(".sort-picker-trigger");
      if (trigger && ["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        setSortPickerOpen(picker, true, true);
        return;
      }
      const option = event.target.closest(".sort-option");
      if (!option || !picker.classList.contains("is-open")) return;
      const options = $$(".sort-option", picker);
      const index = options.indexOf(option);
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const nextIndex = event.key === "Home"
          ? 0
          : event.key === "End"
            ? options.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
        options[nextIndex]?.focus({ preventScroll: true });
      }
    });
    workbench.addEventListener("change", (event) => {
      const selected = event.target.closest("[data-select-node]");
      if (selected) {
        const id = Number(selected.dataset.selectNode);
        if (selected.checked) state.selected.add(id); else state.selected.delete(id);
        rerenderCurrentNodeView();
      }
      const selectPage = event.target.closest('[data-action="select-page"]');
      if (selectPage) {
        state.nodePage.items.forEach((node) => selectPage.checked ? state.selected.add(node.id) : state.selected.delete(node.id));
        rerenderCurrentNodeView();
      }
      const range = event.target.closest("[data-trend-range]");
      if (range) {
        const nodeId = Number(range.dataset.trendRange);
        state.trendRanges.set(nodeId, Number(range.value));
        rerenderCurrentNodeView();
        ensureTrend(nodeId);
      }
    });
    workbench.addEventListener("click", async (event) => {
      const pageButton = event.target.closest("button[data-page]");
      if (pageButton && !pageButton.disabled) {
        state.filters.page = Number(pageButton.dataset.page);
        await reloadNodeView();
        return;
      }
      const action = event.target.closest("[data-action]");
      if (!action) return;
      const name = action.dataset.action;
      if (name === "toggle-sort-menu") {
        const picker = action.closest("[data-sort-picker]");
        setSortPickerOpen(picker, !picker.classList.contains("is-open"));
      } else if (name === "set-sort") {
        const nextSort = action.dataset.sortValue;
        if (state.filters.sort !== nextSort) {
          state.filters.sort = nextSort;
          state.filters.direction = SORT_DEFAULT_DIRECTIONS[nextSort] || "asc";
        }
        state.filters.page = 1;
        reloadNodeView();
      } else if (name === "set-sort-direction") {
        state.filters.direction = action.dataset.sortDirection === "desc" ? "desc" : "asc";
        state.filters.page = 1;
        reloadNodeView();
      } else if (name === "reset-filters") {
        resetFilters();
      } else if (name === "clear-selection") {
        state.selected.clear();
        rerenderCurrentNodeView();
      } else if (name === "select-visible") {
        const visibleNodes = state.nodePage?.items || [];
        const visibleSelected = visibleNodes.every((node) => state.selected.has(node.id));
        visibleNodes.forEach((node) => visibleSelected ? state.selected.delete(node.id) : state.selected.add(node.id));
        rerenderCurrentNodeView();
      } else if (name === "enable-selected") {
        await runBatchSetEnabled(true, action);
      } else if (name === "disable-selected") {
        await runBatchSetEnabled(false, action);
      } else if (name === "check-selected") {
        await runBatchCheck(action);
      } else if (name === "check-all") {
        await runCheckAll(action);
      } else if (name === "check-node") {
        await runNodeCheck(Number(action.dataset.node), action);
      } else if (name === "set-node-enabled") {
        await setNodeEnabled(
          Number(action.dataset.node),
          action.dataset.enabled === "true",
          action
        );
      } else if (name === "open-node") {
        await openNodeDetail(Number(action.dataset.node));
      } else if (name === "toggle-trend") {
        toggleTrend(Number(action.dataset.node), action.dataset.kind);
      } else if (name === "expand-all") {
        await setAllTrends(true);
      } else if (name === "collapse-all") {
        setAllTrends(false);
      } else if (name === "explain-metrics") {
        openMetricGuide();
      } else if (name === "reset-columns") {
        resetColumnLayouts();
      }
    });
  }

  function focusSearchShortcut(event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k" && state.me) {
      event.preventDefault();
      const selector = state.view === "latency"
        ? '[data-latency-filter="search"]'
        : '[data-filter="search"]';
      $(selector)?.focus();
      return true;
    }
    return false;
  }

  function resetFilters() {
    state.filters = { page: 1, page_size: 30, search: "", status: "", country: "", service: "", sort: "status", direction: "asc" };
    reloadNodeView();
  }

  function reloadNodeView() {
    return state.view === "dashboard" ? loadDashboard(true) : loadNodes(true);
  }

  function rerenderCurrentNodeView() {
    if (state.view === "dashboard") renderDashboard();
    else if (state.view === "nodes") renderNodes();
  }

  function toggleTrend(nodeId, kind) {
    const value = expansionFor(nodeId);
    value[kind] = !value[kind];
    rerenderCurrentNodeView();
    if (value[kind]) ensureTrend(nodeId);
  }

  async function setAllTrends(expand) {
    const nodes = state.nodePage?.items || [];
    nodes.forEach((node) => state.expanded.set(node.id, { latency: expand, health: expand }));
    rerenderCurrentNodeView();
    if (!expand) return;
    for (let index = 0; index < nodes.length; index += 3) {
      await Promise.all(nodes.slice(index, index + 3).map((node) => ensureTrend(node.id, false)));
    }
  }

  async function ensureTrend(nodeId, redraw = true) {
    const days = state.trendRanges.get(nodeId) || 7;
    const key = `${nodeId}:${days}`;
    const cached = state.trendCache.get(key);
    if (cached && Date.now() - cached.loadedAt < 120000) {
      if (redraw) updateTrendPanels(nodeId);
      return cached;
    }
    if (state.trendRequests.has(key)) return state.trendRequests.get(key);
    const request = api(`/api/nodes/${nodeId}/trend?days=${days}`)
      .then((payload) => {
        const value = { points: payload.points || [], loadedAt: Date.now() };
        state.trendCache.set(key, value);
        updateTrendPanels(nodeId);
        return value;
      })
      .catch((error) => {
        updateTrendPanels(nodeId, error);
        return null;
      })
      .finally(() => state.trendRequests.delete(key));
    state.trendRequests.set(key, request);
    return request;
  }

  function updateTrendPanels(nodeId, error = null) {
    const days = state.trendRanges.get(nodeId) || 7;
    const cached = state.trendCache.get(`${nodeId}:${days}`);
    ["latency", "health"].forEach((kind) => {
      const panel = $(`[data-trend-panel="${nodeId}:${kind}"]`);
      if (!panel) return;
      const content = $(".trend-content", panel);
      content.innerHTML = error
        ? `<div class="trend-empty is-error"><i data-lucide="cloud-off"></i><span>${escapeHtml(error.message)}</span></div>`
        : cached
          ? trendCanvasMarkup(nodeId, kind, cached.points)
          : `<div class="trend-loading"><i data-lucide="loader-circle"></i><span>读取趋势数据</span></div>`;
      refreshIcons(panel);
      if (cached) drawPanelChart(panel, cached.points, kind);
    });
  }

  function drawExpandedCharts(root = document) {
    $$("[data-trend-panel]", root).forEach((panel) => {
      const [nodeId, kind] = panel.dataset.trendPanel.split(":");
      const days = state.trendRanges.get(Number(nodeId)) || 7;
      const cached = state.trendCache.get(`${nodeId}:${days}`);
      if (cached) drawPanelChart(panel, cached.points, kind);
      else ensureTrend(Number(nodeId));
    });
  }

  function redrawVisibleCharts() {
    drawExpandedCharts();
    const resource = $("#resource-chart");
    if (resource && state.system?.series) drawResourceChart(resource, state.system.series);
  }

  function setupCanvas(canvas) {
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    const context = canvas.getContext("2d");
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { context, width: rect.width, height: rect.height };
  }

  function cssColor(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function drawPanelChart(panel, points, kind) {
    const canvas = $(".mini-trend-canvas", panel);
    const setup = setupCanvas(canvas);
    if (!setup || !points.length) return;
    const { context: ctx, width, height } = setup;
    const pad = { left: 12, right: 12, top: 10, bottom: 20 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;
    const values = kind === "latency"
      ? points.flatMap((point) => [point.latency_ms, point.website_latency_ms])
      : points.map((point) => point.health);
    const finite = values.filter((value) => value !== null && Number.isFinite(Number(value))).map(Number);
    const max = kind === "latency" ? Math.max(100, ...finite) * 1.08 : 100;
    const min = kind === "latency" ? Math.max(0, Math.min(...finite, 0) * 0.9) : 0;
    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = cssColor("--line-subtle");
    ctx.lineWidth = 1;
    [0, 0.5, 1].forEach((ratio) => {
      const y = pad.top + innerH * ratio;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(width - pad.right, y);
      ctx.stroke();
    });
    const xAt = (index) => pad.left + innerW * index / Math.max(1, points.length - 1);
    const yAt = (value) => pad.top + innerH - ((Number(value) - min) / Math.max(1, max - min)) * innerH;
    const series = kind === "latency"
      ? [
          { key: "website_latency_ms", color: cssColor("--chart-violet"), dash: [5, 4], width: 1.7, fill: null },
          { key: "latency_ms", color: cssColor("--chart-blue"), dash: [], width: 2.2, fill: cssColor("--chart-blue-fill") }
        ]
      : [{ key: "health", color: cssColor("--chart-green"), dash: [], width: 2, fill: cssColor("--chart-green-fill") }];
    series.forEach((item) => {
      const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + innerH);
      gradient.addColorStop(0, item.fill || "transparent");
      gradient.addColorStop(1, "transparent");
      ctx.beginPath();
      let first = null;
      let last = null;
      points.forEach((point, index) => {
        const value = point[item.key];
        if (value === null || value === undefined || !Number.isFinite(Number(value))) return;
        const x = xAt(index);
        const y = yAt(value);
        if (!first) { ctx.moveTo(x, y); first = { x, y }; } else ctx.lineTo(x, y);
        last = { x, y };
      });
      if (!first || !last) return;
      ctx.strokeStyle = item.color;
      ctx.lineWidth = item.width;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.setLineDash(item.dash);
      ctx.stroke();
      ctx.setLineDash([]);
      if (item.fill) {
        ctx.lineTo(last.x, pad.top + innerH);
        ctx.lineTo(first.x, pad.top + innerH);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();
      }
    });
    ctx.fillStyle = cssColor("--ink-muted");
    ctx.font = "11px 'Segoe UI', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(formatTime(points[0].time), pad.left, height - 4);
    ctx.textAlign = "right";
    ctx.fillText(formatTime(points.at(-1).time), width - pad.right, height - 4);
    bindChartTooltip(canvas, points, kind, pad, innerW);
  }

  function bindChartTooltip(canvas, points, kind, pad, innerW) {
    canvas._trendPoints = points;
    canvas._trendKind = kind;
    canvas._trendPad = pad;
    canvas._trendInnerWidth = innerW;
    if (canvas.dataset.tooltipBound === "1") return;
    canvas.dataset.tooltipBound = "1";
    const show = (clientX, clientY) => {
      const rect = canvas.getBoundingClientRect();
      const currentPoints = canvas._trendPoints || [];
      const currentPad = canvas._trendPad;
      const ratio = clamp((clientX - rect.left - currentPad.left) / Math.max(1, canvas._trendInnerWidth), 0, 1);
      const index = Math.round(ratio * Math.max(0, currentPoints.length - 1));
      const point = currentPoints[index];
      if (!point) return;
      const tooltip = $("#tooltip-root");
      const value = canvas._trendKind === "latency"
        ? `<strong>本地 → 节点 ${formatLatency(point.latency_ms)}</strong><span>节点 → 网站 ${formatLatency(point.website_latency_ms)}</span>`
        : `<strong>${formatPercent(point.health, 1)}</strong>`;
      tooltip.innerHTML = `${value}<span>${formatTime(point.time, true)}</span><small>${point.samples || 0} 个节点测速样本</small>`;
      tooltip.hidden = false;
      const left = Math.min(window.innerWidth - 170, Math.max(8, clientX + 12));
      const top = Math.max(8, clientY - 72);
      tooltip.style.transform = `translate(${left}px, ${top}px)`;
    };
    canvas.addEventListener("pointermove", (event) => show(event.clientX, event.clientY));
    canvas.addEventListener("pointerleave", () => { $("#tooltip-root").hidden = true; });
    canvas.addEventListener("pointerdown", (event) => show(event.clientX, event.clientY));
  }

  async function runNodeCheck(nodeId, button) {
    await busyButton(button, async () => {
      await api(`/api/nodes/${nodeId}/check`, { method: "POST" });
      toast("节点已进入复测队列", "结果完成后会自动刷新。");
    });
  }

  async function runBatchCheck(button) {
    const ids = Array.from(state.selected);
    if (!ids.length) return;
    await busyButton(button, async () => {
      await api("/api/tasks/check-batch", { method: "POST", body: { node_ids: ids } });
      toast("批量复测已提交", `共 ${ids.length} 个启用节点。`);
      state.selected.clear();
      rerenderCurrentNodeView();
    });
  }

  async function runBatchSetEnabled(enabled, button) {
    const ids = (state.nodePage?.items || [])
      .filter((node) => state.selected.has(node.id) && node.enabled !== enabled)
      .map((node) => node.id);
    if (!ids.length) return;
    await busyButton(button, async () => {
      const result = await api("/api/nodes/enabled-batch", {
        method: "PUT",
        body: { node_ids: ids, enabled }
      });
      state.selected.clear();
      await loadNodes(true);
      toast(
        enabled ? "所选节点已启用" : "所选节点已停用",
        enabled
          ? `已启用 ${result.updated} 个节点，并加入错峰检测队列。`
          : `已停用 ${result.updated} 个节点，不再参加自动检测。`,
        enabled ? "success" : "warning"
      );
    });
  }

  async function setNodeEnabled(nodeId, enabled, button) {
    await busyButton(button, async () => {
      await api(`/api/nodes/${nodeId}/enabled`, {
        method: "PUT",
        body: { enabled }
      });
      state.selected.delete(nodeId);
      await loadNodes(true);
      toast(
        enabled ? "节点已启用" : "节点已停用",
        enabled ? "该节点已加入错峰检测队列。" : "该节点将不再参加自动检测。",
        enabled ? "success" : "warning"
      );
    });
  }

  async function runCheckAll(button) {
    await busyButton(button, async () => {
      await api("/api/tasks/check-all", { method: "POST" });
      toast("全量复测已提交", "调度器会按并发上限逐个处理。");
    });
  }

  async function openNodeDetail(nodeId) {
    try {
      const data = await api(`/api/nodes/${nodeId}`);
      const node = data.node;
      const knownCountry = Object.prototype.hasOwnProperty.call(COUNTRY_NAMES, node.country_code);
      const countryOptions = `${knownCountry ? "" : `<option value="${escapeHtml(node.country_code)}" selected>${escapeHtml(node.region_name || node.country_code)} · ${escapeHtml(node.country_code)}</option>`}${Object.entries(COUNTRY_NAMES).map(([code, name]) => `<option value="${code}" ${node.country_code === code ? "selected" : ""}>${escapeHtml(name)} · ${code}</option>`).join("")}`;
      const explanation = nodeStatusExplanation(node);
      const detailPresentation = nodeStatusPresentation(node);
      const locationChecked = node.location_checked_at ? formatTime(node.location_checked_at, true) : "尚未自动识别";
      const locationMeta = node.location_source === "auto"
        ? `已自动核实 · ${node.location_provider_count || 0} 个来源一致${node.exit_ip_mask ? ` · 出口 IP ${node.exit_ip_mask}` : ""} · ${locationChecked}`
        : node.location_source === "manual"
          ? `管理员手动设置 · ${locationChecked}`
          : node.location_source === "name"
            ? "当前暂按节点名称推断，可点击“自动识别出口地区”核实"
            : "尚未识别出口地区，可点击“自动识别出口地区”";
      const serviceCards = (node.active_tests || []).map((key) => {
        const result = node.services?.[key];
        const meta = SERVICE_STATUS[result?.status || "uncertain"] || SERVICE_STATUS.uncertain;
        const status = result?.status || "uncertain";
        const detail = ERROR_LABELS[status] || (status === "available" ? "目标网站已正常返回有效页面" : meta[0]);
        return `<div class="service-detail level-${meta[1]}"><span>${brandLogo(key)}<strong>${escapeHtml(state.targets.find((item) => item.key === key)?.label || key)}</strong></span><span><i data-lucide="${meta[2]}"></i>${meta[0]}</span><p>${escapeHtml(detail)}</p><dl><div><dt>网站完整耗时</dt><dd>${formatLatency(result?.latency_ms)}</dd></div><div><dt>页面响应</dt><dd>${result?.http_code ?? "—"}</dd></div><div><dt>安全连接</dt><dd>${result?.tls_ok ? "成功" : "未确认"}</dd></div></dl></div>`;
      }).join("");
      const runs = data.runs.slice(0, 5).map((run) => `<div class="run-row"><span>${statusBadge(run.status, friendlyDetail(run.error_type, ""), runStatusPresentation(run))}</span><span class="run-latencies" title="${escapeHtml(nodeLatencyMethodDetail(run))}"><small>本地 → 节点 · ${nodeLatencyMethodShort(run.node_latency_method)}</small><strong>${formatLatency(run.node_latency_ms)}</strong><small>节点 → 网站</small><strong>${formatLatency(run.latency_avg_ms)}</strong></span><span>${run.health_score === null || run.health_score === undefined ? "—" : `${formatNumber(run.health_score, 0)} / 100`}</span><time>${formatTime(run.finished_at, true)}</time></div>`).join("");
      openModal(`
        <section class="modal node-detail-modal" role="dialog" aria-modal="true" aria-labelledby="node-detail-title">
          <header class="modal-head"><div><p class="eyebrow">节点详情</p><h2 id="node-detail-title">${escapeHtml(node.name)}</h2><p>${escapeHtml(node.protocol)} · ${escapeHtml(node.subscription_name)}</p></div><button class="icon-button" type="button" data-modal-close aria-label="关闭"><i data-lucide="x"></i></button></header>
          <div class="modal-body">
            <div class="detail-status-strip"><div>${statusBadge(node.enabled ? node.current_status : "paused", explanation, detailPresentation)}<small>${escapeHtml(node.current_status === "online" ? `已连续可用 ${durationSince(node.online_since)}` : explanation)}</small></div>${metricMeter(node.health_score, "健康评分", "health")}${metricMeter(node.availability_24h, "24 小时在线率", "availability")}<div class="detail-latency">${dualLatencyMarkup(node, "is-detail")}<small class="probe-source">本地测速：${escapeHtml(nodeLatencyMethodShort(node.last_node_latency_method))} · ${escapeHtml(nodeLatencyMethodDetail(node))}${node.last_node_jitter_ms === null || node.last_node_jitter_ms === undefined ? "" : ` · 抖动 ${formatLatency(node.last_node_jitter_ms)}`}</small></div></div>
            <section class="location-setting"><div><span class="location-heading"><i data-lucide="map-pinned"></i><strong>出口国家 / 地区</strong></span><p>${escapeHtml(locationMeta)}</p></div><div class="location-actions"><button class="button button-secondary" type="button" id="detail-locate"><i data-lucide="radar"></i>${node.location_source === "auto" ? "重新自动识别" : "自动识别出口地区"}</button></div><details><summary><i data-lucide="chevron-right"></i><span>手动修正地区</span></summary><form id="node-region-form" class="inline-setting"><div class="field"><label for="node-country-code">选择国家或地区</label><span class="field-control"><i data-lucide="map"></i><select id="node-country-code" name="country_code" data-select-kind="region" aria-label="选择节点出口国家或地区">${countryOptions}</select></span></div><button class="button button-quiet" type="submit"><i data-lucide="save"></i>保存手动设置</button></form></details></section>
            <section class="detail-section detail-services"><header><h3>网站访问结果</h3><p>完整页面耗时与节点轻量测速分开统计</p></header><div class="service-detail-grid">${serviceCards}</div></section>
            <section class="detail-section detail-runs"><header><h3>最近 5 次检测</h3><p>每次同时记录节点测速与网站完整访问耗时</p></header><div class="run-table">${runs || '<div class="trend-empty">暂无检测记录</div>'}</div></section>
            <div class="detail-actions"><button class="button button-primary" type="button" id="detail-check" ${node.enabled ? "" : "disabled"}><i data-lucide="scan-line"></i>立即复测</button><label class="switch-row"><span><strong>启用持续检测</strong><small>${node.enabled ? "定时任务会继续检查" : "当前不进入定时队列"}</small></span><span class="switch"><input id="detail-enabled" type="checkbox" ${node.enabled ? "checked" : ""}><i></i></span></label></div>
          </div>
        </section>
      `);
      $("#node-region-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = $('button[type="submit"]', event.currentTarget);
        await busyButton(button, async () => {
          const countryCode = new FormData(event.currentTarget).get("country_code");
          await api(`/api/nodes/${nodeId}/region`, { method: "PUT", body: { country_code: countryCode } });
          toast("节点地区已更新");
          closeModal();
          reloadNodeView();
        });
      });
      $("#detail-locate").addEventListener("click", (event) => busyButton(event.currentTarget, async () => {
        await api(`/api/nodes/${nodeId}/locate`, { method: "POST" });
        toast("出口地区识别已提交", "平台会通过该节点联网，并等待至少两个公开来源给出一致结论。");
        closeModal();
      }));
      $("#detail-check").addEventListener("click", (event) => runNodeCheck(nodeId, event.currentTarget));
      $("#detail-enabled").addEventListener("change", async (event) => {
        const input = event.currentTarget;
        input.disabled = true;
        try {
          await api(`/api/nodes/${nodeId}/enabled`, { method: "PUT", body: { enabled: input.checked } });
          toast(input.checked ? "已恢复持续检测" : "已停用持续检测");
          closeModal();
          reloadNodeView();
        } catch (error) {
          input.checked = !input.checked;
          input.disabled = false;
          toast("设置未保存", error.message, "error");
        }
      });
    } catch (error) {
      toast("节点详情读取失败", error.message, "error");
    }
  }

  async function loadSubscriptions(silent = false, signal) {
    const target = $("#subscriptions-content");
    if (!silent) target.innerHTML = loadingMarkup();
    const data = await api("/api/subscriptions", { signal });
    state.subscriptions = data.items;
    renderSubscriptions();
  }

  function renderSubscriptions() {
    const target = $("#subscriptions-content");
    const items = state.subscriptions.map((item) => `
      <article class="subscription-row ${item.enabled ? "" : "is-disabled"}">
        <span class="subscription-symbol"><i data-lucide="rss"></i></span>
        <div class="subscription-main"><strong>${escapeHtml(item.name)}</strong><span>${item.node_count} 个节点 · ${item.enabled ? "持续刷新" : "已停用"}</span></div>
        <div class="subscription-meta"><span>最近刷新</span><strong>${relativeTime(item.last_refresh_at)}</strong></div>
        <div class="subscription-meta"><span>刷新周期</span><strong>${formatRefreshInterval(item.refresh_interval_minutes)}</strong></div>
        <div>${item.last_error_message ? `<span class="inline-alert"><i data-lucide="triangle-alert"></i>${escapeHtml(item.last_error_message)}</span>` : featureBadge(item.enabled, "自动刷新已启用", "自动刷新已停用")}</div>
        <div class="row-actions subscription-actions">
          <button class="button button-quiet button-small" type="button" data-sub-action="refresh" data-id="${item.id}" aria-label="立即刷新 ${escapeHtml(item.name)}"><i data-lucide="refresh-cw"></i>刷新</button>
          <button class="button button-quiet button-small" type="button" data-sub-action="edit" data-id="${item.id}" aria-label="编辑 ${escapeHtml(item.name)}"><i data-lucide="pencil"></i>编辑</button>
          <button class="button button-quiet button-small danger-text" type="button" data-sub-action="delete" data-id="${item.id}" aria-label="删除 ${escapeHtml(item.name)}"><i data-lucide="trash-2"></i>删除</button>
        </div>
      </article>
    `).join("");
    target.innerHTML = `
      <div class="page-intro compact-intro"><div><p class="eyebrow">订阅源</p><h2>安全同步节点配置</h2><p>订阅地址始终加密存储，页面和接口不会回显。</p></div><button class="button button-primary" type="button" id="add-subscription"><i data-lucide="plus"></i>添加订阅</button></div>
      <section class="list-panel"><header class="list-panel-head"><span>名称</span><span>最近刷新</span><span>周期</span><span>状态</span><span class="align-right">操作</span></header><div>${items || `<div class="state-panel is-inline"><span class="state-icon"><i data-lucide="rss"></i></span><h3>尚未添加订阅</h3><p>添加订阅后会自动同步节点。</p></div>`}</div></section>
    `;
    $("#add-subscription").addEventListener("click", () => openSubscriptionForm());
    target.addEventListener("click", (event) => {
      const action = event.target.closest("[data-sub-action]");
      if (!action) return;
      const item = state.subscriptions.find((entry) => entry.id === Number(action.dataset.id));
      if (action.dataset.subAction === "edit") openSubscriptionForm(item);
      if (action.dataset.subAction === "refresh") refreshSubscription(item.id, action);
      if (action.dataset.subAction === "delete") confirmDeleteSubscription(item);
    });
    refreshIcons(target);
  }

  function formatRefreshInterval(minutes) {
    return minutes % 1440 === 0 ? `${minutes / 1440} 天` : minutes % 60 === 0 ? `${minutes / 60} 小时` : `${minutes} 分钟`;
  }

  function openSubscriptionForm(item = null) {
    openModal(`
      <section class="modal" role="dialog" aria-modal="true" aria-labelledby="subscription-title">
        <header class="modal-head"><div><p class="eyebrow">${item ? "编辑订阅" : "添加订阅"}</p><h2 id="subscription-title">${item ? escapeHtml(item.name) : "连接新的订阅源"}</h2><p>地址加密保存，提交后不会再次显示。</p></div><button class="icon-button" type="button" data-modal-close aria-label="关闭"><i data-lucide="x"></i></button></header>
        <form id="subscription-form" class="modal-body" autocomplete="off">
          <label class="field"><span>订阅名称</span><span class="field-control"><i data-lucide="tag"></i><input name="name" required maxlength="100" autocomplete="off" data-1p-ignore value="${escapeHtml(item?.name || "")}" placeholder="例如：主力订阅"></span></label>
          <label class="field"><span>订阅地址${item ? "（留空保持原地址）" : ""}</span><span class="field-control"><i data-lucide="link-2"></i><input name="url" type="password" ${item ? "" : "required"} maxlength="4096" autocomplete="new-password" data-1p-ignore placeholder="${item ? "输入新地址才会替换" : "https://example.com/sub/..."}"></span></label>
          <div class="field"><label for="subscription-refresh-interval">自动刷新周期</label><span class="field-control"><i data-lucide="clock-3"></i><select id="subscription-refresh-interval" name="refresh_interval_minutes" data-select-kind="refresh_interval" aria-label="自动刷新周期">${[[60, "每小时"], [180, "每 3 小时"], [360, "每 6 小时"], [720, "每 12 小时"], [1440, "每天"]].map(([value, label]) => `<option value="${value}" ${Number(item?.refresh_interval_minutes || 360) === value ? "selected" : ""}>${label}</option>`).join("")}</select></span></div>
          <label class="switch-row"><span><strong>启用自动刷新</strong><small>停用不会删除已保存数据</small></span><span class="switch"><input name="enabled" type="checkbox" ${item?.enabled === false ? "" : "checked"}><i></i></span></label>
          <p class="form-note"><i data-lucide="shield-check"></i>订阅地址和节点凭据不会写入页面、日志或导出文件。</p>
          <div class="modal-actions"><button class="button button-quiet" type="button" data-modal-close>取消</button><button class="button button-primary" type="submit"><i data-lucide="save"></i>${item ? "保存修改" : "添加并刷新"}</button></div>
        </form>
      </section>
    `);
    $("#subscription-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const data = new FormData(form);
      const body = {
        name: String(data.get("name") || "").trim(),
        enabled: data.get("enabled") === "on",
        refresh_interval_minutes: Number(data.get("refresh_interval_minutes"))
      };
      const url = String(data.get("url") || "").trim();
      if (url) body.url = url;
      const button = $('button[type="submit"]', form);
      await busyButton(button, async () => {
        await api(item ? `/api/subscriptions/${item.id}` : "/api/subscriptions", { method: item ? "PUT" : "POST", body });
        closeModal();
        toast(item ? "订阅已更新" : "订阅已添加", "节点同步任务已进入队列。");
        loadSubscriptions(true);
      });
    });
  }

  async function refreshSubscription(id, button) {
    await busyButton(button, async () => {
      await api(`/api/subscriptions/${id}/refresh`, { method: "POST" });
      toast("订阅刷新已提交", "同步完成后节点列表会自动更新。");
    });
  }

  function confirmDeleteSubscription(item) {
    openModal(`
      <section class="modal modal-small" role="alertdialog" aria-modal="true" aria-labelledby="delete-title">
        <header class="modal-head"><div><p class="eyebrow">危险操作</p><h2 id="delete-title">删除“${escapeHtml(item.name)}”</h2></div><button class="icon-button" type="button" data-modal-close aria-label="关闭"><i data-lucide="x"></i></button></header>
        <div class="modal-body"><div class="danger-copy"><i data-lucide="triangle-alert"></i><p>该订阅及其节点检测历史会被删除。其他订阅和服务器服务不受影响。</p></div><div class="modal-actions"><button class="button button-quiet" type="button" data-modal-close>取消</button><button class="button button-danger" type="button" id="confirm-delete"><i data-lucide="trash-2"></i>确认删除</button></div></div>
      </section>
    `);
    $("#confirm-delete").addEventListener("click", (event) => busyButton(event.currentTarget, async () => {
      await api(`/api/subscriptions/${item.id}`, { method: "DELETE" });
      closeModal();
      toast("订阅已删除");
      loadSubscriptions(true);
    }));
  }

  async function loadEvents(silent = false, signal) {
    const target = $("#events-content");
    if (!silent) target.innerHTML = loadingMarkup();
    const data = await api("/api/events?limit=200", { signal });
    state.events = data.items;
    renderEvents();
  }

  function renderEvents() {
    const target = $("#events-content");
    const items = state.events.map((event) => {
      const level = event.severity === "critical" ? "critical" : event.severity === "warning" ? "warning" : event.severity === "success" ? "healthy" : "unknown";
      const icon = event.event_type === "recovery" ? "circle-check" : event.event_type.includes("subscription") ? "rss" : "triangle-alert";
      return `<article class="event-row level-${level}"><span class="event-symbol"><i data-lucide="${icon}"></i></span><div><strong>${escapeHtml(event.title)}</strong><p>${escapeHtml(friendlyDetail(event.detail))}</p></div><span>${escapeHtml(event.node_name || event.subscription_name || "系统")}</span><time><strong>${relativeTime(event.created_at)}</strong><small>${formatTime(event.created_at, true)}</small></time>${event.recovered_at ? '<span class="recovery-mark"><i data-lucide="check"></i>已恢复</span>' : '<span></span>'}</article>`;
    }).join("");
    target.innerHTML = `<div class="page-intro compact-intro"><div><p class="eyebrow">事件轨迹</p><h2>故障、恢复与订阅同步记录</h2><p>近期事件按发生时间排序，敏感端点不会出现在详情中。</p></div><button class="button button-secondary" type="button" id="export-nodes"><i data-lucide="download"></i>导出节点摘要</button></div><section class="event-list">${items || `<div class="state-panel"><span class="state-icon"><i data-lucide="bell-off"></i></span><h3>近期没有事件</h3><p>系统运行平稳时这里会保持安静。</p></div>`}</section>`;
    $("#export-nodes").addEventListener("click", () => { window.location.href = "/api/export/nodes.csv"; });
    refreshIcons(target);
  }

  async function loadSystem(silent = false, signal) {
    const target = $("#system-content");
    if (!silent) target.innerHTML = loadingMarkup();
    const [system, settings, notifications, targets] = await Promise.all([
      api("/api/system", { signal }),
      api("/api/settings", { signal }),
      api("/api/notifications", { signal }),
      api("/api/targets", { signal })
    ]);
    state.system = system;
    state.settings = settings;
    state.notifications = notifications;
    state.targets = targets.items;
    renderSystem();
  }

  function storageMeter(label, value, maximum, icon) {
    const ratio = maximum ? clamp(value / maximum * 100) : 0;
    const level = ratio >= 95 ? "critical" : ratio >= 75 ? "warning" : "healthy";
    return `<div class="storage-meter"><span class="storage-icon level-${level}"><i data-lucide="${icon}"></i></span><span><small>${escapeHtml(label)}</small><strong>${formatBytes(value)}</strong><i><b style="width:${ratio}%"></b></i></span><em>${formatNumber(ratio, 1)}%</em></div>`;
  }

  function renderSystem() {
    const target = $("#system-content");
    const current = state.system.current || {};
    const storage = state.system.storage || {};
    const retention = state.system.retention || {};
    const maintenance = state.system.last_maintenance;
    const settings = state.settings;
    const observer = state.system.observer || {};
    const note = state.notifications;
    const targetCheckboxes = state.targets.map((item) => `
      <label class="target-choice ${settings.enabled_targets.includes(item.key) ? "is-active" : ""}">
        <input type="checkbox" name="enabled_targets" value="${item.key}" ${settings.enabled_targets.includes(item.key) ? "checked" : ""}>
        ${brandLogo(item.key)}
        <span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.category)}${item.default_enabled ? " · 默认项" : " · 可选项"}</small></span>
        <i data-lucide="check"></i>
      </label>`).join("");
    target.innerHTML = `
      <div class="page-intro compact-intro"><div><p class="eyebrow">运行边界</p><h2>资源、检测与存储策略</h2><p>监测网口${observer.status === "online" ? `在线${observer.interface ? `（${escapeHtml(observer.interface)}）` : ""}` : observer.status === "offline" ? "已断开，节点归责暂停" : "状态待确认"}；离线节点会持续复测直至恢复。</p></div><button class="button ${settings.scheduler_paused ? "button-primary" : "button-secondary"}" type="button" id="scheduler-toggle"><i data-lucide="${settings.scheduler_paused ? "play" : "pause"}"></i>${settings.scheduler_paused ? "恢复定时任务" : "暂停定时任务"}</button></div>
      <div class="system-layout">
        <section class="panel resource-panel"><header class="panel-head"><div><h3>实时资源</h3><p>整机综合占用与真实硬件温度</p></div><span>${relativeTime(current.sampled_at)}</span></header><div class="resource-strip"><div><small>整机 CPU</small><strong>${formatPercent(current.system_cpu_percent, 1)}</strong></div><div><small>服务器内存</small><strong>${formatPercent(current.system_memory_percent, 1)}</strong></div><div><small>CPU 温度</small><strong>${current.cpu_temperature_c === null || current.cpu_temperature_c === undefined ? "传感器不可用" : `${formatNumber(current.cpu_temperature_c, 1)} °C`}</strong></div><div><small>硬盘温度</small><strong>${current.disk_temperature_c === null || current.disk_temperature_c === undefined ? "传感器不可用" : `${formatNumber(current.disk_temperature_c, 1)} °C`}</strong></div></div>${state.system.series.length ? '<canvas id="resource-chart" class="resource-chart" aria-label="资源占用趋势"></canvas>' : ""}</section>
        <section class="panel storage-panel"><header class="panel-head"><div><h3>容量保护</h3><p>日志 10 GB、全部数据 15 GB 硬上限</p></div><span class="pressure-badge level-${storage.pressure === "critical" ? "critical" : storage.pressure === "warning" ? "warning" : "healthy"}"><i data-lucide="${storage.pressure === "normal" ? "shield-check" : "shield-alert"}"></i>${storage.pressure === "normal" ? "余量充足" : storage.pressure === "warning" ? "接近软限制" : "容量告警"}</span></header><div class="storage-grid">${storageMeter("全部持久化数据", storage.total_bytes, storage.total_hard_bytes, "database-zap")}${storageMeter("日志文件", storage.log_bytes, storage.log_hard_bytes, "scroll-text")}${storageMeter("数据库与 WAL", storage.database_bytes, storage.total_hard_bytes, "database")}${storageMeter("发布文件", storage.install_bytes, storage.total_hard_bytes, "package-check")}</div><div class="retention-strip"><span><small>原始数据</small><strong>${retention.raw_days} 天</strong></span><span><small>小时聚合</small><strong>${retention.hourly_days} 天</strong></span><span><small>最近清理</small><strong>${maintenance ? relativeTime(maintenance.finished_at) : "等待首次维护"}</strong></span><span><small>最近释放</small><strong>${formatBytes(maintenance?.freed_bytes || 0)}</strong></span><button class="button button-secondary button-small" type="button" id="run-maintenance"><i data-lucide="sparkles"></i>立即维护</button></div></section>
        <section class="panel settings-panel"><header class="panel-head"><div><h3>检测策略</h3><p>保存后用于新进入队列的任务</p></div></header><form id="settings-form" class="settings-form">
          ${numberField("check_interval_minutes", "检测周期（分钟）", settings.check_interval_minutes, 5, 1440, "clock-3")}
          ${numberField("offline_check_interval_minutes", "离线持续复测（分钟）", settings.offline_check_interval_minutes, 5, 1440, "refresh-cw")}
          ${numberField("timeout_seconds", "单目标超时（秒）", settings.timeout_seconds, 5, 60, "timer")}
          ${numberField("retry_count", "失败重试次数", settings.retry_count, 0, 3, "rotate-ccw")}
          ${numberField("max_concurrency", "最大节点并发", settings.max_concurrency, 1, 8, "workflow")}
          ${numberField("jitter_seconds", "随机抖动（秒）", settings.jitter_seconds, 0, 900, "shuffle")}
          ${numberField("raw_retention_days", "原始数据保留（天）", settings.raw_retention_days, 2, 30, "database")}
          ${numberField("hourly_retention_days", "小时聚合保留（天）", settings.hourly_retention_days, 30, 730, "archive")}
          <label class="switch-row node-probe-setting"><span><strong>启用本地节点测速</strong><small>所有节点均通过完整代理协议链路访问固定轻量目标，连续 3 次取中位数；不会使用 CDN 或中继入口的裸端口延迟。</small></span><span class="switch"><input name="node_probe_enabled" type="checkbox" ${settings.node_probe_enabled ? "checked" : ""}><i></i></span></label>
          <fieldset class="target-fieldset"><legend>实际访问检测项</legend><p>默认项保持不变；新增项只有勾选后才参与后续检测。</p><div class="target-grid">${targetCheckboxes}</div></fieldset>
          <div class="form-actions"><p><i data-lucide="info"></i>节点离线后不会熔断停测，会按离线复测周期持续执行；监测机网线断开时暂停节点归责，恢复后立即全量复测。</p><button class="button button-primary" type="submit"><i data-lucide="save"></i>保存检测策略</button></div>
        </form></section>
        <section class="panel notification-panel"><header class="panel-head"><div><h3>异常通知</h3><p>通用 Webhook，端点加密保存</p></div>${featureBadge(note.enabled, "通知已启用", "通知未启用")}</header><form id="notification-form" class="notification-form" autocomplete="off"><label class="field"><span>Webhook 地址${note.endpoint_configured ? "（留空保留）" : ""}</span><span class="field-control"><i data-lucide="webhook"></i><input name="endpoint" type="password" maxlength="4096" autocomplete="new-password" data-1p-ignore placeholder="${note.endpoint_configured ? "输入新地址才会替换" : "https://example.com/webhook"}"></span></label><label class="switch-row"><span><strong>启用通知</strong><small>只发送节点名称、事件和时间</small></span><span class="switch"><input name="enabled" type="checkbox" ${note.enabled ? "checked" : ""}><i></i></span></label><div class="notification-options"><label><input name="failure" type="checkbox" ${note.event_types.includes("failure") ? "checked" : ""}>故障通知</label><label><input name="recovery" type="checkbox" ${note.event_types.includes("recovery") ? "checked" : ""}>恢复通知</label></div>${numberField("cooldown_minutes", "同类通知冷却（分钟）", note.cooldown_minutes, 5, 1440, "hourglass")}<div class="form-actions"><span></span><button class="button button-primary" type="submit"><i data-lucide="save"></i>保存通知</button></div></form></section>
      </div>
    `;
    $("#scheduler-toggle").addEventListener("click", toggleScheduler);
    $("#run-maintenance").addEventListener("click", runMaintenance);
    $("#settings-form").addEventListener("submit", saveSettings);
    $("#settings-form").addEventListener("change", (event) => {
      const choice = event.target.closest(".target-choice");
      if (choice) choice.classList.toggle("is-active", event.target.checked);
    });
    $("#notification-form").addEventListener("submit", saveNotifications);
    refreshIcons(target);
    if ($("#resource-chart")) requestAnimationFrame(() => drawResourceChart($("#resource-chart"), state.system.series));
  }

  function numberField(name, label, value, min, max, icon) {
    return `<label class="field"><span>${label}</span><span class="field-control"><i data-lucide="${icon}"></i><input name="${name}" type="number" required min="${min}" max="${max}" value="${escapeHtml(value)}"></span></label>`;
  }

  function drawResourceChart(canvas, points) {
    const setup = setupCanvas(canvas);
    if (!setup || !points.length) return;
    const { context: ctx, width, height } = setup;
    const pad = { left: 30, right: 12, top: 12, bottom: 18 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;
    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = cssColor("--line-subtle");
    ctx.lineWidth = 1;
    [0, 0.5, 1].forEach((ratio) => {
      const y = pad.top + innerH * ratio;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    });
    [["system_cpu_percent", cssColor("--chart-blue")], ["system_memory_percent", cssColor("--chart-violet")]].forEach(([key, color]) => {
      ctx.beginPath();
      points.forEach((point, index) => {
        const x = pad.left + innerW * index / Math.max(1, points.length - 1);
        const y = pad.top + innerH - clamp(point[key]) / 100 * innerH;
        if (!index) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    });
    ctx.fillStyle = cssColor("--ink-muted");
    ctx.font = "10px 'Segoe UI', sans-serif";
    ctx.textAlign = "left"; ctx.fillText("CPU", 2, 18);
    ctx.fillStyle = cssColor("--chart-violet"); ctx.fillText("内存", 2, 32);
  }

  async function toggleScheduler(event) {
    await busyButton(event.currentTarget, async () => {
      const paused = !state.settings.scheduler_paused;
      state.settings = await api("/api/settings", { method: "PUT", body: { scheduler_paused: paused } });
      toast(paused ? "定时任务已暂停" : "定时任务已恢复", paused ? "手动复测仍可使用。" : "调度器会继续错峰执行。", paused ? "warning" : "success");
      renderSystem();
    });
  }

  async function runMaintenance(event) {
    await busyButton(event.currentTarget, async () => {
      const result = await api("/api/system/maintenance", { method: "POST" });
      toast("存储维护已完成", `释放 ${formatBytes(result.freed_bytes + (result.logs?.removed_bytes || 0))}。`);
      await loadSystem(true);
    });
  }

  async function saveSettings(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const enabledTargets = data.getAll("enabled_targets").map(String);
    if (!enabledTargets.length) {
      toast("至少保留一个检测项", "新增检测项可以关闭，但不能关闭全部目标。", "warning");
      return;
    }
    const body = {
      enabled_targets: enabledTargets,
      node_probe_enabled: data.get("node_probe_enabled") === "on"
    };
    ["check_interval_minutes", "offline_check_interval_minutes", "timeout_seconds", "retry_count", "max_concurrency", "jitter_seconds", "raw_retention_days", "hourly_retention_days"].forEach((key) => { body[key] = Number(data.get(key)); });
    await busyButton($('button[type="submit"]', form), async () => {
      state.settings = await api("/api/settings", { method: "PUT", body });
      toast("检测策略已保存", "新任务会使用最新目标和资源限制。");
      renderSystem();
    });
  }

  async function saveNotifications(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const body = {
      enabled: data.get("enabled") === "on",
      event_types: ["failure", "recovery"].filter((key) => data.get(key) === "on"),
      cooldown_minutes: Number(data.get("cooldown_minutes"))
    };
    const endpoint = String(data.get("endpoint") || "").trim();
    if (endpoint) body.endpoint = endpoint;
    await busyButton($('button[type="submit"]', form), async () => {
      state.notifications = await api("/api/notifications", { method: "PUT", body });
      toast("通知设置已保存");
      renderSystem();
    });
  }

  function openModal(content) {
    closeSmartSelects();
    closeSortPickers();
    setUserMenuOpen(false);
    state.modalReturnFocus = document.activeElement;
    const root = $("#modal-root");
    root.innerHTML = `<div class="modal-backdrop">${content}</div>`;
    document.body.classList.add("modal-open");
    refreshIcons(root);
    $$("[data-modal-close]", root).forEach((button) => button.addEventListener("click", closeModal));
    $(".modal-backdrop", root).addEventListener("mousedown", (event) => {
      if (event.target.classList.contains("modal-backdrop")) closeModal();
    });
    root.onkeydown = (event) => {
      if (event.key !== "Tab") return;
      const focusable = $$('button:not([disabled]), input:not([disabled]), select:not(.smart-select-native):not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])', root)
        .filter((element) => element.offsetParent !== null);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    requestAnimationFrame(() => {
      const preferred = $('form input:not([type="hidden"]):not([disabled]), form textarea:not([disabled]), form .smart-select-trigger:not([disabled])', root);
      (preferred || $("button:not([disabled])", root))?.focus();
    });
  }

  function closeModal() {
    const root = $("#modal-root");
    closeSmartSelects();
    $$(".smart-select", root).forEach((shell) => shell._smartSelectMenu?.remove());
    root.onkeydown = null;
    root.innerHTML = "";
    document.body.classList.remove("modal-open");
    state.modalReturnFocus?.focus?.();
    state.modalReturnFocus = null;
  }

  async function busyButton(button, operation, customError) {
    if (!button || state.busy.has(button)) return null;
    state.busy.add(button);
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<i data-lucide="loader-circle"></i><span>处理中</span>`;
    refreshIcons(button);
    try {
      return await operation();
    } catch (error) {
      if (customError) customError(error);
      else toast("操作未完成", error.message, "error");
      return null;
    } finally {
      state.busy.delete(button);
      if (button.isConnected) {
        button.disabled = false;
        button.innerHTML = original;
        refreshIcons(button);
      }
    }
  }

  function debounce(fn, delay) {
    let timer;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  bootstrap();
})();
