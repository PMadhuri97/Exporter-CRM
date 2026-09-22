import logging
import sys

import structlog

from app.platform.observability.tracing import add_trace_context


def configure_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        add_trace_context,  # stamp active OTel trace_id/span_id onto every log line
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: structlog.types.Processor
    if log_format == "console":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # aiokafka consumers long-poll the broker continuously — its DEBUG logs
    # (FetchRequest/heartbeat per group, ~2/sec) flood the output. Parent level
    # is inherited by aiokafka.conn / .consumer.fetcher / .group_coordinator etc.
    logging.getLogger("aiokafka").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
