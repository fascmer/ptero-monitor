#!/usr/bin/env python3
"""
翼龙面板服务器监控保活工具
Pterodactyl Panel Server Monitor & Auto-Restart
"""

import os
import json
import asyncio
import sqlite3
import time
import logging
import base64
import hashlib
from datetime import datetime
from aiohttp import web
from typing import Dict, Optional
from curl_cffi.requests import AsyncSession

# 配置
PORT = int(os.environ.get('PORT', 8000))
DB_PATH = os.environ.get('DB_PATH', 'monitor.db')

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 全局监控任务存储
monitor_tasks: Dict[int, asyncio.Task] = {}

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            api_url TEXT NOT NULL,
            api_key TEXT NOT NULL,
            server_id TEXT NOT NULL,
            interval INTEGER DEFAULT 10,
            enabled INTEGER DEFAULT 1,
            last_status TEXT DEFAULT 'unknown',
            last_check TEXT,
            restart_count INTEGER DEFAULT 0,
            proxy_url TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 尝试添加 proxy_url 字段（如果表已存在）
    try:
        c.execute('ALTER TABLE servers ADD COLUMN proxy_url TEXT DEFAULT ""')
    except:
        pass
    c.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER,
            action TEXT,
            status TEXT,
            message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (server_id) REFERENCES servers(id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_setting(key: str, default: str = None) -> str:
    """获取设置"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = c.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key: str, value: str):
    """保存设置"""
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def parse_server_url(full_url: str) -> tuple:
    """从完整URL解析出base_url和server_id
    例如: https://cp.host2play.gratis/api/client/servers/c271ea0c-85dd-49c2-b5c7-154c608f6f49
    返回: (base_url, server_id)
    """
    full_url = full_url.rstrip('/')
    # 找到 /api/client/servers/ 后面的部分作为 server_id
    if '/api/client/servers/' in full_url:
        parts = full_url.split('/api/client/servers/')
        base_url = parts[0] + '/api/client/servers'
        server_id = parts[1].split('/')[0]  # 取第一段作为server_id
        return base_url, server_id
    else:
        # 尝试取最后一段作为 server_id
        parts = full_url.rsplit('/', 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return full_url, ''

async def fetch_server_status(api_url: str, api_key: str, server_id: str = None, proxy_url: str = None) -> dict:
    """获取服务器状态"""
    # 如果 server_id 为空或为 '-'，从 api_url 解析
    if not server_id or server_id == '-':
        base_url, server_id = parse_server_url(api_url)
    else:
        base_url = api_url.rstrip('/')
        if '{SERVER_ID}' in base_url:
            base_url = base_url.replace('{SERVER_ID}', server_id)
        elif not base_url.endswith(server_id):
            base_url = f"{base_url}/{server_id}" if not base_url.endswith('/') else f"{base_url}{server_id}"
    
    resources_url = f"{base_url}/{server_id}/resources"
    proxy = proxy_url.strip() if proxy_url else None
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    try:
        async with AsyncSession(impersonate="chrome", proxy=proxy, timeout=15) as session:
            resp = await session.get(resources_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    'success': True,
                    'status': data.get('attributes', {}).get('current_state', 'unknown'),
                    'resources': data.get('attributes', {})
                }
            else:
                text = resp.text
                return {'success': False, 'error': f'HTTP {resp.status_code}: {text[:200]}'}
    except asyncio.TimeoutError:
        return {'success': False, 'error': 'Request timeout'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

async def send_power_action(api_url: str, api_key: str, server_id: str, action: str, proxy_url: str = None) -> dict:
    """发送电源操作"""
    # 如果 server_id 为空或为 '-'，从 api_url 解析
    if not server_id or server_id == '-':
        base_url, server_id = parse_server_url(api_url)
    else:
        base_url = api_url.rstrip('/')
        if '{SERVER_ID}' in base_url:
            base_url = base_url.replace('{SERVER_ID}', server_id)
        elif not base_url.endswith(server_id):
            base_url = f"{base_url}/{server_id}" if not base_url.endswith('/') else f"{base_url}{server_id}"
    
    power_url = f"{base_url}/{server_id}/power"
    proxy = proxy_url.strip() if proxy_url else None
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    try:
        async with AsyncSession(impersonate="chrome", proxy=proxy, timeout=15) as session:
            resp = await session.post(power_url, headers=headers, json={'signal': action})
            if resp.status_code in [200, 204]:
                return {'success': True}
            else:
                text = resp.text
                return {'success': False, 'error': f'HTTP {resp.status_code}: {text[:200]}'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def add_log(server_id: int, action: str, status: str, message: str):
    """添加日志"""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        'INSERT INTO logs (server_id, action, status, message) VALUES (?, ?, ?, ?)',
        (server_id, action, status, message)
    )
    conn.commit()
    conn.close()

async def monitor_server(server_id: int):
    """监控单个服务器的任务"""
    logger.info(f"Starting monitor for server {server_id}")
    
    while True:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute('SELECT * FROM servers WHERE id = ?', (server_id,))
            server = c.fetchone()
            conn.close()
            
            if not server or not server['enabled']:
                logger.info(f"Server {server_id} disabled or removed, stopping monitor")
                break
            
            # 获取代理配置
            proxy_url = server['proxy_url'] if 'proxy_url' in server.keys() else None
            
            # 获取状态
            result = await fetch_server_status(
                server['api_url'], 
                server['api_key'], 
                server['server_id'],
                proxy_url
            )
            
            now = datetime.now().isoformat()
            
            if result['success']:
                status = result['status']
                
                # 更新状态
                conn = get_db()
                c = conn.cursor()
                c.execute(
                    'UPDATE servers SET last_status = ?, last_check = ? WHERE id = ?',
                    (status, now, server_id)
                )
                conn.commit()
                conn.close()
                
                # 如果offline，自动重启
                if status == 'offline':
                    logger.warning(f"Server {server['name']} is offline, sending restart...")
                    add_log(server_id, 'detect', 'offline', 'Server detected offline')
                    
                    restart_result = await send_power_action(
                        server['api_url'],
                        server['api_key'],
                        server['server_id'],
                        'start',
                        proxy_url
                    )
                    
                    if restart_result['success']:
                        logger.info(f"Restart command sent for {server['name']}")
                        add_log(server_id, 'restart', 'success', 'Restart command sent')
                        
                        # 更新重启计数
                        conn = get_db()
                        c = conn.cursor()
                        c.execute(
                            'UPDATE servers SET restart_count = restart_count + 1 WHERE id = ?',
                            (server_id,)
                        )
                        conn.commit()
                        conn.close()
                    else:
                        logger.error(f"Failed to restart {server['name']}: {restart_result['error']}")
                        add_log(server_id, 'restart', 'failed', restart_result['error'])
            else:
                logger.error(f"Failed to get status for {server['name']}: {result['error']}")
                conn = get_db()
                c = conn.cursor()
                c.execute(
                    'UPDATE servers SET last_status = ?, last_check = ? WHERE id = ?',
                    ('error', now, server_id)
                )
                conn.commit()
                conn.close()
                add_log(server_id, 'check', 'error', result['error'])
            
            # 等待下次检查
            await asyncio.sleep(server['interval'])
            
        except asyncio.CancelledError:
            logger.info(f"Monitor for server {server_id} cancelled")
            break
        except Exception as e:
            logger.error(f"Monitor error for server {server_id}: {e}")
            await asyncio.sleep(10)

def start_monitor(server_id: int):
    """启动服务器监控"""
    if server_id in monitor_tasks:
        monitor_tasks[server_id].cancel()
    
    task = asyncio.create_task(monitor_server(server_id))
    monitor_tasks[server_id] = task

def stop_monitor(server_id: int):
    """停止服务器监控"""
    if server_id in monitor_tasks:
        monitor_tasks[server_id].cancel()
        del monitor_tasks[server_id]

# ============ 认证相关 ============

def hash_password(password: str) -> str:
    """对密码进行哈希"""
    return hashlib.sha256(password.encode()).hexdigest()

def check_auth(username: str, password: str) -> bool:
    """检查认证"""
    stored_user = get_setting('auth_username')
    stored_pass = get_setting('auth_password')
    
    if not stored_user or not stored_pass:
        return True  # 未设置认证，允许访问
    
    return username == stored_user and hash_password(password) == stored_pass

def is_auth_enabled() -> bool:
    """检查是否启用了认证"""
    return bool(get_setting('auth_username')) and bool(get_setting('auth_password'))

@web.middleware
async def auth_middleware(request, handler):
    """认证中间件"""
    # 登录页面和登录API不需要认证
    if request.path in ['/login', '/api/login', '/api/auth/status']:
        return await handler(request)
    
    # 静态文件中的登录页面
    if request.path.startswith('/static/') and 'login' in request.path:
        return await handler(request)
    
    # 检查是否启用认证
    if not is_auth_enabled():
        return await handler(request)
    
    # 检查 session cookie
    session_token = request.cookies.get('session')
    valid_token = get_setting('session_token')
    
    if session_token and valid_token and session_token == valid_token:
        return await handler(request)
    
    # 检查 Basic Auth
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Basic '):
        try:
            credentials = base64.b64decode(auth_header[6:]).decode('utf-8')
            username, password = credentials.split(':', 1)
            if check_auth(username, password):
                return await handler(request)
        except:
            pass
    
    # 如果是页面请求，重定向到登录页
    if request.path == '/' or not request.path.startswith('/api/'):
        raise web.HTTPFound('/login')
    
    # API请求返回401
    return web.json_response({'success': False, 'error': '未授权，请登录'}, status=401)

# ============ Web API Routes ============

async def index(request):
    """首页"""
    return web.FileResponse('static/index.html')

async def login_page(request):
    """登录页面"""
    return web.FileResponse('static/login.html')

async def api_servers_list(request):
    """获取服务器列表"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM servers ORDER BY id DESC')
    servers = [dict(row) for row in c.fetchall()]
    conn.close()
    
    # 添加监控状态
    for s in servers:
        s['monitoring'] = s['id'] in monitor_tasks
    
    return web.json_response({'success': True, 'servers': servers})

async def api_server_add(request):
    """添加服务器"""
    try:
        data = await request.json()
        name = data.get('name', '').strip()
        api_url = data.get('api_url', '').strip()
        api_key = data.get('api_key', '').strip()
        server_id = data.get('server_id', '-').strip() or '-'  # 可以为空，从 URL 解析
        interval = int(data.get('interval', 10))
        proxy_url = data.get('proxy_url', '').strip()
        
        if not all([name, api_url, api_key]):
            return web.json_response({'success': False, 'error': '名称、API地址和API Key是必填的'})
        
        if interval < 5:
            interval = 5
        
        conn = get_db()
        c = conn.cursor()
        c.execute(
            'INSERT INTO servers (name, api_url, api_key, server_id, interval, proxy_url) VALUES (?, ?, ?, ?, ?, ?)',
            (name, api_url, api_key, server_id, interval, proxy_url)
        )
        new_id = c.lastrowid
        conn.commit()
        conn.close()
        
        # 自动启动监控
        start_monitor(new_id)
        
        return web.json_response({'success': True, 'id': new_id})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def api_server_delete(request):
    """删除服务器"""
    try:
        server_id = int(request.match_info['id'])
        
        # 停止监控
        stop_monitor(server_id)
        
        conn = get_db()
        c = conn.cursor()
        c.execute('DELETE FROM logs WHERE server_id = ?', (server_id,))
        c.execute('DELETE FROM servers WHERE id = ?', (server_id,))
        conn.commit()
        conn.close()
        
        return web.json_response({'success': True})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def api_server_toggle(request):
    """切换服务器监控状态"""
    try:
        server_id = int(request.match_info['id'])
        
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT enabled FROM servers WHERE id = ?', (server_id,))
        row = c.fetchone()
        
        if not row:
            return web.json_response({'success': False, 'error': '服务器不存在'})
        
        new_enabled = 0 if row['enabled'] else 1
        c.execute('UPDATE servers SET enabled = ? WHERE id = ?', (new_enabled, server_id))
        conn.commit()
        conn.close()
        
        if new_enabled:
            start_monitor(server_id)
        else:
            stop_monitor(server_id)
        
        return web.json_response({'success': True, 'enabled': bool(new_enabled)})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def api_server_update(request):
    """更新服务器配置"""
    try:
        server_id = int(request.match_info['id'])
        data = await request.json()
        
        conn = get_db()
        c = conn.cursor()
        
        updates = []
        params = []
        
        if 'name' in data:
            updates.append('name = ?')
            params.append(data['name'])
        if 'api_url' in data:
            updates.append('api_url = ?')
            params.append(data['api_url'])
        if 'api_key' in data:
            updates.append('api_key = ?')
            params.append(data['api_key'])
        if 'server_id' in data:
            updates.append('server_id = ?')
            params.append(data['server_id'])
        if 'interval' in data:
            interval = max(5, int(data['interval']))
            updates.append('interval = ?')
            params.append(interval)
        if 'proxy_url' in data:
            updates.append('proxy_url = ?')
            params.append(data['proxy_url'])
        
        if updates:
            params.append(server_id)
            c.execute(f"UPDATE servers SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            
            # 重启监控以应用新配置
            c.execute('SELECT enabled FROM servers WHERE id = ?', (server_id,))
            row = c.fetchone()
            if row and row['enabled']:
                start_monitor(server_id)
        
        conn.close()
        return web.json_response({'success': True})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def api_server_restart(request):
    """手动重启服务器"""
    try:
        server_id = int(request.match_info['id'])
        
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM servers WHERE id = ?', (server_id,))
        server = c.fetchone()
        conn.close()
        
        if not server:
            return web.json_response({'success': False, 'error': '服务器不存在'})
        
        proxy_url = server['proxy_url'] if 'proxy_url' in server.keys() else None
        result = await send_power_action(
            server['api_url'],
            server['api_key'],
            server['server_id'],
            'restart',
            proxy_url
        )
        
        if result['success']:
            add_log(server_id, 'manual_restart', 'success', 'Manual restart command sent')
        else:
            add_log(server_id, 'manual_restart', 'failed', result['error'])
        
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def api_server_power(request):
    """服务器电源操作"""
    try:
        server_id = int(request.match_info['id'])
        data = await request.json()
        action = data.get('action', 'start')
        
        if action not in ['start', 'stop', 'restart', 'kill']:
            return web.json_response({'success': False, 'error': '无效的操作'})
        
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM servers WHERE id = ?', (server_id,))
        server = c.fetchone()
        conn.close()
        
        if not server:
            return web.json_response({'success': False, 'error': '服务器不存在'})
        
        proxy_url = server['proxy_url'] if 'proxy_url' in server.keys() else None
        result = await send_power_action(
            server['api_url'],
            server['api_key'],
            server['server_id'],
            action,
            proxy_url
        )
        
        if result['success']:
            add_log(server_id, f'power_{action}', 'success', f'Power {action} command sent')
        else:
            add_log(server_id, f'power_{action}', 'failed', result['error'])
        
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def api_server_logs(request):
    """获取服务器日志"""
    try:
        server_id = int(request.match_info['id'])
        limit = int(request.query.get('limit', 50))
        
        conn = get_db()
        c = conn.cursor()
        c.execute(
            'SELECT * FROM logs WHERE server_id = ? ORDER BY id DESC LIMIT ?',
            (server_id, limit)
        )
        logs = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return web.json_response({'success': True, 'logs': logs})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def api_server_status(request):
    """实时获取服务器状态"""
    try:
        server_id = int(request.match_info['id'])
        
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM servers WHERE id = ?', (server_id,))
        server = c.fetchone()
        conn.close()
        
        if not server:
            return web.json_response({'success': False, 'error': '服务器不存在'})
        
        proxy_url = server['proxy_url'] if 'proxy_url' in server.keys() else None
        result = await fetch_server_status(
            server['api_url'],
            server['api_key'],
            server['server_id'],
            proxy_url
        )
        
        return web.json_response(result)
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def api_all_logs(request):
    """获取所有日志"""
    try:
        limit = int(request.query.get('limit', 100))
        
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            SELECT l.*, s.name as server_name 
            FROM logs l 
            JOIN servers s ON l.server_id = s.id 
            ORDER BY l.id DESC LIMIT ?
        ''', (limit,))
        logs = [dict(row) for row in c.fetchall()]
        conn.close()
        
        return web.json_response({'success': True, 'logs': logs})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def api_auth_status(request):
    """获取认证状态"""
    return web.json_response({
        'success': True,
        'auth_enabled': is_auth_enabled(),
        'has_username': bool(get_setting('auth_username'))
    })

async def api_login(request):
    """登录"""
    try:
        data = await request.json()
        username = data.get('username', '')
        password = data.get('password', '')
        
        if check_auth(username, password):
            # 生成 session token
            import secrets
            token = secrets.token_hex(32)
            set_setting('session_token', token)
            
            response = web.json_response({'success': True})
            response.set_cookie('session', token, max_age=86400*7, httponly=True)
            return response
        else:
            return web.json_response({'success': False, 'error': '用户名或密码错误'})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def api_logout(request):
    """登出"""
    set_setting('session_token', '')
    response = web.json_response({'success': True})
    response.del_cookie('session')
    return response

async def api_set_auth(request):
    """设置认证"""
    try:
        data = await request.json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if username and password:
            set_setting('auth_username', username)
            set_setting('auth_password', hash_password(password))
            # 生成新的 session token
            import secrets
            token = secrets.token_hex(32)
            set_setting('session_token', token)
            
            response = web.json_response({'success': True, 'message': '认证已启用'})
            response.set_cookie('session', token, max_age=86400*7, httponly=True)
            return response
        elif not username and not password:
            # 清空认证
            set_setting('auth_username', '')
            set_setting('auth_password', '')
            set_setting('session_token', '')
            response = web.json_response({'success': True, 'message': '认证已禁用'})
            response.del_cookie('session')
            return response
        else:
            return web.json_response({'success': False, 'error': '用户名和密码必须同时设置或同时清空'})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

async def on_startup(app):
    """启动时恢复所有已启用的监控"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id FROM servers WHERE enabled = 1')
    servers = c.fetchall()
    conn.close()
    
    for server in servers:
        start_monitor(server['id'])
    
    logger.info(f"Started monitoring for {len(servers)} servers")

async def on_shutdown(app):
    """关闭时停止所有监控"""
    for task in monitor_tasks.values():
        task.cancel()
    logger.info("All monitors stopped")

def create_app():
    """创建应用"""
    app = web.Application(middlewares=[auth_middleware])
    
    # 路由
    app.router.add_get('/', index)
    app.router.add_get('/login', login_page)
    app.router.add_get('/api/servers', api_servers_list)
    app.router.add_post('/api/servers', api_server_add)
    app.router.add_delete('/api/servers/{id}', api_server_delete)
    app.router.add_post('/api/servers/{id}/toggle', api_server_toggle)
    app.router.add_put('/api/servers/{id}', api_server_update)
    app.router.add_post('/api/servers/{id}/restart', api_server_restart)
    app.router.add_post('/api/servers/{id}/power', api_server_power)
    app.router.add_get('/api/servers/{id}/logs', api_server_logs)
    app.router.add_get('/api/servers/{id}/status', api_server_status)
    app.router.add_get('/api/logs', api_all_logs)
    
    # 认证相关
    app.router.add_get('/api/auth/status', api_auth_status)
    app.router.add_post('/api/login', api_login)
    app.router.add_post('/api/logout', api_logout)
    app.router.add_post('/api/auth/set', api_set_auth)
    
    # 静态文件
    app.router.add_static('/static/', 'static')
    
    # 生命周期
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    return app

if __name__ == '__main__':
    init_db()
    app = create_app()
    logger.info(f"Starting Pterodactyl Monitor on port {PORT}")
    web.run_app(app, host='0.0.0.0', port=PORT)
