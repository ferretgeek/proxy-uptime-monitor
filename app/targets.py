from __future__ import annotations

from typing import Any, Iterable


DEFAULT_TARGET_KEYS: tuple[str, ...] = ("google", "chatgpt", "grok")


TARGETS: dict[str, dict[str, Any]] = {
    "google": {
        "label": "Google",
        "url": "https://www.google.com/",
        "hosts": {"www.google.com", "google.com"},
        "features": ("<title>google", 'name="q"', "/images/branding/"),
        "login_hosts": {"accounts.google.com"},
        "icon": "google",
        "category": "搜索",
    },
    "chatgpt": {
        "label": "ChatGPT",
        "url": "https://chatgpt.com/",
        "hosts": {"chatgpt.com", "www.chatgpt.com"},
        "features": ("chatgpt", "openai", "__next_data__"),
        "login_hosts": {"auth.openai.com", "auth0.openai.com"},
        "icon": "openai",
        "category": "AI",
    },
    "grok": {
        "label": "Grok",
        "url": "https://grok.com/",
        "hosts": {"grok.com", "www.grok.com"},
        "features": ("grok", "xai", "__next_data__"),
        "login_hosts": {"accounts.x.ai", "x.com", "twitter.com"},
        "icon": "grok",
        "category": "AI",
    },
    "x": {
        "label": "X",
        "url": "https://x.com/",
        "hosts": {"x.com", "www.x.com", "twitter.com", "www.twitter.com"},
        "features": ("see what’s happening", "see what's happening", "twitter"),
        "login_hosts": {"x.com", "twitter.com"},
        "icon": "x",
        "category": "社交",
    },
    "claude": {
        "label": "Claude",
        "url": "https://claude.ai/",
        "hosts": {"claude.ai", "www.claude.ai"},
        "features": ("claude", "anthropic", "continue with email"),
        "login_hosts": {"claude.ai", "console.anthropic.com"},
        "icon": "claude",
        "category": "AI",
    },
    "wikipedia": {
        "label": "Wikipedia",
        "url": "https://www.wikipedia.org/",
        "hosts": {"wikipedia.org", "www.wikipedia.org"},
        "features": ("wikipedia", "free encyclopedia", "search wikipedia"),
        "login_hosts": {"login.wikimedia.org"},
        "icon": "wikipedia",
        "category": "知识",
    },
    "github": {
        "label": "GitHub",
        "url": "https://github.com/",
        "hosts": {"github.com", "www.github.com"},
        "features": ("github", "octicon", "repository"),
        "login_hosts": {"github.com"},
        "icon": "github",
        "category": "开发",
    },
    "nodejs": {
        "label": "Node.js",
        "url": "https://nodejs.org/",
        "hosts": {"nodejs.org", "www.nodejs.org"},
        "features": ("node.js", "run javascript everywhere", "nodejs"),
        "login_hosts": set(),
        "icon": "nodejs",
        "category": "开发",
    },
    "python": {
        "label": "Python",
        "url": "https://www.python.org/",
        "hosts": {"python.org", "www.python.org"},
        "features": ("python", "python software foundation", "downloads"),
        "login_hosts": {"id.python.org"},
        "icon": "python",
        "category": "开发",
    },
    "perplexity": {
        "label": "Perplexity",
        "url": "https://www.perplexity.ai/",
        "hosts": {"perplexity.ai", "www.perplexity.ai"},
        "features": ("perplexity", "__next_data__", "ask anything"),
        "login_hosts": {"www.perplexity.ai", "perplexity.ai"},
        "icon": "perplexity",
        "category": "AI",
    },
    "youtube": {
        "label": "YouTube",
        "url": "https://www.youtube.com/",
        "hosts": {"youtube.com", "www.youtube.com", "m.youtube.com"},
        "features": ("youtube", "ytcfg", "youtubei"),
        "login_hosts": {"accounts.google.com"},
        "icon": "youtube",
        "category": "视频",
    },
    "nexusmods": {
        "label": "Nexus Mods",
        "url": "https://www.nexusmods.com/",
        "hosts": {"nexusmods.com", "www.nexusmods.com"},
        "features": ("nexus mods", "mods and community", "nexusmods"),
        "login_hosts": {"users.nexusmods.com", "www.nexusmods.com"},
        "icon": "nexusmods",
        "category": "游戏",
    },
    "huggingface": {
        "label": "Hugging Face",
        "url": "https://huggingface.co/",
        "hosts": {"huggingface.co", "www.huggingface.co"},
        "features": ("hugging face", "huggingface", "models"),
        "login_hosts": {"huggingface.co"},
        "icon": "huggingface",
        "category": "AI",
    },
    "cloudflare": {
        "label": "Cloudflare",
        "url": "https://www.cloudflare.com/",
        "hosts": {"cloudflare.com", "www.cloudflare.com"},
        "features": ("cloudflare", "connectivity cloud", "cdn-cgi"),
        "login_hosts": {"dash.cloudflare.com"},
        "icon": "cloudflare",
        "category": "网络",
    },
    "linuxdo": {
        "label": "Linux.do",
        "url": "https://linux.do/",
        "hosts": {"linux.do", "www.linux.do"},
        "features": ("linux.do", "discourse", "linux do"),
        "login_hosts": {"linux.do"},
        "icon": "linuxdo",
        "category": "社区",
    },
}


def normalize_target_keys(
    values: Iterable[str] | None,
    *,
    fallback_to_default: bool = True,
) -> tuple[str, ...]:
    if values is None:
        return DEFAULT_TARGET_KEYS if fallback_to_default else ()
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = str(value).strip().lower()
        if key in TARGETS and key not in seen:
            result.append(key)
            seen.add(key)
    if not result and fallback_to_default:
        return DEFAULT_TARGET_KEYS
    return tuple(result)


def public_target_catalog() -> list[dict[str, Any]]:
    defaults = set(DEFAULT_TARGET_KEYS)
    return [
        {
            "key": key,
            "label": value["label"],
            "icon": value["icon"],
            "category": value["category"],
            "default_enabled": key in defaults,
        }
        for key, value in TARGETS.items()
    ]
