
from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "pricing_demo.db"

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

USERS = {
    "parent": {
        "id": "parent",
        "name": "김민서",
        "segment": "긴급 구매형",
        "login_id": "minseo_parent",
        "profile": "영유아 자녀 · 빠른 배송 선호 · 최근 체온계 검색",
        "starting_bias": 900,
        "sensitivity": 32,
        "urgency": 84,
        "loyalty": 52,
    },
    "smart": {
        "id": "smart",
        "name": "박지훈",
        "segment": "가격 비교형",
        "login_id": "jihun_compare",
        "profile": "쿠폰 사용 빈번 · 브랜드 비교 다수 · 최저가 정렬 선호",
        "starting_bias": -700,
        "sensitivity": 88,
        "urgency": 25,
        "loyalty": 24,
    },
    "loyal": {
        "id": "loyal",
        "name": "이선영",
        "segment": "충성 고객형",
        "login_id": "sunyoung_loyal",
        "profile": "동일 브랜드 반복 구매 · 이탈 가능성 낮음 · 구매 이력 풍부",
        "starting_bias": 500,
        "sensitivity": 44,
        "urgency": 46,
        "loyalty": 91,
    },
}

PRODUCTS = [
    {"id": "thermo_a", "brand": "CareOne", "name": "귀·이마 겸용 체온계 Pro", "base_price": 32900, "rating": 4.8, "reviews": 2184, "stock": 7},
    {"id": "thermo_b", "brand": "MediSense", "name": "비접촉 적외선 체온계", "base_price": 28900, "rating": 4.6, "reviews": 1530, "stock": 13},
    {"id": "thermo_c", "brand": "HomeCheck", "name": "초고속 디지털 체온계", "base_price": 25900, "rating": 4.5, "reviews": 987, "stock": 21},
    {"id": "thermo_d", "brand": "ThermoLab", "name": "프리미엄 스마트 체온계", "base_price": 36900, "rating": 4.9, "reviews": 3021, "stock": 4},
]

RULES = {
    "view_review": (300, "후기를 확인해 구매 검토 의도가 상승"),
    "deep_review": (550, "후기를 자세히 읽어 구매 확률이 높아짐"),
    "check_shipping": (850, "도착일 확인으로 긴급성이 감지됨"),
    "check_stock": (450, "재고를 확인해 희소성 반응이 감지됨"),
    "favorite": (350, "찜하기로 관심 지속 신호가 확인됨"),
    "add_cart": (1400, "장바구니 담기로 구매 임박 가능성이 높아짐"),
    "remove_cart": (-900, "장바구니 제거로 이탈 가능성이 높아짐"),
    "coupon": (0, "개인화 쿠폰 계산 로직이 동적 적용됨"),
    "sort_low": (-850, "낮은 가격순 정렬로 가격 민감도가 확인됨"),
    "compare_brand": (-700, "다른 브랜드와 비교해 이탈 가능성이 높아짐"),
    "same_brand": (500, "같은 브랜드를 다시 확인해 관심도가 높아짐"),
    "dwell_4": (180, "4초 체류로 초기 관심 신호가 감지됨"),
    "dwell_8": (280, "8초 체류로 적극적 검토 신호가 감지됨"),
    "dwell_15": (420, "15초 체류로 높은 구매 관심이 감지됨"),
    "purchase_complete": (0, "구매 완료로 해당 사용자의 데이터 수집을 종료"),
}

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                segment TEXT NOT NULL,
                login_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                product_name TEXT NOT NULL,
                brand TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                old_price INTEGER NOT NULL,
                delta INTEGER NOT NULL,
                new_price INTEGER NOT NULL,
                reference_price INTEGER NOT NULL,
                dwell_seconds INTEGER NOT NULL DEFAULT 0,
                purchase_intent INTEGER NOT NULL DEFAULT 50,
                price_sensitivity INTEGER NOT NULL DEFAULT 50,
                urgency INTEGER NOT NULL DEFAULT 50,
                confidence INTEGER NOT NULL DEFAULT 50,
                session_closed INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()

def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))

def clamp_price(value: int, base: int) -> int:
    return clamp(value, int(base * 0.72), int(base * 1.35))

def get_product(product_id: str) -> dict[str, Any]:
    for product in PRODUCTS:
        if product["id"] == product_id:
            return product
    raise KeyError(product_id)

def calculate_personalized_coupon(user_id: str) -> dict[str, Any]:
    user = USERS.get(user_id)
    if not user:
        return {"discount_percent": 0, "reason": "unknown user"}
    
    urgency_factor = user["urgency"] * 0.15
    loyalty_factor = user["loyalty"] * 0.1
    bias_factor = user["starting_bias"] * 0.01
    
    discount_percent = 25 - (urgency_factor + loyalty_factor + bias_factor)
    discount_percent = clamp(int(discount_percent), 5, 25)
    
    if discount_percent <= 10:
        reason = f"구매 유력 고객(충성도/급박도 높음). 최소 이탈 방지 혜택({discount_percent}%)만 제시합니다."
    elif discount_percent <= 18:
        reason = f"이탈 가능성 중간 수준. 충성 고객용 기본 혜택({discount_percent}%)을 제시합니다."
    else:
        reason = f"가격비교형 극대화 상태. 이탈 방지를 위해 최대 파격 혜택({discount_percent}%)을 투입합니다."
        
    return {
        "user_id": user_id,
        "discount_percent": discount_percent,
        "reason": reason
    }

@app.get("/")
def index():
    return render_template("index.html", users=list(USERS.values()), products=PRODUCTS)

@app.get("/api/coupon/<user_id>")
def get_coupon(user_id: str):
    if user_id not in USERS:
        return jsonify({"error": "unknown user"}), 400
    return jsonify(calculate_personalized_coupon(user_id))

