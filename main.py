import os
import re
import json
import aiohttp
import asyncio
import traceback
import http.cookies

import blivedm.blivedm.models.web as web_models


from libs import log
from libs import api
from libs import config as Config
from libs import check_runtime

from nicegui import ui, app
from typing import Optional
from blivedm import blivedm
from multiprocessing import freeze_support

version = "1.0.0"
logger = log.logger
logger.debug("version: {}", version)

# 初始化NiceGUI
app.storage.general.indent = True  # 格式化storage # type: ignore
app.add_static_files("/static", "static")  # 创建虚拟路径

base_config = Config.Config()
base_config.sync_config(base_config.load(), base_config.default_data)
config = base_config.load()

host = config["general"]["host"]  # type: ignore[index]
port = config["general"]["port"]  # type: ignore[index]
queue_file = config["str"]["queue_file"]  # type: ignore[index]

header = f"排队请扣{'、'.join(config['str']['queue_keyword'])}\n"

if not os.path.exists(queue_file):
    with open(queue_file, "w", encoding="utf-8") as f:
        f.write(header)
else:
    with open(queue_file, "r", encoding="utf-8") as f:
        queue_content = f.readlines()

    queue_content[0] = header

    with open(queue_file, "w", encoding="utf-8") as f:
        f.writelines(queue_content)

# 删除旧的二维码图片
for file in os.listdir(os.getcwd()):
    if re.match(r"bili_qrcode_\d+\.png", file):
        try:
            os.remove(file)
        except:
            pass

SESSDATA = ""

session: Optional[aiohttp.ClientSession] = None
client = None
_client_task: Optional[asyncio.Task] = None
_pending_refresh = False


async def start_handler():
    global client, _client_task
    init_session()
    try:
        await run_client()
    finally:
        await session.close()
        client = None
        _client_task = None


def init_session():
    cookies = http.cookies.SimpleCookie()
    cookies["SESSDATA"] = base_config.get("cookies", "SESSDATA", SESSDATA)
    cookies["SESSDATA"]["domain"] = "bilibili.com"

    global session
    session = aiohttp.ClientSession()
    session.cookie_jar.update_cookies(cookies)


async def run_client():
    global client
    room_id = base_config.get("general", "room_id", 3)
    _client = blivedm.BLiveClient(room_id, session=session)
    client = _client
    handler = BiliHandler()
    _client.set_handler(handler)
    _client.start()

    try:
        await _client.join()
    finally:
        await _client.stop_and_close()


def append_queue(uname: str):
    """
    将用户名追加到队列文件末尾，并刷新页面显示

    若用户名已存在于队列中则不重复添加，写入文件后发送通知
    并尝试刷新 user_card 以实时更新列表展示

    Args:
        uname (str): 待加入队列的用户名

    Raises:
        无显式异常抛出；页面刷新失败时异常会被静默捕获
    """
    with open(queue_file, "r", encoding="utf-8") as f:
        queues = [line.strip("\n") for line in f.readlines()]

    if uname not in queues:
        queues.append(uname)

    with open(queue_file, "w", encoding="utf-8") as f:
        f.writelines(q + "\n" for q in queues)

    with main_card:
        ui.notify(f"{uname} 已加入队列: {len(queues) - 1}", type="positive")

    # 标记待刷新，由 check_sort_update 在非拖拽状态下统一刷新，避免拖拽中销毁 DOM
    global _pending_refresh
    _pending_refresh = True


def delete_queue(index):
    """
    从队列文件中删除指定索引的用户并写回文件

    Args:
        index (int): 要删除的用户在队列中的行索引

    Returns:
        None
    """
    with open(queue_file, "r", encoding="utf-8") as f:
        queues = [line.strip("\n") for line in f.readlines()]

    uname = queues.pop(index)

    with open(queue_file, "w", encoding="utf-8") as f:
        f.writelines(q + "\n" for q in queues)

    with main_card:
        ui.notify(f"已从队列移除 {uname}")


