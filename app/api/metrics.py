from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.utils.metrics import metrics


router = APIRouter(prefix="/metrics", tags=["Monitoring"])


@router.get("", response_class=PlainTextResponse, include_in_schema=False)
def prometheus_metrics() -> PlainTextResponse:
    return PlainTextResponse(
        metrics.render_prometheus(),
        media_type="text/plain; version=0.0.4",
    )


@router.get("/json", summary="查看当前实例运行指标")
def json_metrics():
    """返回便于人工排查的当前进程指标；多实例时需分别查看每个实例。"""
    return metrics.snapshot()
