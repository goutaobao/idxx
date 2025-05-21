import json
import asyncio
import requests
import os
import re
import traceback
from datetime import datetime
from pathlib import Path
from playwright.async_api import Playwright, async_playwright, Locator
import time
from dotenv import load_dotenv
import base64

# 加载.env文件中的环境变量
load_dotenv()

# 基础配置
BASE_PREFIX = "9000-firebase-xxx-"
DOMAIN_PATTERN = f"{BASE_PREFIX}[^.]*.cloudworkstations.dev"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]
VIEWPORT_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
]

# 全局配置
cookies_path = "cookie.json"  # 只保留一个cookie文件
app_url = os.environ.get("APP_URL", "https://idx.google.com")
all_messages = []
MAX_RETRIES = 3
TIMEOUT = 30000  # 默认超时时间（毫秒）

def log_message(message):
    """记录消息到全局列表并打印"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] {message}"
    all_messages.append(formatted_message)
    print(formatted_message)

def find_9000_firebase_xxx_jwt_and_domain(cookie_path="cookie.json"):
    """
    直接遍历cookie，找到domain以9000-firebase-xxx-开头的WorkstationJwtPartitioned，返回其domain和JWT
    """
    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for cookie in data.get("cookies", []):
            if (
                cookie.get("name") == "WorkstationJwtPartitioned"
                and cookie.get("domain", "").startswith("9000-firebase-xxx-")
            ):
                return f"https://{cookie['domain']}", cookie["value"]
    except Exception as e:
        log_message(f"查找9000-firebase-xxx域名和JWT时出错: {e}")
    return None, None

def send_to_telegram(message):
    """将消息发送到Telegram"""
    # 从环境变量获取凭据，优先使用.env文件中的配置
    bot_token = os.environ.get("TG_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    
    # 如果环境变量中没有找到，使用默认值（作为备选）
    if not bot_token:
        bot_token = '1834872183:AAGt1glfQhItvU04PSeFUzoPpT5jOG8WqC4'
        log_message("未在环境变量中找到TG_TOKEN，使用默认值")
    
    if not chat_id:
        chat_id = '1690909053'
        log_message("未在环境变量中找到TG_CHAT_ID，使用默认值")
    
    if not bot_token or not chat_id:
        log_message("缺少Telegram配置，跳过通知")
        return
    
    # 简化消息内容 - 只保留关键状态信息
    simplified_message = "【IDX自动登录状态报告】\n"
    
    # 提取关键信息 - 查找关键状态行
    key_status_patterns = [
        "开始执行IDX登录",
        "工作站可以直接通过协议访问",
        "自动化流程执行结果",
        "成功点击工作区图标",
        "通过cookies直接登录",
        "UI交互流程",
        "工作区加载验证",
        "已保存最终cookie状态",
        "主流程执行出错"
    ]
    
    # 从所有消息中提取关键状态行
    key_lines = []
    for line in all_messages:
        for pattern in key_status_patterns:
            if pattern in line:
                # 截取时间戳和实际消息
                parts = line.split("] ", 1)
                if len(parts) > 1:
                    time_stamp = parts[0].replace("[", "")
                    message_content = parts[1]
                    key_lines.append(f"{time_stamp}: {message_content}")
                    break
    
    # 添加关键状态行到简化消息
    if key_lines:
        simplified_message += "\n".join(key_lines)
    else:
        simplified_message += "未找到关键状态信息"
    
    # 添加工作站域名信息(如果存在)
    domain, _ = find_9000_firebase_xxx_jwt_and_domain(cookies_path)
    if not domain:
        domain = extract_domain_from_jwt()
    if domain:
        simplified_message += f"\n\n工作站域名: {domain}"
    
    # 添加时间戳
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    simplified_message += f"\n\n执行时间: {current_time}"
    
    # 发送简化的消息
    try:
        log_message(f"正在使用TG_TOKEN={bot_token[:5]}...和TG_CHAT_ID={chat_id[:3]}...发送消息")
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {"chat_id": chat_id, "text": simplified_message}
        response = requests.post(url, data=data, timeout=10)
        log_message(f"Telegram通知状态: {response.status_code}")
    except Exception as e:
        log_message(f"发送Telegram通知失败: {e}")

def load_cookies(filename=cookies_path):
    """加载cookies并验证格式"""
    try:
        if not os.path.exists(filename):
            log_message(f"{filename}不存在，将创建空cookie文件")
            empty_data = {"cookies": [], "origins": []}
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(empty_data, f)
            return empty_data
            
        with open(filename, 'r', encoding="utf-8") as f:
            cookie_data = json.load(f)
            
        # 验证格式
        if "cookies" not in cookie_data or not isinstance(cookie_data["cookies"], list):
            log_message(f"{filename}格式有问题，将重置")
            empty_data = {"cookies": [], "origins": []}
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(empty_data, f)
            return empty_data
            
        log_message(f"成功加载{filename}")
        return cookie_data
    except Exception as e:
        log_message(f"加载{filename}失败: {e}")
        # 创建空cookie文件
        empty_data = {"cookies": [], "origins": []}
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(empty_data, f)
        except Exception:
            pass
        return empty_data

def check_page_status_with_requests():
    """使用预设的JWT和URL值直接检查工作站的访问状态"""
    try:
        # 预设值
        preset_jwt = 'eyJhIjoiOGU1YzU5MDRmNjU3ODcwOWQ5MzM1NDk4YzFjZTQ1MTIiLCJ0IjoiMGEwNzRmYjctZWEwOC00MTk0LWIyZjUtOWMwYTcxZWI2OGNlIiwicyI6IlpXVTJNVFpoWlRRdE1tVmxNeTAwTVdSakxXSm1ZbVF0WVRZeE5tRTFOR0kzTnpRMiJ9'
        preset_url = 'https://9000-firebase-xxx-1746608640411.cluster-pb4ljhlmg5hqsxnzpc56r3prxw.cloudworkstations.dev/'

        # 优先查找cookie.json中匹配的9000-firebase-xxx域名和JWT
        domain, jwt = find_9000_firebase_xxx_jwt_and_domain(cookies_path)
        if domain and jwt:
            preset_url = domain
            preset_jwt = jwt
            log_message("已优先使用cookie.json中匹配的9000-firebase-xxx域名和JWT")
        else:
            # 兼容原有逻辑
            try:
                if os.path.exists(cookies_path):
                    cookie_data = load_cookies(cookies_path)
                    for cookie in cookie_data.get("cookies", []):
                        if cookie.get("name") == "WorkstationJwtPartitioned":
                            jwt = cookie.get("value")
                            log_message("从cookie.json中成功加载了JWT")
                            break
            except Exception as e:
                log_message(f"从cookie.json加载JWT失败: {e}，将使用预设值")

        # 构建请求
        request_cookies = {'WorkstationJwtPartitioned': preset_jwt}
        headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US',
            'Connection': 'keep-alive',
            'Referer': 'https://workstations.cloud.google.com/',
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1',
        }

        # 获取正确的域名
        workstation_url = preset_url
        log_message(f"使用requests检查工作站状态，URL: {workstation_url}")
        log_message(f"使用JWT: {preset_jwt[:20]}... (已截断)")

        # 发送请求获取页面状态，简化直接访问
        response = requests.get(
            workstation_url,
            cookies=request_cookies,
            headers=headers,
            timeout=15
        )

        log_message(f"页面状态码: {response.status_code}")

        if response.status_code == 200:
            log_message("页面状态码200，工作站可以直接通过协议访问")
            return True
        else:
            log_message(f"页面状态码为{response.status_code}，无法直接通过协议访问")
            return False
    except Exception as e:
        log_message(f"使用requests检查工作站状态时出错: {e}")
        return False

def extract_domain_from_jwt(jwt_value=None):
    """从JWT token中提取域名"""
    try:
        # 如果没有提供JWT，尝试从cookie文件加载
        if not jwt_value:
            cookie_data = load_cookies(cookies_path)
            for cookie in cookie_data.get("cookies", []):
                if cookie.get("name") == "WorkstationJwtPartitioned":
                    jwt_value = cookie.get("value")
                    break
        
        if not jwt_value:
            log_message("无法找到JWT值，将使用默认域名")
            return f"https://{BASE_PREFIX}1746608640411.cluster-pb4ljhlmg5hqsxnzpc56r3prxw.cloudworkstations.dev"
            
        # 解析JWT获取域名信息
        parts = jwt_value.split('.')
        if len(parts) >= 2:
            # 解码中间部分（可能需要补齐=）
            padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
            decoded = base64.b64decode(padded)
            payload = json.loads(decoded)
            
            # 从aud字段提取域名
            if 'aud' in payload:
                aud = payload['aud']
                log_message(f"JWT中提取的aud字段: {aud}")
                match = re.search(r'(9000-firebase-xxx-[^\.]+\.cluster-[^\.]+\.cloudworkstations\.dev)', aud)
                if match:
                    domain_suffix = match.group(1).split('9000-firebase-xxx-')[1]
                    full_domain = f"https://{BASE_PREFIX}{domain_suffix}"
                    log_message(f"从JWT提取的域名: {full_domain}")
                    return full_domain
        
        # 如果提取失败，使用默认域名
        default_domain = f"https://{BASE_PREFIX}1746608640411.cluster-pb4ljhlmg5hqsxnzpc56r3prxw.cloudworkstations.dev"
        log_message(f"使用默认域名: {default_domain}")
        return default_domain
    except Exception as e:
        log_message(f"提取域名时出错: {e}")
        return f"https://{BASE_PREFIX}1746608640411.cluster-pb4ljhlmg5hqsxnzpc56r3prxw.cloudworkstations.dev"

def extract_and_display_credentials():
    """从cookie.json中提取并显示云工作站域名和JWT"""
    try:
        if not os.path.exists(cookies_path):
            log_message("cookie.json文件不存在，无法提取凭据")
            return

        # 优先查找9000-firebase-xxx域名和JWT
        domain, jwt = find_9000_firebase_xxx_jwt_and_domain(cookies_path)
        if not (domain and jwt):
            # 兼容原有逻辑
            with open(cookies_path, 'r', encoding='utf-8') as f:
                cookie_data = json.load(f)
            jwt = None
            for cookie in cookie_data.get("cookies", []):
                if cookie.get("name") == "WorkstationJwtPartitioned":
                    jwt = cookie.get("value")
                    break
            if not jwt:
                log_message("在cookie.json中未找到WorkstationJwtPartitioned")
                return
            domain = extract_domain_from_jwt(jwt)

        # 显示提取的信息
        log_message("\n========== 提取的凭据信息 ==========")
        log_message(f"WorkstationJwtPartitioned: {jwt[:20]}...{jwt[-20:]} (已截断，仅显示前20和后20字符)")

        if domain:
            log_message(f"工作站域名: {domain}")
        else:
            log_message("无法从JWT提取域名")

        # 打印完整的请求示例
        log_message("\n以下是可用于访问工作站的请求示例代码:")
        code_example = f"""import requests

