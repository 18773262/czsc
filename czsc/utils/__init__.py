# coding: utf-8
import os
import functools
import threading
import pandas as pd
from typing import List, Union
from loguru import logger

from . import qywx
from . import ta
from . import io
from . import echarts_plot

from .echarts_plot import kline_pro, trading_view_kline
from .corr import nmi_matrix, single_linear, cross_sectional_ic
from .bar_generator import BarGenerator, freq_end_time, resample_bars, format_standard_kline
from .bar_generator import is_trading_time, get_intraday_times, check_freq_and_market
from .io import dill_dump, dill_load, read_json, save_json
from .sig import check_gap_info, is_bis_down, is_bis_up, get_sub_elements, is_symmetry_zs
from .sig import same_dir_counts, fast_slow_cross, count_last_same, create_single_signal
from .plotly_plot import KlineChart
from .trade import update_nxb, update_bbars, update_tbars, risk_free_returns, resample_to_daily
from .cross import cross_sectional_ranker
from .stats import (
    daily_performance,
    subtract_fee,
    holds_performance,
    top_drawdowns,
    rolling_daily_performance,
    psi,
)
from .cache import home_path, get_dir_size, empty_cache_path, DiskCache, disk_cache, clear_cache, clear_expired_cache
from .index_composition import index_composition
from .data_client import DataClient, set_url_token, get_url_token
from .oss import AliyunOSS
from .events import overlap
from .fernet import generate_fernet_key, fernet_encrypt, fernet_decrypt


sorted_freqs = [
    "Tick",
    "1分钟",
    "2分钟",
    "3分钟",
    "4分钟",
    "5分钟",
    "6分钟",
    "10分钟",
    "12分钟",
    "15分钟",
    "20分钟",
    "30分钟",
    "60分钟",
    "120分钟",
    "日线",
    "周线",
    "月线",
    "季线",
    "年线",
]


def x_round(x: Union[float, int], digit: int = 4) -> Union[float, int]:
    """用去尾法截断小数

    :param x: 数字
    :param digit: 保留小数位数
    :return:
    """
    if isinstance(x, int):
        return x

    try:
        digit_ = pow(10, digit)
        x = int(x * digit_) / digit_
    except:
        print(f"x_round error: x = {x}")
    return x


def get_py_namespace(file_py: str, keys: list = []) -> dict:
    """获取 python 脚本文件中的 namespace

    :param file_py: python 脚本文件名
    :param keys: 指定需要的对象名称
    :return: namespace
    """
    text = open(file_py, "r", encoding="utf-8").read()
    code = compile(text, file_py, "exec")
    namespace = {"file_py": file_py, "file_name": os.path.basename(file_py).split(".")[0]}
    exec(code, namespace)
    if keys:
        namespace = {k: v for k, v in namespace.items() if k in keys}
    return namespace


def code_namespace(code: str, keys: list = []) -> dict:
    """获取 python 代码中的 namespace

    :param code: python 代码
    :param keys: 指定需要的对象名称
    :return: namespace
    """
    namespace = {"code": code}
    exec(code, namespace)
    if keys:
        namespace = {k: v for k, v in namespace.items() if k in keys}
    return namespace


def import_by_name(name):
    """通过字符串导入模块、类、函数

    函数执行逻辑：

    1. 检查 name 中是否包含点号（'.'）。如果没有，则直接使用内置的 import 函数来导入整个模块，并返回该模块对象。
    2. 如果 name 包含点号，先处理一个相对路径。将 name 拆分为两部分：module_name 和 function_name。
        使用 Python 内置的 rsplit 方法从右边开始分割，只取一次，这样可以确保我们将最后的一个点号前的部分作为 module_name，点号后面的部分作为 function_name。
    3. 使用import函数导入指定的 module_name。
        这里传入三个参数：globals() 和 locals() 分别代表当前全局和局部命名空间；
        [function_name] 是一个列表，用于指定要导入的子模块或属性名。
        这样做是为了避免一次性导入整个模块的所有内容，提高效率。
    4.  使用 vars 函数获取模块的字典表示形式（即模块内所有的变量和函数），取出 function_name 对应的值，然后返回这个值。

    :param name: 模块名，如：'czsc.objects.Factor'
    :return: 模块对象
    """
    if "." not in name:
        return __import__(name)

    # 从右边开始分割，分割成模块名和函数名
    module_name, function_name = name.rsplit(".", 1)
    module = __import__(module_name, globals(), locals(), [function_name])
    return vars(module)[function_name]


