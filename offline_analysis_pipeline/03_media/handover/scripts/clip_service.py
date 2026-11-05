"""本地部署 OFA-Sys/chinese-clip-vit-base-patch16（原型探索，未进生产）。

用法：
  1) 安装依赖：pip install torch transformers pillow fastapi uvicorn python-multipart
  2) 国内下载模型（首次约 750MB）：PowerShell 执行
       $env:HF_ENDPOINT = "https://hf-mirror.com"
  3) 自检（不启服务）：
       python backend/scripts/clip_service.py --selftest
  4) 启动服务（默认 127.0.0.1:8100）：
       python backend/scripts/clip_service.py
       python backend/scripts/clip_service.py --host 0.0.0.0 --port 8100
"""

import argparse
import io
import base64
import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # 规避 Windows 下 OpenMP 运行时冲突

from contextlib import asynccontextmanager

import torch
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form
from PIL import Image
from transformers import ChineseCLIPProcessor, ChineseCLIPModel

MODEL_ID = "OFA-Sys/chinese-clip-vit-base-patch16"


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_model()
    yield


_state: dict = {}


def load_model(device: str | None = None) -> None:
    """加载模型与 processor，进程内单例。"""
    if _state.get("model") is not None:
        return
    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    model = ChineseCLIPModel.from_pretrained(MODEL_ID)
    model.eval().to(dev)
    processor = ChineseCLIPProcessor.from_pretrained(MODEL_ID)
    _state["model"] = model
    _state["processor"] = processor
    _state["device"] = dev


@torch.no_grad()
def encode_texts(texts: list[str], max_length: int = 64) -> list[list[float]]:
    model, processor, dev = _state["model"], _state["processor"], _state["device"]
    inputs = processor(
        text=texts, return_tensors="pt", padding=True,
        truncation=True, max_length=max_length,
    ).to(dev)
    feats = model.get_text_features(**inputs)
    if not torch.is_tensor(feats):  # transformers>=5 返回 ModelOutput
        feats = feats.pooler_output
    return feats.cpu().tolist()


@torch.no_grad()
def encode_images(images: list[Image.Image]) -> list[list[float]]:
    model, processor, dev = _state["model"], _state["processor"], _state["device"]
    inputs = processor(images=images, return_tensors="pt").to(dev)
    feats = model.get_image_features(**inputs)
    if not torch.is_tensor(feats):  # transformers>=5 返回 ModelOutput
        feats = feats.pooler_output
    return feats.cpu().tolist()


def decode_image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("RGB")


# ---------------- FastAPI 服务 ----------------

app = FastAPI(title="chinese-clip-vit-base-patch16 local service", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    loaded = _state.get("model") is not None
    return {"model": MODEL_ID, "loaded": loaded, "device": _state.get("device")}


@app.post("/encode/text")
def api_encode_text(payload: dict) -> dict:
    texts = payload.get("texts") or []
    if not texts or not all(isinstance(t, str) for t in texts):
        return {"error": "需要 {'texts': ['中文文本', ...]}"}
    feats = encode_texts(texts)
    return {"model": MODEL_ID, "features": feats}


@app.post("/encode/image")
async def api_encode_image(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    feats = encode_images([decode_image(data)])
    return {"model": MODEL_ID, "features": feats}


@app.post("/match")
async def api_match(file: UploadFile = File(...), texts: str = Form(...)) -> dict:
    """图文匹配：上传一张图片 + form 字段 texts=逗号分隔的中文描述，
    返回每个描述的相似度与归一化概率。"""
    text_list = [t.strip() for t in texts.split(",") if t.strip()]
    if not text_list:
        return {"error": "texts 不能为空，格式: texts=新能源车内饰干净,后排空间大"}
    data = await file.read()
    img_feat = torch.tensor(encode_images([decode_image(data)]))       # [1, d]
    txt_feat = torch.tensor(encode_texts(text_list))                    # [n, d]
    logits = img_feat @ txt_feat.T * _state["model"].logit_scale.exp().item()
    probs = logits.softmax(dim=-1)[0]
    return {
        "model": MODEL_ID,
        "results": [
            {"text": t, "logit": round(l, 4), "prob": round(p, 4)}
            for t, l, p in zip(text_list, logits[0].tolist(), probs.tolist())
        ],
    }


# ---------------- 自检 ----------------

def selftest() -> None:
    load_model()
    imgs = [Image.new("RGB", (224, 224), color=c) for c in [(255, 0, 0), (0, 0, 255)]]
    texts = ["一张纯红色的图片", "一张纯蓝色的图片"]
    i_feats = torch.tensor(encode_images(imgs))
    t_feats = torch.tensor(encode_texts(texts))
    logits = i_feats @ t_feats.T * _state["model"].logit_scale.exp().item()
    probs = logits.softmax(dim=-1)
    print(f"device: {_state['device']}")
    for name, p in zip(texts, probs[0].tolist()):
        print(f"  与红图匹配概率 [{name}]: {p:.4f}")
    print("selftest OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--device", default=None, help="cpu / cuda")
    args = parser.parse_args()

    if args.selftest:
        selftest()
    else:
        uvicorn.run(app, host=args.host, port=args.port)
