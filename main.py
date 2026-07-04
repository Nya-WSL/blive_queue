import aiohttp
import asyncio
import traceback
import http.cookies

import blivedm.blivedm.models.web as web_models


from libs import log
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
    cookies["SESSDATA"] = SESSDATA
    cookies["SESSDATA"]["domain"] = "bilibili.com"

    global session
    session = aiohttp.ClientSession()
    session.cookie_jar.update_cookies(cookies)


async def run_client():
    room_id = ""
    client = blivedm.BLiveClient(room_id, session=session)
    handler = BiliHandler()
    client.set_handler(handler)
    client.start()

    try:
        await client.join()
    finally:
        await client.stop_and_close()


class BiliHandler(blivedm.BaseHandler):
    def _on_heartbeat(
        self, client: blivedm.BLiveClient, message: web_models.HeartbeatMessage
    ):
        print(f"[{client.room_id}] 心跳")

    def _on_danmaku(
        self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage
    ):
        print(f"[{client.room_id}] {message.uname}: {message.msg}")


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
            window_size=(300, 400),
            reconnect_timeout=30,
            language="zh-CN",
            use_colors=False,
        )  # pyright: ignore[reportArgumentType]
    except Exception:
        logger.error(f"run error: {traceback.format_exc()}")