@app.post("/api/event")
def create_event():
    payload = request.get_json(force=True)

    user = USERS.get(payload.get("user_id"))
    if not user:
        return jsonify({"error": "unknown user"}), 400

    try:
        product = get_product(payload.get("product_id", ""))
    except KeyError:
        return jsonify({"error": "unknown product"}), 400

    action = payload.get("action")
    if action not in RULES:
        return jsonify({"error": "unknown action"}), 400

    with connect() as conn:
        last = conn.execute(
            "SELECT session_closed FROM events WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user["id"],),
        ).fetchone()

    if last and last["session_closed"]:
        return jsonify({"error": "해당 사용자는 이미 구매를 완료했습니다."}), 409

    old_price = int(payload.get("old_price", product["base_price"]))
    dwell_seconds = int(payload.get("dwell_seconds", 0))
    purchase_intent = clamp(int(payload.get("purchase_intent", 50)), 0, 100)
    price_sensitivity = clamp(int(payload.get("price_sensitivity", user["sensitivity"])), 0, 100)
    urgency = clamp(int(payload.get("urgency", user["urgency"])), 0, 100)

    base_delta, reason = RULES[action]
    delta = base_delta

    if action == "purchase_complete":
        new_price = old_price
        applied_delta = 0
        confidence = 99
    else:
        if action == "coupon":
            coupon_info = calculate_personalized_coupon(user["id"])
            discount_percent = coupon_info["discount_percent"]
            discount_amount = int(old_price * (discount_percent / 100))
            delta = -discount_amount
            reason = f"개인화 쿠폰 적용 ({discount_percent}% 할인) - {coupon_info['reason']}"
        else:
            if action == "check_shipping":
                delta += urgency * 3
            elif action in {"sort_low", "compare_brand"}:
                delta -= price_sensitivity * 4
            elif action in {"add_cart", "same_brand"}:
                delta += user["loyalty"] * 3
            elif action.startswith("dwell_"):
                delta += purchase_intent

        new_price = clamp_price(old_price + delta, product["base_price"])
        applied_delta = new_price - old_price
        confidence = clamp(55 + abs(applied_delta) // 40 + min(dwell_seconds, 20), 50, 98)

    created_at = datetime.now().isoformat(timespec="seconds")
    session_closed = 1 if action == "purchase_complete" else 0

    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO events (
                created_at, user_id, user_name, segment, login_id,
                product_id, product_name, brand, action, reason,
                old_price, delta, new_price, reference_price,
                dwell_seconds, purchase_intent, price_sensitivity,
                urgency, confidence, session_closed
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at, user["id"], user["name"], user["segment"], user["login_id"],
                product["id"], product["name"], product["brand"], action, reason,
                old_price, applied_delta, new_price, product["base_price"],
                dwell_seconds, purchase_intent, price_sensitivity,
                urgency, confidence, session_closed,
            ),
        )
        event_id = cur.lastrowid
        conn.commit()

    return jsonify({
        "id": event_id,
        "created_at": created_at,
        "delta": applied_delta,
        "new_price": new_price,
        "reason": reason,
        "confidence": confidence,
        "reference_price": product["base_price"],
        "session_closed": bool(session_closed),
    })

@app.get("/api/events")
def list_events():
    limit = min(max(int(request.args.get("limit", 120)), 1), 500)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return jsonify([dict(row) for row in rows])

@app.get("/api/summary")
def summary():
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"]
        active_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) AS c FROM events WHERE session_closed = 0"
        ).fetchone()["c"]
        completed_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) AS c FROM events WHERE session_closed = 1"
        ).fetchone()["c"]

        latest_rows = conn.execute(
            """
            SELECT e.*
            FROM events e
            INNER JOIN (
                SELECT user_id, MAX(id) AS max_id
                FROM events
                GROUP BY user_id
            ) x ON e.id = x.max_id
            ORDER BY e.user_id
            """
        ).fetchall()

    latest = [dict(row) for row in latest_rows]
    deviations = []
    for row in latest:
        ref = row["reference_price"] or 1
        deviations.append(((row["new_price"] - ref) / ref) * 100)
    spread = round(max(deviations) - min(deviations), 1) if len(deviations) >= 2 else 0.0

    return jsonify({
        "total": total,
        "active_users": active_users,
        "completed_users": completed_users,
        "spread": spread,
        "latest": latest,
    })

@app.post("/api/reset")
def reset():
    with connect() as conn:
        conn.execute("DELETE FROM events")
        conn.commit()
    return jsonify({"ok": True})

@app.get("/api/export.csv")
def export_csv():
    with connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM events ORDER BY id ASC").fetchall()]

    output = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else [
        "id","created_at","user_id","user_name","segment","login_id",
        "product_id","product_name","brand","action","reason",
        "old_price","delta","new_price","reference_price",
        "dwell_seconds","purchase_intent","price_sensitivity",
        "urgency","confidence","session_closed"
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=personalized_pricing_events.csv"},
    )

@app.get("/api/export.json")
def export_json():
    with connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM events ORDER BY id ASC").fetchall()]

    return Response(
        json.dumps(rows, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=personalized_pricing_events.json"},
    )

init_db()

import os
if __name__ == "__main__":
        app.run(host="127.0.0.1", port=5001, debug=True)
        
if __name__ == '__main__':
        # Render가 지정해주는 포트를 가져오고, 없으면 5000번을 씁니다.
        port = int(os.environ.get('PORT', 5000))
        # 0.0.0.0으로 설정해야 외부(인터넷)에서 접속이 가능합니다.
        app.run(host='0.0.0.0', port=port)