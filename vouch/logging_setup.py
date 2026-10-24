"""JSON logs with request ids; optional Azure Monitor / OpenTelemetry tracing when APPLICATIONINSIGHTS_CONNECTION_STRING is set."""
import json, logging, os, sys, contextvars

request_id_var = contextvars.ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, r):
        d = {"ts": self.formatTime(r, "%Y-%m-%dT%H:%M:%S"), "level": r.levelname, "logger": r.name, "msg": r.getMessage(),
             "request_id": request_id_var.get()}
        for k in ("audit", "http"):
            if hasattr(r, k):
                d[k] = getattr(r, k)
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)
        return json.dumps(d, default=str)


def setup(level=None):
    root = logging.getLogger()
    if any(getattr(h, "_vouch", False) for h in root.handlers):
        return
    h = logging.StreamHandler(sys.stdout); h.setFormatter(JsonFormatter()); h._vouch = True
    root.addHandler(h); root.setLevel(level or os.environ.get("LOG_LEVEL", "INFO"))
    cs = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if cs:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor
            configure_azure_monitor(connection_string=cs)
            logging.getLogger("vouch").info("azure monitor tracing enabled")
        except ImportError:
            logging.getLogger("vouch").warning("APPLICATIONINSIGHTS_CONNECTION_STRING set but azure-monitor-opentelemetry not installed")
