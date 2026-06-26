import hashlib
import io
import logging
import os
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

APP_VERSION    = "2.1.5"
APP_START_TIME = datetime.now()
STATIC_DIR      = "static"
LOG_FORMAT      = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("KomutaMerkezi")

os.makedirs(STATIC_DIR, exist_ok=True)

# Bellek içi grafik önbelleği
_GRAFIK_CACHE = {"html": ""}

class VeriDeposu:
    def __init__(self) -> None:
        self._lock        = threading.RLock()
        self._ham_df      : Optional[pd.DataFrame] = None
        self.son_yuklenme : Optional[datetime]      = None

    def yukle(self, df: pd.DataFrame) -> None:
        with self._lock:
            self._ham_df      = df.copy()
            self.son_yuklenme = datetime.now()

    def hazir_mi(self) -> bool:
        return self._ham_df is not None

depo = VeriDeposu()

app = FastAPI(
    title       = "Otonom Siber-Fiziksel Komuta Merkezi API",
    version     = APP_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def temiz_kolon_bul(df: pd.DataFrame, adaylar: List[str]) -> Optional[str]:
    # Kolon isimlerindeki boşlukları, büyük/küçük harfleri ve Türkçe karakterleri esnetir
    def temizle(s: str) -> str:
        return (str(s).lower()
                .replace("ı", "i").replace("ş", "s").replace("ğ", "g")
                .replace("ç", "c").replace("ö", "o").replace("ü", "u")
                .replace(" ", "").replace("_", "").replace("-", ""))
    
    for c in df.columns:
        if temizle(c) in [temizle(a) for a in adaylar]:
            return c
    return None

def det_rand(seed_str: str, lo: float, hi: float) -> float:
    h = int(hashlib.sha256(seed_str.encode()).hexdigest()[:16], 16)
    return round(random.Random(h).uniform(lo, hi), 4)

def kriz_metni_uret(mid: str, skor: float, ai: float, temp: float) -> str:
    if skor > 800:
        return f"KRITIK SABOTAJ: {mid} birimi {skor:.1f} skoruyla tum esikleri asti. ACIL MUDAHALE EMRI."
    elif skor > 500:
        return f"YUKSEK RISK: {mid} birimi {skor:.1f} sabotaj skoru ile tehlike bolgesinde."
    return f"IZLEMEDE: {mid} birimi {skor:.1f} skorla kontrol listesinde."

def sabotaj_analiz_yap(df: pd.DataFrame) -> List[Dict[str, Any]]:
    # Ne gelirse gelsin yakalayacak esnek eşleştirme listesi
    mid_k = temiz_kolon_bul(df, ["makine_id", "machine_id", "makine", "id", "sensor_id", "unit_id", "makineid", "machineid"])
    ovr_k = temiz_kolon_bul(df, ["ai_override", "aioverride", "override", "ai_score", "aiscore", "ai"])
    sic_k = temiz_kolon_bul(df, ["sicaklik", "temperature", "temp", "sicaklik_c", "temp_c"])
    omr_k = temiz_kolon_bul(df, ["kalan_omur", "kalan_sure", "remaining_life", "remaining_lifetime", "omur", "life"])

    # Eğer CSV'de bu kolonlar yine de bulunamazsa çökme, sırayla ilk kolonları ata!
    cols = list(df.columns)
    mid_col = mid_k if mid_k else cols[0]
    ovr_col = ovr_k if ovr_k else (cols[1] if len(cols) > 1 else cols[0])
    sic_col = sic_k if sic_k else (cols[2] if len(cols) > 2 else cols[0])
    omr_col = omr_k if omr_k else (cols[3] if len(cols) > 3 else cols[0])

    analiz = pd.DataFrame()
    analiz["Makine_ID"]   = df[mid_col].astype(str).str.strip()
    analiz["AI_Override"] = pd.to_numeric(df[ovr_col], errors="coerce").fillna(50.0)
    analiz["Sicaklik"]    = pd.to_numeric(df[sic_col], errors="coerce").fillna(60.0)
    analiz["Kalan_Omur"]  = pd.to_numeric(df[omr_col], errors="coerce").fillna(100.0)
    
    analiz["Sabotaj_Skoru"] = (analiz["AI_Override"] * analiz["Sicaklik"]) / (analiz["Kalan_Omur"] + 1)
    
    top3 = analiz.nlargest(3, "Sabotaj_Skoru").reset_index(drop=True)
    return [{
        "id": row["Makine_ID"], "sabotaj_skoru": round(float(row["Sabotaj_Skoru"]), 4),
        "ai_override": round(float(row["AI_Override"]), 4), "sicaklik": round(float(row["Sicaklik"]), 2),
        "kalan_omur": round(float(row["Kalan_Omur"]), 2), 
        "kriz_aciklamasi": kriz_metni_uret(row["Makine_ID"], row["Sabotaj_Skoru"], row["AI_Override"], row["Sicaklik"])
    } for _, row in top3.iterrows()]

def grafik_uret(sabotaj_data: Dict[str, Any], host: str) -> str:
    makineler = sabotaj_data.get("machines", [])
    if not makineler: return f"https://{host}/api/grafik/html"
    fig = go.Figure(go.Scatter(x=[m["sicaklik"] for m in makineler], y=[m["sabotaj_skoru"] for m in makineler], mode="markers+text", text=[m["id"] for m in makineler], marker=dict(size=40, color="red")))
    fig.update_layout(title="SIBER SABOTAJ ANALIZI", paper_bgcolor="#070711", plot_bgcolor="#0d0d1a", font=dict(color="#dce3f0"))
    
    html_buffer = io.StringIO()
    fig.write_html(html_buffer, include_plotlyjs="cdn", full_html=True)
    _GRAFIK_CACHE["html"] = html_buffer.getvalue()
    return f"https://{host}/api/grafik/html"

@app.get("/")
async def kok():
    return {"servis": "Otonom Komuta Merkezi", "durum": "AKTIF", "veri_hazir": depo.hazir_mi()}

@app.get("/health")
async def saglik():
    return {"status": "ok"}

@app.get("/api/grafik/html")
async def grafik_html_servis():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=_GRAFIK_CACHE["html"] or "<h1>Grafik Henuz Uretilmedi</h1>")

