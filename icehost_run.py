import os
import time
import json
import urllib.parse
import requests
from playwright.sync_api import sync_playwright
try:
    from playwright_stealth import Stealth
    _USE_STEALTH_CLASS = True
except ImportError:
    try:
        from playwright_stealth import stealth_sync
        _USE_STEALTH_CLASS = False
    except ImportError:
        print("警告: 系统中未找到 playwright-stealth 库，将跳过高级指纹混淆。")
        _USE_STEALTH_CLASS = None

SERVER_URL = os.getenv("ICEHOST_SERVER_URL")
ICEHOST_COOKIES = os.getenv("ICEHOST_COOKIES")

def send_tg_notification(message, photo_path=None):
    """发送结果和截图至 Telegram"""
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        print("未配置 TG 机器人变量，跳过发送 TG 推送。")
        return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload)
        print("TG 状态通知发送成功。")
    except Exception as e:
        print(f"发送 TG 消息异常: {e}")

    if photo_path and os.path.exists(photo_path):
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": chat_id, "caption": "IceHost 实时画面"}
                requests.post(url, data=data, files=files)
            print("TG 截图发送成功。")
        except Exception as e:
            print(f"发送 TG 截图异常: {e}")

def load_page_with_cf_bypass(page, url):
    """智能页面加载函数：利用物理坐标网格盲点点击法穿透 Cloudflare 的人机验证"""
    print(f"正在访问页面: {url}")
    page.goto(url)
    page.wait_for_timeout(8000) # 给予 8 秒让页面完成基础加载

    # 1. 检查是否处于 Cloudflare 验证页面（Connection Challenge）
    # 该标题属于外层 DOM 节点，完全未被隔离，可以 100% 稳定识别
    is_cf_page = (
        "Challenge" in page.title() or 
        page.locator("h1:has-text('Challenge')").first.is_visible() or
        page.locator("text=Connection Challenge").first.is_visible() or
        page.locator("text=Verify you are human").first.is_visible()
    )

    if is_cf_page:
        print("⚡ 检测到处于 Cloudflare Connection Challenge 验证页面！")
        print("正在启动终极盲点坐标网格点击法 (Bypass Closed Shadow DOM)...")
        
        # 在 1280x720 视口下，Cloudflare 验证盒子处于屏幕正中央
        # 整个盒子宽 300px，高 65px，中心点约为 (640, 405)，左侧复选框（Checkbox）中心大约在 (530, 405)
        # 我们设计一个高精度网格点击点列表，对该区域实施地毯式模拟物理点击，确保 100% 击中
        points_to_click = [
            (530, 405),  # 1. 理论复选框正中心
            (530, 395),  # 2. 复选框偏上
            (530, 415),  # 3. 复选框偏下
            (515, 405),  # 4. 复选框偏左
            (545, 405),  # 5. 常规验证区域中左
            (640, 405)   # 6. 验证盒正中心点（作为保底）
        ]
        
        for x, y in points_to_click:
            try:
                print(f"正在模拟真人鼠标平滑移动至 ({x}, {y}) 并执行物理点击...")
                page.mouse.move(x, y, steps=10) # 模拟真人 10 步平滑移动轨迹
                page.wait_for_timeout(300)
                page.mouse.click(x, y)
                page.wait_for_timeout(1500) # 等待 1.5 秒看是否有响应
                
                # 每点击完一个点，检查验证是否通过（如果标题变了或者挑战 H1 消失了，说明成功通过）
                current_cf_page = (
                    "Challenge" in page.title() or 
                    page.locator("h1:has-text('Challenge')").first.is_visible()
                )
                if not current_cf_page:
                    print("✓ 恭喜！验证已成功解开，退出点击循环。")
                    break
            except Exception as e:
                print(f"点击坐标 ({x}, {y}) 遇到问题，跳过: {e}")
                
        # 成功通过后，额外多等待 8 秒完成页面 React 数据加载
        print("正在等待页面 React 异步数据完全加载...")
        page.wait_for_timeout(8000)
    else:
        print("页面未检测到验证盾，或已成功跳过。")
        
    page.wait_for_timeout(3000)

