import os
import tomlkit
from pathlib import Path

default_data = '''[general]
room_id = "" # 房间号
host = "127.0.0.1" # 监听地址
port = 65000 # 监听端口

[bool]
check_update = true # 是否启用更新检查
check_sha256 = true # 是否启用更新包SHA256校验

[str]
queue_keyword = ["1", "排队"] # 弹幕关键字
cancel_keyword = ["取消排队"] # 取消排队关键字
queue_file = "queue.txt" # 队列文件路径
queue_separator = ", " # 队列文件分隔符
queue_limit = 5 # 队列上限（0 表示不限制）

[cookies]
SESSDATA = "" # B站SESSDATA
'''

class Config:
    def __init__(self) -> None:
        self.file = Path("config.toml")
        self.default_data = default_data

        self.visited = set()  # 用于检测循环引用
        if not os.path.exists(self.file):
            self.default()

    def default(self):
        "初始化配置文件"
        with open("config.toml", "w+", encoding="utf-8") as f:
            tomlkit.dump(tomlkit.parse(self.default_data), f)

    def load(self):
        "加载配置文件"
        with open(self.file, "r", encoding="utf-8") as f:
            config = tomlkit.load(f)
        return config

    def save(self, data):
        "保存配置文件"
        with open("config.toml", "w+", encoding="utf-8") as f:
            if isinstance(data, tomlkit.TOMLDocument):
                tomlkit.dump(data, f)
            else:
                tomlkit.dump(tomlkit.parse(data), f)

    def get(self, table, value, default=None):
        """
        使用dict.get()获取配置文件中的值，不支持嵌套table

        params:
            table: 配置文件的table，如果为None则视为隐式table
            value: 配置文件中的值
            default: 值不存在时的默认值
        """
        data = self.load()

        if table is None:
            return data.get(value, default)
        else:
            return data.get(table, {}).get(value, default)

    def sync_config(self, config, example_config):
        "检查配置文件是否有缺失或多余项"
        example_config = tomlkit.parse(self.default_data)
        config = self.load()

        for example_table, example_data in example_config.items():
            if example_table == "cookies":
                continue  # 跳过 cookies 表，保留用户配置不变
            if example_table not in config:
                # 如果键不存在，直接复制默认值
                config[example_table] = example_data

            for example_key, example_value in example_data.items():
                if example_key not in config[example_table]:
                    # 如果子键不存在,直接复制默认值
                    config[example_table][example_key] = example_value  # type: ignore[index]
                else:
                    # 检查配置文件缺失项
                    diff = example_data.keys() - config[example_table].keys()  # type: ignore[attr-defined]

                    for key in diff:
                        config[example_table][key] = example_config[example_table][key]  # type: ignore[index]

                    # 检查配置文件多余项
                    diff = config[example_table].keys() - example_data.keys()  # type: ignore[attr-defined]

                    for key in diff:
                        config[example_table].pop(key, None)  # type: ignore[attr-defined]

        self.save(config)