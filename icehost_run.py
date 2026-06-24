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

def check_is_cf_page(page):
    """精准检测当前是否仍卡在 Cloudflare 验证拦截页面"""
    try:
        title_match = "Challenge" in page.title()
        h1_match = page.locator("h1:has-text('Challenge')").first.is_visible()
        text_match_1 = page.locator("text=Connection Challenge").first.is_visible()
        text_match_2 = page.locator("text=Verify you are human").first.is_visible()
        return title_match or h1_match or text_match_1 or text_match_2
    except Exception:
        return False

def load_page_with_cf_bypass(page, url):
    """智能页面加载函数：通过未隔离的父级容器获取绝对物理坐标并实施多点精准点击"""
    print(f"正在访问页面: {url}")
    page.goto(url)
    
    # 轮询 15 秒，直接通过浏览器底层 Frame 列表搜寻验证盾 iframe
    turnstile_frame = None
    for i in range(15):
        for frame in page.frames:
            if "challenge-platform" in frame.url or "challenges.cloudflare.com" in frame.url:
                turnstile_frame = frame
                break
        if turnstile_frame:
            break
        page.wait_for_timeout(1000)

    if turnstile_frame:
        print("⚡ 成功通过底层接口穿透闭合影子 DOM 捕获到 Cloudflare 验证盾 iframe！")
        page.wait_for_timeout(3000) # 给予 3 秒缓冲时间确保其完全渲染完毕
        
        box = None
        # 核心突破：通过主页面上未被隔离和跨域限制的父级容器（如 #turnstile-wrapper、.cf-turnstile 等 div）获取物理边界框！
        for selector in ["#turnstile-wrapper", ".cf-turnstile", "div:has(iframe)", "iframe"]:
            try:
                temp_box = page.locator(selector).first.bounding_box()
                if temp_box and temp_box["width"] > 50 and temp_box["height"] > 20:
                    box = temp_box
                    print(f"✓ 成功通过选择器 '{selector}' 获取到验证盾物理坐标: x={box['x']:.1f}, y={box['y']:.1f}, w={box['width']:.1f}, h={box['height']:.1f}")
                    break
            except Exception:
                pass
                
        if not box:
            # 最终经验保底：如果全部读取失败，则使用 1280x720 视口下的标准经验坐标
            print("⚠️ 无法获取验证盾边界定位框，启用标准视口固定经验坐标...")
            box = {"x": 490.0, "y": 375.3, "width": 300.0, "height": 65.0}

        # 准备高精度点击
        base_x = box["x"]
        base_y = box["y"]
        h_center = box["height"] / 2
        
        # 精调网格点击点（针对复选框所在的左侧位置 30px ~ 45px 范围进行多点微调）
        points_to_click = [
            (base_x + 35, base_y + h_center),      # 1. 理论复选框正中心
            (base_x + 40, base_y + h_center),      # 2. 稍微偏右 5 像素
            (base_x + 30, base_y + h_center),      # 3. 稍微偏左 5 像素
            (base_x + 35, base_y + h_center - 5),  # 4. 微调偏上 5 像素
            (base_x + 35, base_y + h_center + 5),  # 5. 微调偏下 5 像素
            (base_x + box["width"] / 2, base_y + h_center) # 6. 验证码容器正中心点（保底）
        ]
        
        for x, y in points_to_click:
            if not check_is_cf_page(page):
                break
            print(f"正在模拟真人平滑移动至 ({x:.1f}, {y:.1f}) 并执行物理点击...")
            page.mouse.move(x, y, steps=10) # 模拟真人 10 步平滑移动轨迹
            page.wait_for_timeout(400)
            page.mouse.click(x, y)
            page.wait_for_timeout(6000) # 每次点击后等待 6 秒观察
            
            if not check_is_cf_page(page):
                print("✓ 恭喜！验证盾已成功解开，退出点击循环。")
                break
                
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