def cancel_queue(uname: str):
    """
    从队列文件中删除指定用户名的用户并触发界面刷新

    若用户不存在于队列中则不做任何操作

    Args:
        uname (str): 要取消排队的用户名
    """
    with open(queue_file, "r", encoding="utf-8") as f:
        queues = [line.strip("\n") for line in f.readlines()]

    if uname in queues:
        queues.remove(uname)

        with open(queue_file, "w", encoding="utf-8") as f:
            f.writelines(q + "\n" for q in queues)

        with main_card:
            ui.notify(f"{uname} 已取消排队")

        global _pending_refresh
        _pending_refresh = True


def update_queue(new_order):
    """根据新的用户顺序重新排列队列文件，并持久化写入文件

    Args:
        new_order (list[str]): 拖拽排序后的用户名列表（按新顺序排列）

    Returns:
        None
    """
    with open(queue_file, "r", encoding="utf-8") as f:
        queues = [line.strip("\n") for line in f.readlines()]

    header = queues[0]
    # 按 new_order 中的用户名顺序重建
    reordered = [header] + new_order

    with open(queue_file, "w", encoding="utf-8") as f:
        f.writelines(q + "\n" for q in reordered)

    # with main_card:
    #     ui.notify("队列顺序已更新", type="positive")


def check_sessdata() -> bool:
    """检查 SESSDATA 是否已配置

    Returns:
        bool: SESSDATA 存在且非空时返回 True，否则返回 False
    """
    if not base_config.get("cookies", "SESSDATA", SESSDATA):
        return False
    return True


def login_page():
    def check_auth(loginInfo):
        status = api.login(loginInfo[0])

        if status == True:
            try:
                os.remove(loginInfo[1])
            except:
                pass

            ui.navigate.reload()  # 成功登录后刷新页面
        else:
            ui.notify(status, type="negative")

    loginInfo = api.get_qrcode("bili_qrcode")

    with main_card:
        qrcode_ui = ui.image(loginInfo[1])
        ui.label("请使用B站APP扫描二维码")

        with ui.row():
            ui.button("已扫码", on_click=lambda: check_auth(loginInfo))
            ui.button(
                "重新获取",
                on_click=lambda: (
                    qrcode_ui.set_source(api.get_qrcode("bili_qrcode")[1]),
                    ui.notify("已刷新二维码"),
                ),
            )


def user_page():
    def del_and_refresh(i):
        delete_queue(i + 1)
        user_card.clear()
        user_page()

    with user_card:
        with open(queue_file, "r", encoding="utf-8") as f:
            queues = [line.strip("\n") for line in f.readlines()]
        queues.pop(0)
        for idx, uname in enumerate(queues):
            row = ui.row().classes("items-center gap-2")
            row.props(f'data-queue-index="{idx}" data-queue-uname="{uname}"')
            with row:
                ui.icon("drag_indicator").classes(
                    "handle cursor-grab active:cursor-grabbing"
                )
                ui.label(uname)
                ui.space()
                ui.button(
                    icon="delete", on_click=lambda i=idx: del_and_refresh(i)
                ).props("flat round dense")


class BiliHandler(blivedm.BaseHandler):
    async def _on_heartbeat(
        self, client: blivedm.BLiveClient, message: web_models.HeartbeatMessage
    ):
        logger.debug(f"[{client.room_id}] 心跳")

    async def _on_danmaku(
        self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage
    ):
        uname = message.uname
        msg = message.msg

        for i in base_config.get("str", "cancel_keyword", ["取消排队"]):
            if msg == i:
                cancel_queue(uname)
                logger.info(f"[{client.room_id}] {uname}: {msg} 取消排队")
                break

        for i in base_config.get("str", "queue_keyword", ["排队"]):
            if msg == i:
                append_queue(uname)
                logger.info(f"[{client.room_id}] {uname}: {msg} 触发排队")
                break

    async def _on_gift(
        self, client: blivedm.BLiveClient, message: web_models.GiftMessage
    ):
        pass

    async def _on_user_toast_v2(
        self, client: blivedm.BLiveClient, message: web_models.UserToastV2Message
    ):
        pass

    async def _on_super_chat(
        self, client: blivedm.BLiveClient, message: web_models.SuperChatMessage
    ):
        uname = message.uname
        msg = message.message

        for i in base_config.get("str", "cancel_keyword", ["取消排队"]):
            if msg == i:
                cancel_queue(uname)
                logger.info(f"[{client.room_id}][SC] {uname}: {msg} 取消排队")
                break

        for i in base_config.get("str", "queue_keyword", ["排队"]):
            if msg == i:
                append_queue(uname)
                logger.info(f"[{client.room_id}][SC] {uname}: {msg} 触发排队")
                break

    async def _on_interact_word_v2(
        self, client: blivedm.BLiveClient, message: web_models.InteractWordV2Message
    ):
        pass