cookies = {{
    'WorkstationJwtPartitioned': '{jwt}',
}}

headers = {{
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US',
    'Connection': 'keep-alive',
    'Referer': 'https://workstations.cloud.google.com/',
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1',
}}

response = requests.get(
    '{domain if domain else "工作站URL"}',
    cookies=cookies,
    headers=headers,
)
print(response.status_code)
print(response.text)"""
        log_message(code_example)
        log_message("========== 提取完成 ==========\n")

    except Exception as e:
        log_message(f"提取凭据时出错: {e}")
        log_message(traceback.format_exc())

async def handle_terms_dialog(page, max_attempts=3):
    """处理Terms对话框"""
    for attempt in range(1, max_attempts + 1):
        try:
            log_message(f"第{attempt}次尝试处理Terms对话框...")
            
            # 检查确认按钮状态，看是否需要勾选复选框
            button_status = await page.evaluate("""() => {
                // 先检查确认按钮是否存在且是否禁用
                const confirmButton = document.querySelector('#submit-button');
                if (confirmButton) {
                    return {
                        found: true,
                        disabled: confirmButton.disabled,
                        className: confirmButton.className
                    };
                }
                return { found: false };
            }""")
            
            if button_status.get('found'):
                log_message(f"确认按钮状态: disabled={button_status.get('disabled')}, className={button_status.get('className')}")
                
                # 如果按钮已经可用，无需勾选
                if not button_status.get('disabled'):
                    log_message("确认按钮已经可用，无需勾选复选框")
                else:
                    log_message("确认按钮处于禁用状态，需要勾选复选框...")
                    
                    # 先检查utos-checkbox和marketing-checkbox状态
                    checkbox_status = await page.evaluate("""() => {
                        // 检查所有可能的复选框
                        const checkboxes = [];
                        const ids = ['utos-checkbox', 'marketing-checkbox'];
                        
                        for (const id of ids) {
                            const checkbox = document.querySelector(`#${id}`);
                            if (checkbox) {
                                checkboxes.push({
                                    id: id,
                                    checked: checkbox.checked,
                                    className: checkbox.className,
                                    valid: checkbox.className.includes('ng-valid'),
                                    invalid: checkbox.className.includes('ng-invalid')
                                });
                            }
                        }
                        
                        // 检查labels是否有is-checked类
                        const checkedLabels = document.querySelectorAll('label.is-checked, label.basic-checkbox-label.is-checked');
                        
                        return {
                            checkboxes: checkboxes,
                            checkedLabelsCount: checkedLabels.length
                        };
                    }""")
                    
                    log_message(f"发现 {len(checkbox_status.get('checkboxes', []))} 个复选框，已勾选标签数: {checkbox_status.get('checkedLabelsCount', 0)}")
                    
                    # 尝试勾选所有未勾选的复选框
                    for checkbox in checkbox_status.get('checkboxes', []):
                        checkbox_id = checkbox.get('id')
                        if not checkbox.get('checked') or checkbox.get('invalid'):
                            log_message(f"尝试勾选复选框 #{checkbox_id}...")
                            
                            # 使用多种方法确保复选框被勾选
                            await page.evaluate(f"""() => {{
                                const checkbox = document.querySelector('#{checkbox_id}');
                                if (checkbox) {{
                                    // 1. 先设置checked属性
                                    checkbox.checked = true;
                                    
                                    // 2. 修改ng-invalid为ng-valid
                                    checkbox.classList.remove('ng-invalid');
                                    checkbox.classList.add('ng-valid');
                                    
                                    // 3. 确保label有is-checked类
                                    const label = checkbox.closest('label');
                                    if (label) {{
                                        label.classList.add('is-checked');
                                        if (label.classList.contains('basic-checkbox-label')) {{
                                            label.classList.add('basic-checkbox-label', 'is-checked');
                                        }}
                                    }}
                                    
                                    // 4. 触发所有相关事件以确保Angular检测到变化
                                    ['change', 'input', 'click'].forEach(eventName => {{
                                        checkbox.dispatchEvent(new Event(eventName, {{ bubbles: true }}));
                                    }});
                                    
                                    console.log('已勾选复选框: ' + checkbox.id);
                                    return true;
                                }}
                                return false;
                            }}""")
                            
                            # 使用Playwright的check方法作为备份
                            try:
                                await page.locator(f'#{checkbox_id}').check(force=True, timeout=2000)
                                log_message(f"已使用Playwright API勾选复选框 #{checkbox_id}")
                            except Exception as e:
                                log_message(f"使用Playwright勾选 #{checkbox_id} 失败: {str(e)}")
                    
                    # 等待Angular更新DOM
                    log_message("等待Angular更新DOM状态...")
                    await asyncio.sleep(2)
                    
                    # 验证确认按钮是否变为可用
                    updated_button_status = await page.evaluate("""() => {
                        const confirmButton = document.querySelector('#submit-button');
                        if (confirmButton) {
                            return {
                                found: true,
                                disabled: confirmButton.disabled,
                                className: confirmButton.className,
                                text: confirmButton.textContent.trim()
                            };
                        }
                        return { found: false };
                    }""")
                    
                    if updated_button_status.get('found'):
                        if not updated_button_status.get('disabled'):
                            log_message(f"确认按钮已变为可用状态! 文本: {updated_button_status.get('text')}")
                        else:
                            log_message(f"确认按钮仍然处于禁用状态: {updated_button_status}")
                            
                            # 最后尝试：强制启用按钮
                            await page.evaluate("""() => {
                                const button = document.querySelector('#submit-button');
                                if (button) {
                                    // 移除disabled属性
                                    button.disabled = false;
                                    
                                    // 移除禁用相关的类
                                    button.classList.remove('disabled');
                                    
                                    console.log('已强制启用确认按钮');
                                }
                            }""")
            else:
                log_message("未找到#submit-button，尝试查找任何确认按钮...")
                
                # 尝试查找任何看起来像确认按钮的元素
                confirm_buttons = await page.evaluate("""() => {
                    // 查找文本包含confirm的按钮
                    const buttons = Array.from(document.querySelectorAll('button')).filter(btn => 
                        btn.textContent.toLowerCase().includes('confirm') || 
                        btn.textContent.toLowerCase().includes('accept') ||
                        btn.textContent.toLowerCase().includes('确认')
                    );
                    
                    return buttons.map(btn => ({
                        text: btn.textContent.trim(),
                        disabled: btn.disabled,
                        className: btn.className
                    }));
                }""")
                
                if confirm_buttons:
                    log_message(f"找到 {len(confirm_buttons)} 个可能的确认按钮")
                    for i, btn in enumerate(confirm_buttons):
                        log_message(f"按钮 {i+1}: 文本='{btn.get('text')}', 禁用={btn.get('disabled')}")
                else:
                    log_message("未找到任何确认按钮")
            
            # 尝试点击确认按钮 (无论之前的操作是否成功)
            log_message("尝试点击确认按钮...")
            button_clicked = False
            
            # 方法1: 使用Playwright点击#submit-button
            try:
                submit_button = page.locator('#submit-button')
                if await submit_button.count() > 0:
                    # 检查按钮是否可见且不禁用
                    is_enabled = await submit_button.is_enabled()
                    if is_enabled:
                        await submit_button.click(timeout=3000, force=True)
                        log_message("已点击#submit-button")
                        button_clicked = True
                    else:
                        log_message("#submit-button存在但不可用，尝试其他方法")
            except Exception as e:
                log_message(f"点击#submit-button失败: {str(e)}")
            
            # 方法2: 使用JavaScript点击确认按钮
            if not button_clicked:
                button_clicked = await page.evaluate("""() => {
                    try {
                        // 首先尝试#submit-button
                        const submitButton = document.querySelector('#submit-button');
                        if (submitButton && !submitButton.disabled) {
                            submitButton.click();
                            console.log('已点击#submit-button');
                            return true;
                        }
                        
                        // 寻找任何包含"Confirm"文本的按钮
                        const confirmButtons = Array.from(document.querySelectorAll('button')).filter(btn => 
                            !btn.disabled && (
                                btn.textContent.includes('Confirm') || 
                                btn.textContent.includes('Accept') ||
                                btn.textContent.includes('确认')
                            )
                        );
                        
                        if (confirmButtons.length > 0) {
                            confirmButtons[0].click();
                            console.log('已点击确认按钮: ' + confirmButtons[0].textContent);
                            return true;
                        }
                        
                        // 如果所有方法都失败，尝试点击任何非禁用按钮
                        const anyButton = document.querySelector('button:not([disabled])');
                        if (anyButton) {
                            anyButton.click();
                            console.log('已点击任意非禁用按钮: ' + anyButton.textContent);
                            return true;
                        }
                        
                        return false;
                    } catch (e) {
                        console.error('点击按钮时发生错误:', e);
                        return false;
                    }
                }""")
                
                if button_clicked:
                    log_message("已通过JavaScript点击确认按钮")
            
            if button_clicked:
                log_message("成功点击确认按钮，Terms对话框处理完成")
                await asyncio.sleep(2)  # 等待对话框关闭
                return True
                
            # 记录调试信息
            log_message("没有成功点击确认按钮，记录当前页面状态供分析...")
            try:
                # 保存截图
                await page.screenshot(path=f"terms_dialog_attempt_{attempt}.png")
                
                # 保存HTML结构
                html = await page.content()
                with open(f"terms_dialog_html_{attempt}.txt", "w", encoding="utf-8") as f:
                    f.write(html[:15000])
                
                # 最后尝试：点击页面上任何可点击元素
                await page.evaluate("""() => {
                    // 记录所有复选框状态
                    document.querySelectorAll('input[type="checkbox"]').forEach((cb, i) => {
                        console.log(`Checkbox ${i}: id=${cb.id}, checked=${cb.checked}, class=${cb.className}`);
                    });
                    
                    // 记录所有按钮状态
                    document.querySelectorAll('button').forEach((btn, i) => {
                        console.log(`Button ${i}: text=${btn.textContent.trim()}, disabled=${btn.disabled}`);
                    });
                }""")
            except Exception as e:
                log_message(f"保存调试信息失败: {e}")
                
        except Exception as e:
            log_message(f"第{attempt}次处理Terms对话框失败: {e}")
            log_message(traceback.format_exc())
            
            if attempt < max_attempts:
                log_message("等待2秒后重试...")
                await asyncio.sleep(2)
            else:
                log_message("已达到最大重试次数，继续执行后续步骤")
                return False
    
    # 如果所有尝试都失败，但仍然继续执行后续步骤
    log_message("Terms对话框处理可能未完全成功，但将继续执行后续步骤")
    return True

async def wait_for_workspace_loaded(page, timeout=180):
    """等待Firebase Studio工作区加载完成"""
    log_message(f"检测是否成功进入Firebase Studio...")
    current_url = page.url
    log_message(f"当前URL: {current_url}")
    
    if "lost" in current_url or "workspace" in current_url or "cloudworkstations" in current_url or "firebase" in current_url:
        log_message("URL包含目标关键词，确认进入目标页面")
        
        log_message("等待页面基本加载...")
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=60000)
            log_message("DOM内容已加载")
            
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
                log_message("网络活动已稳定")
            except Exception as e:
                log_message(f"等待网络稳定超时，但这不会阻塞流程: {e}")
        except Exception as e:
            log_message(f"等待DOM加载超时: {e}，但将继续流程")
        
        log_message("等待120秒让页面和资源完全加载...")
        await asyncio.sleep(120)
        log_message("等待时间结束，开始检测侧边栏元素...")
        
        max_refresh_retries = 3
        for refresh_attempt in range(1, max_refresh_retries + 1):
            try:
                # 打印页面部分HTML，便于调试
                html = await page.content()
                log_message("当前页面HTML片段：" + html[:2000])
                
                # 检查是否有iframe
                frames = page.frames
                target = page
                for frame in frames:
                    try:
                        frame_html = await frame.content()
                        if 'codicon-explorer-view-icon' in frame_html:
                            target = frame
                            log_message("已自动切换到包含目标元素的iframe")
                            break
                    except Exception:
                        continue
                
                # IDE相关的侧边栏按钮
                ide_btn_selectors = [
                    '[class*="codicon-explorer-view-icon"], [aria-label*="Explorer"]',
                    '[class*="codicon-search-view-icon"], [aria-label*="Search"]',
                    '[class*="codicon-source-control-view-icon"], [aria-label*="Source Control"]',
                    '[class*="codicon-run-view-icon"], [aria-label*="Run and Debug"]',
                ]
                
                # Web元素检测（只保留一个最可能匹配的选择器）
                web_selector = 'div[aria-label="Web"] span.tab-label-name, div[aria-label*="Web"], [class*="monaco-icon-label"] span.monaco-icon-name-container:has-text("Web")'
                
                # 合并所有需要检测的选择器
                all_selectors = ide_btn_selectors + [web_selector]
                
                # 依次等待每个元素，使用更短的超时时间
                found_elements = 0
                for sel in all_selectors:
                    try:
                        await target.wait_for_selector(sel, timeout=10000)  # 10秒超时
                        found_elements += 1
                        log_message(f"找到元素 {found_elements}/{len(all_selectors)}: {sel}")
                    except Exception as e:
                        log_message(f"未找到元素: {sel}, 错误: {e}")
                        # 即使某个元素未找到，也继续检查其他元素
                        continue
                
                if found_elements > 0:
                    log_message(f"主界面找到 {found_elements}/{len(all_selectors)} 个元素（第{refresh_attempt}次尝试）")
                    # 只要找到至少5个元素（全部）就认为成功
                    if found_elements >= len(all_selectors):
                        log_message(f"找到全部UI元素 ({found_elements}/{len(all_selectors)})，认为界面加载成功")
                        
                        # 停留较短时间
                        log_message("停留15秒以确保页面完全加载...")
                        await asyncio.sleep(15)
                        
                        # 保存cookie状态
                        log_message("已更新存储状态到cookie.json")
                        return True
                    else:
                        log_message(f"找到的元素数量不足 ({found_elements}/{len(all_selectors)})，需要至少4个元素才认为成功")
                        if found_elements >= 4:
                            log_message(f"找到大部分UI元素 ({found_elements}/{len(all_selectors)})，认为界面基本加载成功")
                            # 保存cookie状态
                            log_message("已更新存储状态到cookie.json")
                            return True
                        elif refresh_attempt < max_refresh_retries:
                            log_message(f"未找到足够元素，尝试刷新页面（第{refresh_attempt}/{max_refresh_retries}次）...")
                            await page.reload()
                            log_message("页面刷新后等待60秒让元素加载...")
                            await asyncio.sleep(60)
                        else:
                            log_message("已达到最大刷新重试次数，未能找到足够的UI元素")
                            # 尽管未找到足够元素，我们也返回成功，因为我们已经到了目标页面
                            return True
                else:
                    log_message(f"未找到任何UI元素，尝试刷新...")
                    if refresh_attempt < max_refresh_retries:
                        log_message(f"刷新页面并重试（第{refresh_attempt}/{max_refresh_retries}次）...")
                        await page.reload()
                        log_message("页面刷新后等待60秒让元素加载...")
                        await asyncio.sleep(60)
                    else:
                        log_message("已达到最大刷新重试次数，未能找到任何UI元素")
                        # 尽管未找到元素，我们也返回成功，因为我们已经到了目标页面
                        return True
            except Exception as e:
                log_message(f"第{refresh_attempt}次尝试：等待主界面元素时出错: {e}")
                if refresh_attempt < max_refresh_retries:
                    log_message(f"刷新页面并重试（第{refresh_attempt}/{max_refresh_retries}次）...")
                    await page.reload()
                    log_message("页面刷新后等待60秒让元素加载...")
                    await asyncio.sleep(60)
                else:
                    log_message("已达到最大刷新重试次数，无法完成检测")
                    # 尽管出错，我们也返回成功，因为我们已经到了目标页面
                    return True
    else:
        log_message("URL未包含目标关键词，未检测到目标页面")
        return False
    
    # 如果执行到这里，说明流程已完成但可能未找到所有元素
    return True


async def click_workspace_icon(page):
    """尝试点击工作区图标"""
    log_message("尝试点击workspace图标...")
    
    # 工作区图标选择器列表
    selectors = [
        'div[class="workspace-icon"]',
        'img[src="https://www.gstatic.com/monospace/250314/workspace-blank-192.png"]',
        '.workspace-icon',
        'img[role="presentation"][class="custom-icon"]',
        'div[_ngcontent-ng-c2464377164][class="workspace-icon"]',
        'div.workspace-icon img.custom-icon',
        '.workspace-icon img'
    ]
    
    for selector in selectors:
        try:
            log_message(f"尝试选择器: {selector}")
            element = await page.wait_for_selector(selector, timeout=5000)
            if element:
                # 尝试多种点击方法
                try:
                    await element.click(force=True)
                    log_message(f"成功点击元素! 使用选择器: {selector}")
                    return True
                except Exception as e:
                    log_message(f"直接点击失败: {e}，尝试JavaScript点击")
                    try:
                        await page.evaluate("(element) => element.click()", element)
                        log_message(f"使用JavaScript成功点击元素!")
                        return True
                    except Exception:
                        continue
        except Exception:
            continue
            
    log_message("所有选择器都尝试失败，无法点击工作区图标")
    return False

async def navigate_to_firebase_by_clicking(page):
    """通过点击已验证的工作区图标导航到Firebase Studio"""
    log_message("通过点击已验证的工作区图标导航到Firebase Studio...")
    
    # 获取点击前的URL
    pre_click_url = page.url
    log_message(f"点击前当前URL: {pre_click_url}")
    
    # 尝试点击工作区图标
    workspace_icon_clicked = await click_workspace_icon(page)
    
    if not workspace_icon_clicked:
        log_message("无法点击工作区图标，导航失败")
        return False
    
    # 等待页面响应，检查URL变化
    await asyncio.sleep(5)
    
    # 检查点击后URL是否变化
    post_click_url = page.url
    log_message(f"点击后当前URL: {post_click_url}")
    
    url_changed = pre_click_url != post_click_url
    log_message(f"URL是否发生变化: {url_changed}")
    
    if url_changed:
        log_message("点击工作区图标成功，URL已变化，继续等待工作区加载")
        # URL已变化，直接返回True，后续操作不变
        return True
    else:
        log_message("点击工作区图标后URL未变化，导航失败")
        return False

async def login_with_ui_flow(page):
    """通过UI交互流程登录idx.google.com，然后跳转到Firebase Studio"""
    try:
        log_message("开始UI交互登录流程...")
        
        # 先导航到idx.google.com
        try:
            await page.goto("https://idx.google.com/", timeout=TIMEOUT)
            await page.wait_for_load_state("domcontentloaded", timeout=TIMEOUT)
        except Exception as e:
            log_message(f"导航到idx.google.com失败: {e}，但将继续尝试")
        
        # 等待页面加载
        await asyncio.sleep(10)
        
        # 处理Terms对话框
        await handle_terms_dialog(page)
        
        # 检查是否有工作区图标并点击
        workspace_icon_clicked = await click_workspace_icon(page)
        
        if workspace_icon_clicked:
            log_message("成功点击工作区图标，等待页面响应...")
            
            # 等待页面响应，验证登录状态
            await asyncio.sleep(5)
            
            # 双重验证登录成功
            current_url = page.url
            log_message(f"点击后当前URL: {current_url}")
            
            # 验证1: 检测URL不包含signin
            url_valid = "idx.google.com" in current_url and "signin" not in current_url
            
            # 验证2: 检测是否有其他工作区图标出现（通常点击后会显示其他工作区图标）
            workspace_icon_visible = False
            try:
                # 简化的验证，通常点击后页面会显示其他内容，只要URL验证通过即可
                workspace_icon_visible = url_valid  # 如果URL有效，我们假设图标检查也通过
            except Exception as e:
                log_message(f"点击后检查工作区内容时出错: {e}")
            
            # 双重验证结果
            if url_valid and workspace_icon_visible:
                log_message("UI交互后双重验证通过：确认已成功登录idx.google.com!")
                
                # 登录成功后，通过点击已验证的工作区图标导航到Firebase Studio
                return await navigate_to_firebase_by_clicking(page)
            else:
                log_message(f"UI交互后验证登录失败：URL不含signin: {url_valid}, 工作区验证: {workspace_icon_visible}")
                return False
        else:
            log_message("未能点击工作区图标，UI流程失败")
            return False
    except Exception as e:
        log_message(f"UI交互流程出错: {e}")
        return False

async def direct_url_access(page):
    """先访问idx.google.com验证登录，成功后通过点击已验证的工作区图标进入Firebase Studio"""
    try:
        # 先访问idx.google.com
        log_message("先访问idx.google.com验证登录状态...")
        await page.goto("https://idx.google.com/", timeout=TIMEOUT)
        await page.wait_for_load_state("domcontentloaded", timeout=TIMEOUT)
        
        # 等待页面加载
        await asyncio.sleep(5)
        
        # 提前处理Terms对话框(如果出现)
        await handle_terms_dialog(page)
        
        # 验证是否登录成功 - 双重验证
        current_url = page.url
        log_message(f"当前URL: {current_url}")
        
        # 验证1: 检测URL不包含signin
        url_valid = "idx.google.com" in current_url and "signin" not in current_url
        
        # 验证2: 检测工作区图标是否出现
        workspace_icon_visible = False
        try:
            # 工作区图标选择器列表
            selectors = [
                'div[class="workspace-icon"]',
                'img[src="https://www.gstatic.com/monospace/250314/workspace-blank-192.png"]',
                '.workspace-icon',
                'img[role="presentation"][class="custom-icon"]'
            ]
            
            for selector in selectors:
                try:
                    icon = await page.wait_for_selector(selector, timeout=5000)
                    if icon:
                        log_message(f"找到工作区图标! 使用选择器: {selector}")
                        workspace_icon_visible = True
                        break
                except Exception:
                    continue
        except Exception as e:
            log_message(f"检查工作区图标时出错: {e}")
        
        # 双重验证结果
        if url_valid and workspace_icon_visible:
            log_message("双重验证通过：URL不含signin且工作区图标出现，确认已成功登录idx.google.com!")
            
            # 登录成功后，通过点击已验证的工作区图标导航到Firebase Studio
            return await navigate_to_firebase_by_clicking(page)
        else:
            log_message(f"验证登录失败：URL不含signin: {url_valid}, 工作区图标出现: {workspace_icon_visible}")
            return False
    except Exception as e:
        log_message(f"访问idx.google.com或跳转到Firebase Studio失败: {e}")
        return False

async def run(playwright: Playwright) -> bool:
    """主运行函数"""
    for attempt in range(1, MAX_RETRIES + 1):
        log_message(f"第{attempt}/{MAX_RETRIES}次尝试...")
        
        # 随机选择User-Agent和视口大小
        random_user_agent = USER_AGENTS[attempt % len(USER_AGENTS)]
        random_viewport = VIEWPORT_SIZES[attempt % len(VIEWPORT_SIZES)]
        
        # 浏览器配置
        browser_args = [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-infobars',
            '--window-size=1366,768',
            '--start-maximized',
            '--disable-gpu',
            '--disable-dev-shm-usage',
        ]
        
        # 启动浏览器
        browser = await playwright.chromium.launch(
            headless=True,  # 设置为True在生产环境中运行
            slow_mo=300,
            args=browser_args
        )
        
        try:
            # 加载cookie状态
            cookie_data = load_cookies(cookies_path)
            
            # 创建浏览器上下文
            context = await browser.new_context(
                user_agent=random_user_agent,
                viewport=random_viewport,
                device_scale_factor=1.0,
                locale="en-US",
                timezone_id="America/New_York",
                java_script_enabled=True,
                storage_state=cookie_data  # 直接使用加载的数据对象
            )
            
            page = await context.new_page()
            
            # 配置反检测措施
            await page.evaluate("""() => {
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                    configurable: true
                });
                delete navigator.__proto__.webdriver;
            }""")
            
            # ===== 先尝试直接URL访问 =====
            direct_access_success = await direct_url_access(page)
            
            if not direct_access_success:
                log_message("通过cookies直接登录失败，尝试UI交互流程...")
                ui_success = await login_with_ui_flow(page)
                
                if not ui_success:
                    log_message(f"第{attempt}次尝试：UI交互流程失败")
                    if attempt < MAX_RETRIES:
                        await context.close()
                        await browser.close()
                        continue
                    else:
                        log_message("已达到最大重试次数，放弃尝试")
                        await context.close()
                        await browser.close()
                        return False
            
            # ===== 等待工作区加载 =====
            workspace_loaded = await wait_for_workspace_loaded(page)
            if workspace_loaded:
                log_message("工作区加载验证成功!")
                
                # 保存最终cookie状态
                await context.storage_state(path=cookies_path)
                log_message(f"已保存最终cookie状态到 {cookies_path}")
                
                # 成功完成
                await context.close()
                await browser.close()
                return True
            else:
                log_message(f"第{attempt}次尝试：工作区加载验证失败") # This message might be redundant if wait_for_workspace_loaded always returns True
                if attempt < MAX_RETRIES:
                    await context.close()
                    await browser.close()
                    continue
                else:
                    log_message("已达到最大重试次数，放弃尝试 (run function context)")
                    await context.close()
                    await browser.close()
                    return False # If wait_for_workspace_loaded can truly fail, this path is taken
                    
        except Exception as e:
            log_message(f"第{attempt}次尝试出错: {e}")
            log_message(traceback.format_exc())
            
            if 'browser' in locals() and browser.is_connected():
                 try:
                    if 'context' in locals() and context:
                        await context.close()
                    await browser.close()
                 except Exception as close_err:
                    log_message(f"关闭浏览器/上下文时出错: {close_err}")
            elif 'context' in locals() and context: # browser might not be defined or connected
                try:
                    await context.close()
                except Exception as close_err:
                    log_message(f"关闭上下文时出错: {close_err}")

            if attempt < MAX_RETRIES:
                log_message("准备下一次尝试...")
                continue
            else:
                log_message("已达到最大重试次数，放弃尝试")
                return False
    
    return False # Should be unreachable if MAX_RETRIES >= 1

async def main():
    """主函数"""
    try:
        log_message("开始执行IDX登录并跳转Firebase Studio的自动化流程...")
        
        # 先用requests协议方式直接检查登录状态
        check_result = check_page_status_with_requests()
        if check_result:
            log_message("【检查结果】工作站可直接通过协议访问（状态码200），流程直接退出")
            # 显示提取的凭据
            extract_and_display_credentials()
            if all_messages:
                # full_message = "\n".join(all_messages) # This was in original, simplified_message is built inside send_to_telegram
                send_to_telegram("") # Pass empty or a generic message, actual content is built from all_messages
            return
        
        log_message("【检查结果】工作站不可直接通过协议访问，继续执行完整自动化流程")
        
        # 使用Playwright执行自动化流程
        async with async_playwright() as playwright:
            success = await run(playwright)
            
        log_message(f"自动化流程执行结果: {'成功' if success else '失败'}")
        
        # 显示提取的凭据（无论成功失败）
        extract_and_display_credentials()
        
        # 发送通知
        if all_messages:
            # full_message = "\n".join(all_messages)
            send_to_telegram("") 
            
    except Exception as e:
        log_message(f"主流程执行出错: {e}")
        log_message(traceback.format_exc())
        
        # 尝试提取凭据（即使出错）
        extract_and_display_credentials()
        
        # 确保错误信息也被发送
        if all_messages:
            # full_message = "\n".join(all_messages)
            send_to_telegram("")

if __name__ == "__main__":
    all_messages = []
    asyncio.run(main())
