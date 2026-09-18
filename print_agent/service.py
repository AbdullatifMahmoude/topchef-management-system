import logging
import sys
import threading
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from print_agent.config import LOGS_DIR, config
from print_agent.printer import thermal_printer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "print-agent.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("topchef_print_agent")


def ensure_windows_autostart() -> bool:
    """Register the installed agent for the current Windows user."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    try:
        import winreg

        command = f'"{sys.executable}"'
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, "TopChefPrintAgent", 0, winreg.REG_SZ, command)
        return True
    except OSError as exc:
        log.warning("Could not register Windows autostart: %s", exc)
        return False


class PrinterSettings(BaseModel):
    printer_names: list[str] = Field(default_factory=list)
    printer_width_mm: int = Field(default=80, ge=58, le=80)


class PrintJob(BaseModel):
    order: dict
    receipt_type: str = "customer"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    thermal_printer.start()
    yield


app = FastAPI(title="Top Chef Print Agent", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://([a-z0-9-]+\.)?topchefeg\.com$|^https://(topchef-dashboard|top-chef-resturant)\.vercel\.app$|^https://topchef-system\.fastapicloud\.dev$",
    allow_credentials=False,
    allow_private_network=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def local_only(request: Request, call_next):
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Local access only")
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "topchef-print-agent", "version": "1.0.0"}


@app.get("/api/printers")
def printers():
    selected = config.printer_names
    return {
        "printers": thermal_printer.get_printers(),
        "selected": selected,
    }


@app.get("/api/settings")
def get_settings():
    return {
        "printer_names": config.printer_names,
        "printer_width_mm": config.printer_width_mm,
    }


@app.post("/api/settings")
def save_settings(settings: PrinterSettings):
    available = set(thermal_printer.get_printers())
    unknown = [name for name in settings.printer_names if name not in available]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown printers: {', '.join(unknown)}")
    config.set("printer_names", list(dict.fromkeys(settings.printer_names)))
    config.set("printer_width_mm", settings.printer_width_mm)
    if not config.save():
        raise HTTPException(status_code=500, detail="Could not save settings")
    return {"ok": True, "printer_names": config.printer_names}


@app.post("/api/print", status_code=202)
def print_order(job: PrintJob):
    if not job.order:
        raise HTTPException(status_code=400, detail="Order data is required")
    if not config.printer_names:
        raise HTTPException(status_code=409, detail="No printer selected")
    accepted = thermal_printer.print_receipt(job.order, job.receipt_type)
    if not accepted:
        raise HTTPException(status_code=500, detail="Print job was not accepted")
    return {"ok": True, "queued": True}


@app.post("/api/test-print", status_code=202)
def test_print():
    if not config.printer_names:
        raise HTTPException(status_code=409, detail="No printer selected")
    return {"ok": thermal_printer.test_print(), "queued": True}


SETTINGS_HTML = """<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Top Chef Print Agent</title><style>
body{font-family:Segoe UI,Tahoma,sans-serif;background:#101114;color:#f4f4f4;margin:0;display:grid;place-items:center;min-height:100vh}
main{width:min(620px,calc(100% - 32px));background:#1b1d22;border:1px solid #333842;border-radius:18px;padding:28px;box-shadow:0 20px 60px #0008}
h1{color:#f4b942;margin:0 0 8px}.status{color:#8bd49c;margin-bottom:22px}.printer{display:flex;gap:10px;align-items:center;padding:13px;background:#252830;border-radius:10px;margin:8px 0}
button{border:0;border-radius:9px;padding:11px 18px;font-weight:700;cursor:pointer}.primary{background:#f4b942;color:#171717}.secondary{background:#383d48;color:white;margin-inline-start:8px}#msg{min-height:24px;margin-top:14px;color:#8bd49c}
</style></head><body><main><h1>Top Chef Print Agent</h1><div class="status">الخدمة تعمل على هذا الجهاز</div>
<h3>اختر الطابعة</h3><div id="printers">جاري تحميل الطابعات...</div>
<p><button class="primary" onclick="save()">حفظ الاختيار</button><button class="secondary" onclick="testPrint()">طباعة تجريبية</button></p><div id="msg"></div>
<script>
const p=document.getElementById('printers'),m=document.getElementById('msg');
async function load(){const r=await fetch('/api/printers'),d=await r.json();p.innerHTML=d.printers.length?d.printers.map(n=>`<label class="printer"><input type="checkbox" value="${n.replaceAll('&','&amp;').replaceAll('"','&quot;')}" ${d.selected.includes(n)?'checked':''}> <span>${n}</span></label>`).join(''):'لا توجد طابعات معرفة على Windows';}
async function save(){const names=[...document.querySelectorAll('input:checked')].map(x=>x.value);const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({printer_names:names,printer_width_mm:80})});m.textContent=r.ok?'تم حفظ الطابعة بنجاح':'تعذر حفظ الإعدادات';}
async function testPrint(){const r=await fetch('/api/test-print',{method:'POST'});m.textContent=r.ok?'تم إرسال صفحة الاختبار للطابعة':'اختر طابعة واحفظها أولًا';}
load().catch(()=>p.textContent='تعذر قراءة الطابعات');
</script></main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def settings_page():
    return SETTINGS_HTML


def main():
    ensure_windows_autostart()
    url = f"http://127.0.0.1:{config.local_port}"
    # Open setup only until at least one printer has been saved. Afterwards the
    # agent starts silently with Windows and reuses the persisted selection.
    if not config.printer_names:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    # A windowed PyInstaller executable has no stdout/stderr. Uvicorn's default
    # logging formatter probes those streams and crashes when they are None, so
    # the agent uses the file logger configured above instead.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=config.local_port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
