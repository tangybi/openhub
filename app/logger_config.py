"""统一的日志配置模块。

所有脚本/类共享同一套日志配置模式：
- 日志文件按天命名（如 ``{prefix}_20260801.log``），每天生成一个文件
- 同一天内多次运行会继续追加写入同一文件（不覆盖）
- 同时输出到终端和文件
- 中文以 UTF-8 编码写入
- 所有模块共用同一个 logger，日志不按类名/模块名区分

用法:
    from .logger_config import setup_logging, get_logger    # app 包内（如 main.py）
    from ..logger_config import setup_logging, get_logger   # services/agents 等兄弟子包

    log_file = setup_logging()   # 参数全部使用内置默认值
    logger = get_logger(__name__)   # 名称会被忽略，统一使用同一个 logger
    logger.info("hello")
"""

import datetime
import logging
import os
from typing import Optional

# 内置默认配置（如需修改，直接改这里即可，无需在调用处传参）
DEFAULT_LOG_DIR = "log"
DEFAULT_LOG_PREFIX = "app"
DEFAULT_LOG_LEVEL = logging.INFO
DEFAULT_CONSOLE = True

# 模块级共享状态
_current_log_file: Optional[str] = None
_initialized: bool = False
_logger_name: str = DEFAULT_LOG_PREFIX

# 默认日志格式（含 trace_id / span_id，便于与 OpenTelemetry 追踪关联）
_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-7s | %(name)s | "
    "trace=%(trace_id)s span=%(span_id)s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class TraceContextFilter(logging.Filter):
    """把当前 OpenTelemetry span 的 trace_id / span_id 附加到每条日志记录上。

    无活跃 span 时显示 ``-``；未安装 opentelemetry 时同样安全降级。
    这样每条日志都能与 span 追踪通过 trace_id 关联起来。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from opentelemetry import trace as otel_trace

            span = otel_trace.get_current_span()
            ctx = span.get_span_context()
            if ctx.is_valid:
                record.trace_id = format(ctx.trace_id, "032x")
                record.span_id = format(ctx.span_id, "016x")
            else:
                record.trace_id = "-"
                record.span_id = "-"
        except Exception:
            record.trace_id = "-"
            record.span_id = "-"
        return True


def setup_logging(
    log_dir: str = DEFAULT_LOG_DIR,
    prefix: str = DEFAULT_LOG_PREFIX,
    level: int = DEFAULT_LOG_LEVEL,
    console: bool = DEFAULT_CONSOLE,
) -> str:
    """初始化全局日志配置，返回日志文件路径。

    所有参数都有内置默认值（见模块顶部 ``DEFAULT_*`` 常量），
    调用方无需传参即可使用统一配置。

    Args:
        log_dir: 日志文件存放目录（自动创建）。
        prefix: 日志文件名前缀，最终形如 ``{prefix}_{YYYYmmdd}.log``。
        level: 根日志级别。
        console: 是否同时输出到终端。

    Returns:
        str: 本次运行使用的日志文件路径（同一天内为同一文件，追加写入）。

    Notes:
        - 全局只初始化一次；重复调用直接返回第一次的日志文件路径。
        - 日志文件按天命名；同一天内的多次运行都会追加到同一文件。
        - 同时会为 AutoGen 的 trace 日志（TRACE_LOGGER_NAME）挂载同一文件 handler，
          使 LLM 调用等 DEBUG 级事件也能完整落盘。
    """
    global _current_log_file, _initialized, _logger_name

    if _initialized:
        return _current_log_file or ""

    os.makedirs(log_dir, exist_ok=True)
    _current_log_file = os.path.join(
        log_dir,
        f"{prefix}_{datetime.datetime.now().strftime('%Y%m%d')}.log",
    )
    _logger_name = prefix

    handlers: list[logging.Handler] = [
        logging.FileHandler(_current_log_file, mode="a", encoding="utf-8"),
    ]
    if console:
        handlers.insert(0, logging.StreamHandler())

    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
        handlers=handlers,
    )

    # 给所有 handler 挂上 trace_id 过滤器（handler 级 filter 才会生效），
    # 让每条日志都带上当前 span 的 trace_id/span_id
    _trace_filter = TraceContextFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(_trace_filter)

    # 配置 AutoGen 的 trace 日志（DEBUG），使 LLM 调用完整写入同一文件
    try:
        from autogen_agentchat import TRACE_LOGGER_NAME

        trace_logger = logging.getLogger(TRACE_LOGGER_NAME)
        trace_file_handlers = []
        if console:
            trace_console = logging.StreamHandler()
            trace_console.addFilter(_trace_filter)
            trace_logger.addHandler(trace_console)
        trace_file = logging.FileHandler(
            _current_log_file, mode="a", encoding="utf-8"
        )
        trace_file.addFilter(_trace_filter)
        trace_logger.addHandler(trace_file)
        trace_logger.setLevel(logging.DEBUG)
    except ImportError:
        pass

    _initialized = True
    return _current_log_file


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """获取统一配置的共享 logger。

    参数可省略——所有模块共用同一个 logger，日志统一写入同一个文件，
    不按类名/模块名区分。

    如果尚未调用 :func:`setup_logging`，会自动用默认参数初始化一次。

    Args:
        name: 可选。兼容 ``get_logger(__name__)`` 的旧调用方式，不生效。

    Returns:
        logging.Logger: 共享的、已配置好格式与文件输出的 logger。
    """
    if not _initialized:
        setup_logging()
    return logging.getLogger(_logger_name)


def get_current_log_file() -> Optional[str]:
    """返回当前日志文件路径（未初始化时为 None）。"""
    return _current_log_file