@app.post("/api/sabotaj/predict")
async def sabotaj_endpoint(data: UploadFile = File(...)):
    try:
        icerik = await data.read()
        try:
            df = pd.read_csv(io.BytesIO(icerik), encoding="utf-8")
        except:
            df = pd.read_csv(io.BytesIO(icerik), encoding="latin-1")
            
        depo.yukle(df)
        makineler = sabotaj_analiz_yap(df)
        return JSONResponse({"data": [{"machines": makineler}], "duration": 0.1, "average_duration": 0.1})
    except Exception as e:
        logger.error(f"Hata olustu: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

class OsintIstek(BaseModel): data: List[Dict[str, Any]]
@app.post("/api/osint/predict")
async def osint_endpoint(istek: OsintIstek):
    makine_idler = istek.data[0].get("makine_idler", ["M-101", "M-102"])
    sonuclar = [{
        "id": mid, "ip": f"192.168.1.{int(det_rand(mid, 2, 254))}",
        "ssh_saldiri": int(det_rand(mid, 10, 5000)), "rdp_saldiri": int(det_rand(mid, 5, 3000)),
        "durum": "KRITIK" if det_rand(mid, 0, 10) > 5 else "NORMAL"
    } for mid in makine_idler]
    return JSONResponse({"data": [{"makineler": sonuclar}]})

class EnerjiIstek(BaseModel): data: List[Dict[str, Any]]
@app.post("/api/enerji/predict")
async def enerji_endpoint(istek: EnerjiIstek):
    return JSONResponse({"data": [{"toplam_amper": 450.0, "trafo_yuk_yuzde": 75.0, "jenerator_durum": "STANDBY", "stabilite_uyari": "Sistem stabil."}]})

class ErpIstek(BaseModel): data: List[Dict[str, Any]]
@app.post("/api/erp/predict")
async def erp_endpoint(istek: ErpIstek):
    makine_idler = istek.data[0].get("makine_idler", ["M-101"])
    sonuclar = [{"id": mid, "son_bakim": "2026-06-01", "stok_durumu": "YETERLI", "not": "Bakim normal."} for mid in makine_idler]
    return JSONResponse({"data": [{"makineler": sonuclar}]})

class GrafikIstek(BaseModel): data: List[Dict[str, Any]]
@app.post("/api/grafik/predict")
async def grafik_endpoint(istek: GrafikIstek, request: Request):
    sabotaj_data = istek.data[0].get("sabotaj", {})
    host = request.headers.get("host", "localhost:8000")
    url = grafik_uret(sabotaj_data, host)
    return JSONResponse({"data": [{"grafik_url": url, "url": url}]})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