def freqs_sorted(freqs):
    """K线周期列表排序并去重，第一个元素是基础周期

    :param freqs: K线周期列表
    :return: K线周期排序列表
    """
    _freqs_new = [x for x in sorted_freqs if x in freqs]
    return _freqs_new


def create_grid_params(prefix: str = "", multiply=3, **kwargs) -> dict:
    """创建 grid search 参数组合

    :param prefix: 参数组前缀
    :param multiply: 参数组合的位数，如果为 0，则使用 # 分隔参数
    :param kwargs: 任意参数的候选序列，参数值推荐使用 iterable
    :return: 参数组合字典

    examples
    ============
    >>>x = create_grid_params("test", x=(1, 2), y=('a', 'b'), detail=True)
    >>>print(x)
    Out[0]:
        {'test_x=1_y=a': {'x': 1, 'y': 'a'},
         'test_x=1_y=b': {'x': 1, 'y': 'b'},
         'test_x=2_y=a': {'x': 2, 'y': 'a'},
         'test_x=2_y=b': {'x': 2, 'y': 'b'}}

    # 单个参数传入单个值也是可以的，但类型必须是 int, float, str 中的任一
    >>>x = create_grid_params("test", x=2, y=('a', 'b'), detail=False)
    >>>print(x)
    Out[1]:
        {'test001': {'x': 2, 'y': 'a'},
         'test002': {'x': 2, 'y': 'b'}}
    """
    from sklearn.model_selection import ParameterGrid

    params_grid = dict(kwargs)
    for k, v in params_grid.items():
        # 处理非 list 类型数据
        if type(v) in [int, float, str]:
            v = [v]
        assert type(v) in [tuple, list], f"输入参数值必须是 list 或 tuple 类型，当前参数 {k} 值：{v}"
        params_grid[k] = v

    params = {}
    for i, row in enumerate(ParameterGrid(params_grid), 1):
        if multiply == 0:
            key = "#".join([f"{k}={v}" for k, v in row.items()])
        else:
            key = str(i).zfill(multiply)

        row["version"] = f"{prefix}{key}"
        params[f"{prefix}@{key}"] = row
    return params


def print_df_sample(df, n=5):
    from tabulate import tabulate

    print(tabulate(df.head(n).values, headers=df.columns, tablefmt="rst"))


def mac_address():
    """获取本机 MAC 地址

    MAC地址（英语：Media Access Control Address），直译为媒体访问控制地址，也称为局域网地址（LAN Address），
    以太网地址（Ethernet Address）或物理地址（Physical Address），它是一个用来确认网络设备位置的地址。在OSI模
    型中，第三层网络层负责IP地址，第二层数据链接层则负责MAC地址。MAC地址用于在网络中唯一标示一个网卡，一台设备若有一
    或多个网卡，则每个网卡都需要并会有一个唯一的MAC地址。

    :return: 本机 MAC 地址
    """
    import uuid

    x = uuid.UUID(int=uuid.getnode()).hex[-12:].upper()
    x = "-".join([x[i : i + 2] for i in range(0, 11, 2)])
    return x


def to_arrow(df: pd.DataFrame):
    """将 pandas.DataFrame 转换为 pyarrow.Table"""
    import io
    import pyarrow as pa

    table = pa.Table.from_pandas(df)
    with io.BytesIO() as sink:
        with pa.ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
        return sink.getvalue()


def timeout_decorator(timeout):
    """Timeout decorator using threading

    :param timeout: int, timeout duration in seconds
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = [None]
            exception = [None]

            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=target)
            thread.start()
            thread.join(timeout)

            if thread.is_alive():
                logger.warning(f"{func.__name__} timed out after {timeout} seconds; args: {args}; kwargs: {kwargs}")
                return None

            if exception[0]:
                raise exception[0]

            return result[0]

        return wrapper

    return decorator
