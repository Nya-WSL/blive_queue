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

if not os.path.exists(queue_file):
    with open(queue_file, "w", encoding="utf-8") as f:
        f.write(f"扣 {config['str']['queue_keyword']} 排队")

# 删除旧的二维码图片
for file in os.listdir(os.getcwd()):
    if re.match(r"bili_qrcode_\d+\.png", file):
        try:
            os.remove(file)
        except:
            pass

SESSDATA = ""

session: Optional[aiohttp.ClientSession] = None


async def start_handler():
    init_session()
    try:
        await run_client()
    finally:
        await session.close()


def init_session():
    cookies = http.cookies.SimpleCookie()
    cookies["SESSDATA"] = base_config.get("cookies", "SESSDATA", SESSDATA)
    cookies["SESSDATA"]["domain"] = "bilibili.com"

    global session
    session = aiohttp.ClientSession()
    session.cookie_jar.update_cookies(cookies)


async def run_client():
    room_id = base_config.get("general", "room_id", 3)
    client = blivedm.BLiveClient(room_id, session=session)
    handler = BiliHandler()
    client.set_handler(handler)
    client.start()

    try:
        await client.join()
    finally:
        await client.stop_and_close()


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
        queues = f.readlines()

    if uname not in queues:
        queues.append(uname)

    with open(queue_file, "w", encoding="utf-8") as f:
        f.writelines(queues)

    ui.notify(f"{uname} 已加入队列: {queues.index(uname) + 1}", type="positive")

    # 刷新 user_card 显示最新队列
    try:
        user_card.clear()
        user_page()
    except Exception:
        pass


def delete_queue(index):
    """
    从队列文件中删除指定索引的用户并写回文件

    Args:
        index (int): 要删除的用户在队列中的行索引

    Returns:
        None
    """
    with open(queue_file, "r", encoding="utf-8") as f:
        queues = f.readlines()

    uname = queues.pop(index)

    with open(queue_file, "w", encoding="utf-8") as f:
        f.writelines(queues)

    ui.notify(f"已从队列移除{uname}")


def update_queue(new_order):
    """根据新的顺序索引重新排列队列文件中的条目，并持久化写入文件

    Args:
        new_order (list[int]): 新的顺序索引列表，每个元素为原始队列中的位置索引，
            用于指定条目在新顺序中的排列位置

    Returns:
        None
    """
    with open(queue_file, "r", encoding="utf-8") as f:
        queues = f.readlines()

    header = queues[0]
    reordered = [header] + [queues[i + 1] for i in new_order]

    with open(queue_file, "w", encoding="utf-8") as f:
        f.writelines(reordered)

    ui.notify("队列顺序已更新", type="positive")


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
            ui.notify("登录成功", type="positive")

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
            queues = f.readlines()
        queues.pop(0)
        for idx, user in enumerate(queues):
            row = ui.row().classes("items-center gap-2")
            row.props(f'data-queue-index="{idx}"')
            with row:
                ui.icon("drag_indicator").classes("handle cursor-grab active:cursor-grabbing")
                ui.label(user.strip())
                ui.space()
                ui.button(icon="delete", on_click=lambda i=idx: del_and_refresh(i)).props(
                    "flat round dense"
                )


class BiliHandler(blivedm.BaseHandler):
    def _on_heartbeat(self, client: blivedm.BLiveClient):
        print(f"[{client.room_id}] 心跳")

    def _on_danmaku(
        self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage
    ):
        uname = message.uname
        msg = message.msg

        for i in config["str"]["queue_keyword"]:
            if re.search(i, msg):
                append_queue(uname)
                logger.info(f"[{client.room_id}] {uname}: {msg} 触发排队")
                break


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
            with ui.card(align_items="center").classes("w-2/3 queue-sortable") as user_card:
                user_page()
            user_card.make_sortable(handle=".handle")

            # 监听拖拽排序变化，更新 queue_file
            ui.run_javascript(
                """
                window._queueSortChanged = false;
                window._queueNewOrder = null;

                setTimeout(() => {
                    const container = document.querySelector('.queue-sortable');
                    if (!container) return;
                    const sortable = container.sortable || (window.Sortable && window.Sortable.get(container));
                    if (!sortable) return;

                    sortable.option('onEnd', function(evt) {
                        const items = [...evt.to.querySelectorAll('[data-queue-index]')];
                        window._queueNewOrder = items.map(item => parseInt(item.getAttribute('data-queue-index')));
                        window._queueSortChanged = true;
                    });
                }, 800);
            """
            )

            async def check_sort_update():
                result = await ui.run_javascript(
                    """
                    if (window._queueSortChanged) {
                        window._queueSortChanged = false;
                        return JSON.stringify(window._queueNewOrder);
                    }
                    return null;
                    """,
                    respond=True,
                )
                if result:
                    new_order = json.loads(result)
                    if new_order:
                        update_queue([int(i) for i in new_order])

            ui.timer(0.5, check_sort_update)

            room_id_input = ui.input(
                "房间号", on_change=lambda: base_config.save(config)
            ).style("width: 120px")
            room_id_input.bind_value(
                config["general"], "room_id"
            )  # 实时写入房间号到配置文件


if __name__ == "__main__":
    try:
        freeze_support()
        logger.info("正在检查Edge WebView2 runtime...")
        asyncio.run(check_runtime.check_runtime())  # 检查Edge WebView2 runtime

        ui.run(
            host=host,
            port=port,
            title=f"blive_queue | {version}",
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
