import requests
import qrcode
import time

from . import log
from . import config as Config

logger = log.logger

base_config = Config.Config()


class BiliPollError(Exception):
    """
    B站Web端扫码登录错误

    :param info: 扫码接口返回值
    """

    def __init__(self, info):
        self.info = info
        message = "扫码出现错误：" + info["data"]["message"]
        super().__init__(message)


def get_qrcode(path):
    """
    获取B站Web端扫码登录二维码

    :param path: 二维码保存路径，格式为: "path_时间戳.png"，例: "bili_qrcode_1743233445.png"
    :return: (扫码登录秘钥, 保存路径)
    """
    try:
        loginInfo = requests.get(
            url="https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
            headers={
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            },
        ).json()

        # 生成二维码
        img = qrcode.make(loginInfo["data"]["url"])
        save_path = f"{path}_{int(time.time())}.png"
        img.save(save_path)
        return loginInfo["data"]["qrcode_key"], save_path
    except Exception as e:
        logger.error(e)


def get_buvid3():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/149.0"
    }

    response = requests.get(
        url="https://api.bilibili.com/x/web-frontend/getbuvid", headers=headers
    )

    if response.status_code == 200:
        data = response.json()
        if data["code"] == 0:
            buvid3 = data["data"]["buvid"]
            return buvid3
        else:
            logger.error(f"获取buvid3失败，错误信息：{data['code']} {data['message']}")
    else:
        logger.error(f"获取buvid3失败，HTTP状态码：{response.status_code}")

    return False


def get_uname(mid):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/149.0"
    }

    params = {"mid": mid}

    response = requests.get(
        url="https://api.bilibili.com/x/web-interface/card",
        headers=headers,
        params=params,
    )

    if response.status_code == 200:
        data = response.json()
        if data["code"] == 0:
            uname = data["data"]["card"]["name"]
            return uname
        else:
            logger.error(
                f"获取用户昵称失败，错误信息：{data['code']} {data['message']}"
            )
    else:
        logger.error(f"获取用户昵称失败，HTTP状态码：{response.status_code}")

    return False


def login(loginInfo):
    buvid3 = get_buvid3()

    if not buvid3:
        logger.error("获取buvid3失败，无法登录")
        return False

    sess = requests.Session()
    sess.headers.update({
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    })

    response = sess.get(
        url="https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
        params={"qrcode_key": loginInfo},
    )

    pollInfo = response.json()

    if pollInfo["data"]["code"] != 0:
        return BiliPollError(pollInfo)

    # 跟进 data.url 获取 SESSDATA
    url = pollInfo["data"]["url"]
    sess.get(url, allow_redirects=True)

    cookies = requests.utils.dict_from_cookiejar(sess.cookies)

    if buvid3:
        cookies["buvid3"] = buvid3
    else:
        logger.warning("未能获取buvid3，cookie中将不包含buvid3字段")

    config = base_config.load()
    config["cookies"] = cookies
    base_config.save(config)

    logger.info(f"登录成功，已写入 SESSDATA={cookies.get('SESSDATA', '???' )[:20]}...")

    return True
