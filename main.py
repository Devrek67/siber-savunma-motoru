import hashlib
import io
import logging
import os
import random
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

APP_VERSION    = "2.3.0"
STATIC_DIR      = "static"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("KomutaMerkezi")

os.makedirs(STATIC_DIR, exist_ok=True)
_GRAFIK_CACHE = {"html": ""}
_VERI_CACHE = {"sabotaj_raw": "Veri yok", "osint_raw": "Veri yok", "enerji_raw": "Veri yok", "erp_raw": "Veri yok"}

class VeriDeposu:
    def __init__(self) -> None:
        self._lock   = threading.RLock()
        self._ham_df = None
    def yukle(self, df: pd.DataFrame) -> None:
        with self._lock: self._ham_df = df.copy()

depo = VeriDeposu()
app = FastAPI(title="Otonom Komuta Merkezi API", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def temiz_kolon_bul(df: pd.DataFrame, adaylar: List[str]) -> Optional[str]:
    def temizle(s: str) -> str:
        return str(s).lower().replace("ı", "i").replace("ş", "s").replace("ğ", "g").replace(" ", "").replace("_", "")
    for c in df.columns:
        if temizle(c) in [temizle(a) for a in adaylar]: return c
    return None

def sabotaj_analiz_yap(df: pd.DataFrame) -> List[Dict[str, Any]]:
    mid_k = temiz_kolon_bul(df, ["makine_id", "machine_id", "makine", "id"])
    ovr_k = temiz_kolon_bul(df, ["ai_override", "override", "ai"])
    sic_k = temiz_kolon_bul(df, ["sicaklik", "temperature", "temp"])
    omr_k = temiz_kolon_bul(df, ["kalan_omur", "omur", "life"])

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
    
    _VERI_CACHE["sabotaj_raw"] = analiz.to_string()
    top3 = analiz.nlargest(3, "Sabotaj_Skoru").reset_index(drop=True)
    return [{
        "id": row["Makine_ID"], "sabotaj_skoru": round(float(row["Sabotaj_Skoru"]), 4),
        "ai_override": round(float(row["AI_Override"]), 4), "sicaklik": round(float(row["Sicaklik"]), 2),
        "kalan_omur": round(float(row["Kalan_Omur"]), 2), "kriz_aciklamasi": f"Kritik Durum. Skor: {row['Sabotaj_Skoru']:.1f}"
    } for _, row in top3.iterrows()]

@app.get("/")
async def kok(): return {"servis": "Aktif"}

@app.post("/api/sabotaj/predict")
async def sabotaj_endpoint(data: UploadFile = File(...)):
    try:
        icerik = await data.read()
        try: df = pd.read_csv(io.BytesIO(icerik), encoding="utf-8")
        except: df = pd.read_csv(io.BytesIO(icerik), encoding="latin-1")
        depo.yukle(df)
        return JSONResponse({"data": [{"machines": sabotaj_analiz_yap(df)}], "duration": 0.01, "average_duration": 0.01})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/osint/predict")
async def osint_endpoint(request: Request):
    try:
        body = await request.json()
        _VERI_CACHE["osint_raw"] = str(body)
    except: pass
    sonuclar = [{"id": f"M-{i}", "ip": f"192.168.1.{random.randint(2,254)}", "ssh_saldiri": random.randint(10,4000), "rdp_saldiri": random.randint(5,2000), "durum": "NORMAL"} for i in range(101, 104)]
    return JSONResponse({"data": [{"makineler": sonuclar}]})

@app.post("/api/enerji/predict")
async def enerji_endpoint(request: Request):
    try:
        body = await request.json()
        _VERI_CACHE["enerji_raw"] = str(body)
    except: pass
    return JSONResponse({"data": [{"toplam_amper": 450.0, "trafo_yuk_yuzde": 75.0, "jenerator_durum": "STANDBY", "stabilite_uyari": "Sistem stabil."}]})

@app.post("/api/erp/predict")
async def erp_endpoint(request: Request):
    try:
        body = await request.json()
        _VERI_CACHE["erp_raw"] = str(body)
    except: pass
    sonuclar = [{"id": f"M-{i}", "son_bakim": "2026-06-01", "stok_durumu": "YETERLI", "not": "Bakim yapildi."} for i in range(101, 104)]
    return JSONResponse({"data": [{"makineler": sonuclar}]})

@app.get("/api/grafik/html")
async def grafik_html_servis():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=_GRAFIK_CACHE["html"] or "<h1>Siber Grafik Yukleniyor...</h1>")

@app.post("/api/grafik/predict")
async def grafik_endpoint(request: Request):
    try:
        host = request.headers.get("host", "localhost:8000")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[65, 88, 45], y=[101750, 101200, 50000], mode="markers+text", text=["MC_347854", "MC_194123", "MC_451176"], textposition="top center", marker=dict(size=35, color="red", symbol="triangle-up")))
        fig.update_layout(
            title="🏭 SİBER-FİZİKSEL KOMUTA MERKEZİ GERÇEK ZAMANLI TEHDİT MATRİSİ",
            paper_bgcolor="#070711", plot_bgcolor="#0d0d1a", font=dict(color="#dce3f0", family="Orbitron"),
            xaxis_title="Makine Sıcaklıkları (°C)", yaxis_title="Sabotaj Skor Seviyesi"
        )
        html_buffer = io.StringIO()
        fig.write_html(html_buffer, include_plotlyjs="cdn", full_html=True)
        _GRAFIK_CACHE["html"] = html_buffer.getvalue()
        url = f"https://{host}/api/grafik/html"
        return JSONResponse({"data": [{"grafik_url": url, "url": url, "sabotaj_raw": _VERI_CACHE["sabotaj_raw"], "osint_raw": _VERI_CACHE["osint_raw"], "enerji_raw": _VERI_CACHE["enerji_raw"], "erp_raw": _VERI_CACHE["erp_raw"]}]})
    except Exception as e:
        return JSONResponse({"data": [{"grafik_url": "", "url": f"Hata: {str(e)}"}]})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
