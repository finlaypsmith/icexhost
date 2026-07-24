import os
import re
import time
import json
import urllib.parse
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
# 引入 SeleniumBase 高级过盾包
from seleniumbase import SB

SERVER_URL = os.getenv("ICEHOST_SERVER_URL")
ICEHOST_COOKIES = os.getenv("ICEHOST_COOKIES")

def export_cookies(sb):
    """导出浏览器当前最新的 Cookie 到 new_cookies.json，供工作流回写 Secret。

    只导出 dash.icehost.pl 相关域，格式与 ICEHOST_COOKIES 保持一致。
    """
    try:
        raw = sb.get_cookies()  # Selenium 格式：当前域下的全部 Cookie
        out = []
        for c in raw:
            item = {
                "name": c.get("name"),
                "value": c.get("value"),
                "domain": c.get("domain"),
                "path": c.get("path", "/"),
                # Selenium 用 expiry 表示过期时间戳，缺省表示会话级 -1
                "expires": c.get("expiry", -1),
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", True),
            }
            if c.get("sameSite"):
                item["sameSite"] = c["sameSite"]
            out.append(item)

        if not out:
            print("未获取到任何 Cookie，跳过导出。")
            return

        with open("new_cookies.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"已导出 {len(out)} 条最新 Cookie 到 new_cookies.json。")
    except Exception as e:
        print(f"导出 Cookie 失败: {e}")

def beijing_time_str():
    try:
        return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def send_tg_notification(message, photo_path=None):
    """发送结果和截图至 Telegram。消息格式对齐 .tmp/app.py 的多行纯文本风格。"""
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        print(f"[Telegram disabled] {message}")
        return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {"chat_id": chat_id, "text": message}
        requests.post(url, data=data, timeout=10)
        print(f"Telegram sent: {message[:50]}...")
    except Exception as e:
        print(f"Failed to send Telegram: {e}")

    if photo_path and os.path.exists(photo_path):
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {
                    "chat_id": chat_id,
                    "caption": message[:1024],
                }
                requests.post(url, data=data, files=files, timeout=20)
            print("TG 截图发送成功。")
        except Exception as e:
            print(f"发送 TG 截图异常: {e}")


def build_success_message(server_name, expiry, started):
    lines = [
        "🇵🇱 IceHost 续期通知",
        "",
        "✅ 续期成功",
        f"🖥️ 服务器: {server_name or '未知'}",
        f"⏱️ 新过期时间: {expiry or '未知'}",
        f"▶️ 启动状态: {'已触发 START / 运行中' if started else '未确认'}",
        f"⏱️ 运行时间: {beijing_time_str()}",
    ]
    return "\n".join(lines)


def build_not_yet_due_message(server_name, expiry):
    lines = [
        "🇵🇱 IceHost 续期通知",
        "",
        "⏳ 未到续期时间",
        f"🖥️ 服务器: {server_name or '未知'}",
        f"⏱️ 当前过期时间: {expiry or '未知'}",
        f"⏱️ 运行时间: {beijing_time_str()}",
    ]
    return "\n".join(lines)


def build_login_failed_message():
    lines = [
        "🇵🇱 IceHost 续期通知",
        "",
        "❌ 登录失效",
        "请在浏览器重新提取并更新 ICEHOST_COOKIES。",
        f"⏱️ 运行时间: {beijing_time_str()}",
    ]
    return "\n".join(lines)


def build_unconfirmed_message(server_name, expiry, note):
    lines = [
        "🇵🇱 IceHost 续期通知",
        "",
        "❌ 续期状态未确认",
        f"🖥️ 服务器: {server_name or '未知'}",
        f"⏱️ 当前过期时间: {expiry or '未知'}",
        f"📄 页面提示: {note or '未发现成功提示'}",
        f"⏱️ 运行时间: {beijing_time_str()}",
    ]
    return "\n".join(lines)


def build_error_message(error):
    lines = [
        "🇵🇱 IceHost 续期通知",
        "",
        "⚠️ 处理出错",
        f"错误: {error}",
        f"⏱️ 运行时间: {beijing_time_str()}",
    ]
    return "\n".join(lines)


def extract_server_name(text):
    if not text:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        lowered = line.lower()
        if any(token in lowered for token in [
            "expiration",
            "extend",
            "delete",
            "start",
            "stop",
            "restart",
            "account balance",
            "show my servers",
            "menu",
            "helpdesk",
            "store",
            "knowledge",
            "credits",
            "partner",
            "history",
            "api keys",
            "log out",
        ]):
            continue
        if "server" in lowered or "serwer" in lowered:
            return line
    return ""

def build_sb_options():
    """根据环境变量构造 SeleniumBase 浏览器启动参数。"""
    options = {"uc": True, "xvfb": True}
    is_proxy = os.getenv("IS_PROXY", "false").lower() == "true"

    if is_proxy:
        options["proxy"] = (
            os.getenv("S5_PROXY")
            or os.getenv("PROXY_SERVER")
            or "socks://127.0.0.1:1080"
        )

    return options


def page_text(sb):
    try:
        return sb.execute_script("return document.body.innerText") or ""
    except Exception:
        return sb.get_page_source() or ""


def click_first_visible(sb, selectors, label, timeout=5):
    selector = None
    last_error = None
    for candidate in selectors:
        try:
            sb.wait_for_element_visible(candidate, timeout=timeout)
            selector = candidate
            break
        except Exception as e:
            last_error = e
            continue

    if not selector:
        print(f"未找到可点击的{label}: {last_error}")
        return False

    print(f"点击{label}: {selector}")
    sb.click(selector)
    return True


def extract_expiration(text):
    if not text:
        return ""
    patterns = [
        r"EXPIRATION DATE:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})",
        r"([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return ""


def open_server_detail(sb):
    """如果当前在列表页，进入服务器详情页。"""
    current_url = sb.get_current_url()
    if "/server/" in current_url:
        print(f"已在服务器详情页: {current_url}")
        return True

    detail_candidates = [
        "//a[contains(@href, '/server/')]",
        "//*[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'janver test server')]",
        "//*[contains(@class, 'server') and contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'server')]",
    ]
    if click_first_visible(sb, detail_candidates, "服务器详情入口", timeout=5):
        sb.sleep(4)
        if "/server/" in sb.get_current_url():
            print(f"已进入服务器详情页: {sb.get_current_url()}")
            return True

    print("未能进入服务器详情页")
    return False


def extend_from_list_if_needed(sb, limit_keywords):
    """列表页若存在 EXTEND SERVER，则点击并确认。"""
    list_extend_selectors = [
        "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'extend server')]",
        "//*[self::button or self::a or @role='button'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'extend server')]",
    ]
    selector = None
    for candidate in list_extend_selectors:
        try:
            if sb.is_element_visible(candidate):
                selector = candidate
                break
        except Exception:
            continue

    if not selector:
        print("列表页未发现 EXTEND SERVER 按钮，跳过列表续期步骤")
        return True

    print(f"列表页发现续期按钮，正在点击: {selector}")
    sb.click(selector)

    confirm_selectors = [
        "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'yes, extend the server')]",
        "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'yes, extend')]",
        "//*[self::button or self::a or @role='button'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'yes, extend the server')]",
        "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'tak') and contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'przedłuż')]",
    ]
    if click_first_visible(sb, confirm_selectors, "续期确认按钮", timeout=5):
        sb.sleep(4)
    else:
        print("未检测到续期确认弹窗，继续后续步骤")

    text = page_text(sb)
    if any(kw.lower() in text.lower() for kw in limit_keywords):
        print("列表续期后检测到冷却限制提示")
        return False

    return True


def add_six_hours_validity(sb, limit_keywords):
    """在详情页点击 ADD 6 HOURS VALIDITY。"""
    add_selectors = [
        "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add 6 hours validity')]",
        "//*[self::button or self::a or @role='button'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add 6 hours validity')]",
        "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'dodaj 6')]",
        "//*[self::button or self::a or @role='button'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'dodaj 6')]",
    ]

    if not click_first_visible(sb, add_selectors, "ADD 6 HOURS VALIDITY", timeout=8):
        return False, ""

    sb.sleep(4)
    text = page_text(sb)
    if any(kw.lower() in text.lower() for kw in limit_keywords):
        print("点击 ADD 6 HOURS VALIDITY 后检测到冷却限制提示")
        return False, extract_expiration(text)

    success_markers = [
        "You have extended the validity of your server",
        "SUKCES",
        "extended the validity",
        "przedłuż",
    ]
    expiration = extract_expiration(text)
    if any(marker.lower() in text.lower() for marker in success_markers) or expiration:
        print(f"ADD 6 HOURS VALIDITY 已执行，当前过期时间: {expiration or '未知'}")
        return True, expiration

    print("已点击 ADD 6 HOURS VALIDITY，但未明确识别到成功提示")
    return True, expiration


def ensure_server_started(sb, wait_seconds=20):
    """如果服务器处于关机/离线状态，则点击 START。"""
    start_selector = "//button[translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='start']"
    stop_selector = "//button[translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='stop']"

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        text = page_text(sb).lower()
        start_enabled = False
        stop_enabled = False
        try:
            if sb.is_element_visible(start_selector):
                start_enabled = not sb.execute_script(
                    "const el=document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; return !el || el.disabled;",
                    start_selector,
                )
            if sb.is_element_visible(stop_selector):
                stop_enabled = not sb.execute_script(
                    "const el=document.evaluate(arguments[0], document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; return !el || el.disabled;",
                    stop_selector,
                )
        except Exception:
            pass

        offline_like = any(token in text for token in ["offline", "suspended", "stopped", "wyłącz"])
        connecting = "connecting" in text

        if stop_enabled and not offline_like:
            print("服务器已处于可运行状态，无需点击 START")
            return True

        if start_enabled and (offline_like or not stop_enabled) and not connecting:
            print("检测到服务器离线/关机，正在点击 START ...")
            sb.click(start_selector)
            sb.sleep(8)
            sb.save_screenshot("icehost_debug_screenshot.png")
            after = page_text(sb).lower()
            if "offline" not in after or "online" in after or "running" in after:
                print("START 已点击，服务器启动流程已触发")
                return True
            print("START 已点击，但页面仍显示 offline，继续等待...")

        sb.sleep(2)

    print("等待 START 按钮可点击超时，或服务器状态仍不明确")
    return False


def run():
    if not SERVER_URL:
        print("错误: 缺少 ICEHOST_SERVER_URL 环境变量")
        return

    # 1. 启动 SeleniumBase，并按环境变量决定是否启用浏览器代理
    sb_options = build_sb_options()
    if "proxy" in sb_options:
        print("浏览器代理已启用")
    else:
        print("浏览器未使用代理，采用直连")

    with SB(**sb_options) as sb:
        print(f"正在访问 IceHost 面板: {SERVER_URL}")
        # 使用 UC 专属重连模式访问，能极大缓解首屏 Cloudflare 阻断
        sb.uc_open_with_reconnect(SERVER_URL, reconnect_time=8)
        sb.sleep(5)

        # 2. 注入 Cookies（已升级：智能兼容 JSON 或纯文本格式）
        if ICEHOST_COOKIES:
            try:
                cookies_to_add = []
                raw_cookies_str = ICEHOST_COOKIES.strip()

                # 尝试一：如果 Secret 填的是标准的 JSON 格式
                try:
                    raw_data = json.loads(raw_cookies_str)
                    if isinstance(raw_data, list):
                        cookies_to_add = raw_data
                    elif isinstance(raw_data, dict):
                        cookies_to_add = raw_data.get("cookies", [])
                    print("检测到 JSON 格式 Cookie，正在解析...")

                # 尝试二：如果解析失败，说明填的是纯文本（icehostpl_session=... 或直接是加密串）
                except json.JSONDecodeError:
                    print("检测到纯文本 Cookie 格式，正在自动提取并生成标准字段...")

                    # 提取真正的 Token 字符串值
                    token_value = raw_cookies_str
                    if "icehostpl_session=" in token_value:
                        token_value = token_value.split("icehostpl_session=")[1].split(";")[0]
                    elif "XSRF-TOKEN=" in token_value:
                        token_value = token_value.split("XSRF-TOKEN=")[1].split(";")[0]

                    token_value = token_value.strip()

                    # 最稳妥策略：自动为 Selenium 生成两个核心的 Cookie 字典
                    cookies_to_add = [
                        {"name": "icehostpl_session", "value": token_value, "domain": "dash.icehost.pl"},
                        {"name": "XSRF-TOKEN", "value": token_value, "domain": "dash.icehost.pl"}
                    ]

                # 统一执行转换与注入
                for c in cookies_to_add:
                    raw_value = c["value"]
                    decoded_value = urllib.parse.unquote(raw_value)

                    cookie_dict = {
                        "name": c["name"],
                        "value": decoded_value,
                        "domain": c.get("domain", "dash.icehost.pl"),
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True)
                    }
                    if "sameSite" in c:
                        ss = str(c["sameSite"]).lower()
                        if ss in ["lax", "strict", "none"]:
                            cookie_dict["sameSite"] = ss.capitalize()

                    sb.add_cookie(cookie_dict)

                print("Cookie 成功注入！")

                # 重新刷新加载，应用 Cookie
                sb.refresh()
                sb.sleep(5)
            except Exception as e:
                print(f"注入 Cookie 过程中发生异常，跳过: {e}")

        # 3. 核心过盾：自动寻找并执行系统级物理点击过 Cloudflare Turnstile 验证盾
        sb.save_screenshot("icehost_debug_screenshot.png")
        try:
            print("正在检测并调用系统级 PyAutoGUI 驱动，物理点击 Cloudflare 人机验证码...")
            # 在虚拟桌面上定位验证框并模拟发送系统硬件级点击事件
            sb.uc_gui_click_captcha()
            sb.sleep(10) # 给予 10 秒跳转缓冲
            sb.save_screenshot("icehost_debug_screenshot.png")
        except Exception as e:
            print(f"验证盾已被跳过或点击执行完毕: {e}")

        # 4. 判断登录状态
        current_url = sb.get_current_url()
        # 判断是否停留在登录页
        if "login" in current_url or sb.is_element_visible("input[type='email']"):
            msg = build_login_failed_message()
            print(msg)
            send_tg_notification(msg, "icehost_debug_screenshot.png")
            return

        # 登录态有效：立即导出当前最新 Cookie，供工作流回写 Secret 保活
        export_cookies(sb)

        # 5. 判定续期冷却限制（兼容波兰语 / 英语界面）
        limit_keywords = [
            "Nie możesz przedłużyć",
            "niedawno to zrobiłeś",
            "kolejne 6 godziny",
            "You cannot extend",
            "recently extended",
            "next 6 hours",
            "try again later",
        ]
        current_text = page_text(sb)
        server_name = extract_server_name(current_text)
        current_expiry = extract_expiration(current_text)
        if any(kw.lower() in current_text.lower() for kw in limit_keywords):
            msg = build_not_yet_due_message(server_name, current_expiry)
            print(msg)
            # 与参考脚本保持一致：未到续期时间也可发送状态通知
            send_tg_notification(msg, "icehost_debug_screenshot.png")
            return

        try:
            # 6. 列表页 EXTEND SERVER + 确认
            if not extend_from_list_if_needed(sb, limit_keywords):
                msg = build_not_yet_due_message(server_name, current_expiry)
                print(msg)
                sb.save_screenshot("icehost_debug_screenshot.png")
                send_tg_notification(msg, "icehost_debug_screenshot.png")
                return

            # 7. 进入服务器详情页
            if not open_server_detail(sb):
                msg = build_unconfirmed_message(
                    server_name,
                    current_expiry,
                    "未能进入服务器详情页，无法点击 ADD 6 HOURS VALIDITY",
                )
                print(msg)
                sb.save_screenshot("icehost_debug_screenshot.png")
                send_tg_notification(msg, "icehost_debug_screenshot.png")
                return

            sb.save_screenshot("icehost_debug_screenshot.png")
            detail_text = page_text(sb)
            server_name = extract_server_name(detail_text) or server_name
            current_expiry = extract_expiration(detail_text) or current_expiry

            # 8. 详情页点击 ADD 6 HOURS VALIDITY
            added, expiration = add_six_hours_validity(sb, limit_keywords)
            sb.save_screenshot("icehost_debug_screenshot.png")
            if not added:
                msg = build_unconfirmed_message(
                    server_name,
                    expiration or current_expiry,
                    "未能完成 ADD 6 HOURS VALIDITY",
                )
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")
                return

            # 9. 若关机/离线则点击 START
            started = ensure_server_started(sb)
            sb.save_screenshot("icehost_debug_screenshot.png")

            final_text = page_text(sb)
            expiration = extract_expiration(final_text) or expiration or current_expiry or "未知"
            server_name = extract_server_name(final_text) or server_name
            if started:
                msg = build_success_message(server_name, expiration, started=True)
            else:
                msg = build_unconfirmed_message(
                    server_name,
                    expiration,
                    "续期已执行，但 START 按钮未确认点击成功",
                )
            print(msg)
            send_tg_notification(msg, "icehost_debug_screenshot.png")
        except Exception as e:
            msg = build_error_message(str(e))
            print(msg)
            sb.save_screenshot("icehost_debug_screenshot.png")
            send_tg_notification(msg, "icehost_debug_screenshot.png")

if __name__ == "__main__":
    run()