@ui.page("/")
def _():
    global main_card, user_card
    with (
        ui.card(align_items="center")
        .classes("absolute-center")
        .style("width: 95%") as main_card
    ):
        if not check_sessdata():
            login_page()
        else:
            with ui.card(align_items="center").classes(
                "w-2/3 queue-sortable"
            ) as user_card:
                user_page()
            user_card.make_sortable(handle=".handle")

            # 检测拖拽排序：拖拽中跳过，松手后读取 DOM 顺序写入 queue_file
            _prev_order = None

            async def check_sort_update():
                nonlocal _prev_order
                global _pending_refresh
                # 优先处理待刷新（即使 DOM 为空也要刷）
                if _pending_refresh:
                    _pending_refresh = False
                    try:
                        user_card.clear()
                        user_page()
                        user_card.make_sortable(handle=".handle")
                    except Exception:
                        pass
                    _prev_order = None  # DOM 已重建，上次顺序失效
                    return
                result = await ui.run_javascript("""
                    if (document.querySelector('.sortable-drag, .sortable-ghost, .sortable-chosen'))
                        return '__DRAGGING__';
                    const items = document.querySelectorAll('[data-queue-uname]');
                    if (!items.length) return null;
                    return JSON.stringify(Array.from(items).map(item =>
                        item.getAttribute('data-queue-uname')
                    ));
                """)
                if result is None or result == "__DRAGGING__":
                    return
                new_order = json.loads(result)
                order_str = json.dumps(new_order, sort_keys=True)
                if _prev_order is not None and order_str != _prev_order:
                    if new_order:
                        update_queue(new_order)
                _prev_order = order_str

            ui.timer(1.5, check_sort_update)

            config = base_config.load()

            room_id_input = ui.input(
                "房间号", on_change=lambda: base_config.save(config)
            ).style("width: 120px")
            room_id_input.bind_value(
                config["general"], "room_id"
            )  # 实时写入房间号到配置文件

            danmaku_switch = ui.switch("连接至弹幕服务器")

            async def toggle_connection(e):
                global client, _client_task
                if e.value:
                    # 打开连接
                    room_id = config["general"].get("room_id", "")
                    if not room_id or not str(room_id).strip():
                        ui.notify("请先填写房间号", type="warning")
                        danmaku_switch.set_value(False)
                        return
                    if _client_task and not _client_task.done():
                        ui.notify("弹幕服务器已连接", type="warning")
                        return
                    _client_task = asyncio.create_task(start_handler())
                    logger.info("已连接至弹幕服务器")
                else:
                    # 关闭连接
                    if _client_task and not _client_task.done():
                        if client:
                            client.stop()
                        _client_task = None
                        client = None
                    with main_card:
                        ui.notify("已断开弹幕服务器", type="warning")
                        logger.info("已断开弹幕服务器")

            danmaku_switch.on_value_change(toggle_connection)


if __name__ == "__main__":
    try:
        freeze_support()
        logger.info("正在检查Edge WebView2 runtime...")
        asyncio.run(check_runtime.check_runtime())  # 检查Edge WebView2 runtime

        ui.run(
            host=host,
            port=port,
            title=f"blive_queue | {version}",
            favicon="static/logo.ico",
            reload=False,
            show=False,
            native=True,
            window_size=(400, 700),
            reconnect_timeout=30,
            language="zh-CN",
            use_colors=False,
        )  # pyright: ignore[reportArgumentType]
    except Exception:
        logger.error(f"run error: {traceback.format_exc()}")