def run():
    if not SERVER_URL or not ICEHOST_COOKIES:
        print("错误: 缺少 ICEHOST_SERVER_URL 或 ICEHOST_COOKIES")
        return

    with sync_playwright() as p:
        # 启用过检测参数，抹除自动化特征
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )

        # 隐藏自动化控制指纹
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            raw_data = json.loads(ICEHOST_COOKIES)
            cookies_to_add = []

            # 提取 Cookie
            if isinstance(raw_data, list):
                cookies_to_add = raw_data
            elif isinstance(raw_data, dict):
                cookies_to_add = raw_data.get("cookies", [])
            else:
                raise ValueError("未知的数据格式")

            # 1. 注入并进行高精度统一 URL 编码
            formatted_cookies = []
            for c in cookies_to_add:
                raw_value = c["value"]
                
                # 第一步：先解码，还原为未编码的原始字符
                clean_value = urllib.parse.unquote(raw_value)
                
                # 第二步：将原始字符进行全局统一的 URL 编码，避免 PHP 引擎加号漏洞
                encoded_value = urllib.parse.quote(clean_value)
                
                fc = {
                    "name": c["name"],
                    "value": encoded_value,
                    "domain": c["domain"],
                    "path": c.get("path", "/")
                }
                if "expirationDate" in c:
                    fc["expires"] = int(c["expirationDate"])
                if "secure" in c:
                    fc["secure"] = c["secure"]
                if "httpOnly" in c:
                    fc["httpOnly"] = c["httpOnly"]
                if "sameSite" in c:
                    ss = str(c["sameSite"]).lower()
                    if ss in ["no_restriction", "none"]:
                        fc["sameSite"] = "None"
                    elif ss == "lax":
                        fc["sameSite"] = "Lax"
                    elif ss == "strict":
                        fc["sameSite"] = "Strict"
                formatted_cookies.append(fc)
            
            context.add_cookies(formatted_cookies)
            print("Cookie 成功执行双重高精度 URL 编码并注入！已完美规避 PHP '+' 转换漏洞。")

        except Exception as e:
            print(f"凭证解析/注入失败: {e}")
            send_tg_notification(f"❌ <b>IceHost 运行异常</b>\n凭证解析注入失败: {e}")
            browser.close()
            return

        page = context.new_page()

        # ⚡ 核心修改：向页面注入高精防检测混淆
        if _USE_STEALTH_CLASS is True:
            try:
                stealth = Stealth()
                stealth.apply_stealth_sync(page)
                print("✓ 成功应用新版 playwright-stealth 混淆指纹！")
            except Exception as se:
                print(f"应用新版 stealth 失败，跳过: {se}")
        elif _USE_STEALTH_CLASS is False:
            try:
                stealth_sync(page)
                print("✓ 成功应用旧版 playwright-stealth 混淆指纹！")
            except Exception as se:
                print(f"应用旧版 stealth 失败，跳过: {se}")

        # 全局网络流量拦截与指纹清洗
        def handle_route(route):
            headers = {**route.request.headers}
            headers["sec-ch-ua"] = '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"'
            headers["sec-ch-ua-mobile"] = "?0"
            headers["sec-ch-ua-platform"] = '"Windows"'
            headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            route.continue_(headers=headers)

        page.route("**/*", handle_route)

        # 首次访问：使用优化后的过盾函数
        load_page_with_cf_bypass(page, SERVER_URL)

        # 首次截图
        page.screenshot(path="icehost_debug_screenshot.png")

        # 判断登录状态
        if "login" in page.url or page.locator("input[type='email']").first.is_visible():
            msg = "❌ <b>IceHost 登录失效！</b>\n请在浏览器重新提取并更新 ICEHOST_COOKIES。"
            print(msg)
            send_tg_notification(msg, "icehost_debug_screenshot.png")
            browser.close()
            return

        # 3. 检测是否已经达到了 6 小时限制（波兰语特征词）
        keywords = ["Nie możesz przedłużyć", "niedawno to zrobiłeś", "kolejne 6 godziny"]
        is_limited = False
        
        for kw in keywords:
            if page.locator(f"text={kw}").first.is_visible():
                is_limited = True
                break
        
        if is_limited:
            print("检测到红框限制提示：说明未到可续期时间。结束本次运行（不发送 Telegram 提醒）。")
            browser.close()
            return

        # 4. 如果没有到上限，安全寻找并点击续期按钮
        renew_btn = page.locator("a:has-text('DODAJ 6 GODZIN'), button:has-text('DODAJ 6 GODZIN'), [class*='blue']:has-text('DODAJ 6 GODZIN')").first
        
        if renew_btn.is_visible() and renew_btn.is_enabled():
            print("未检测到限制提示，找到续期按钮，正在点击...")
            renew_btn.click()
            
            # 点击后重新使用过盾函数
            load_page_with_cf_bypass(page, SERVER_URL)
            
            # 重新截图
            page.screenshot(path="icehost_debug_screenshot.png")
            
            # 二次检测结果
            is_now_limited = False
            for kw in keywords:
                if page.locator(f"text={kw}").first.is_visible():
                    is_now_limited = True
                    break
                    
            if is_now_limited:
                print("点击后弹出了红框提示：说明未到可续期时间（续期未成功）。结束本次运行（不发送 Telegram 提醒）。")
            else:
                msg = "⚡ <b>IceHost 服务器续期成功！</b>\n服务器已真正成功延长 6 小时有效期。"
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")
        else:
            print("未在页面中找到可用的蓝色续期按钮。")

        browser.close()

if __name__ == "__main__":
    run()
