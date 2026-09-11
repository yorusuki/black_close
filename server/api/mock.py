"""給範例 layout 示範「資料來源可以是網路請求」用的假資料端點。

實際使用時，把模組 config 裡 value_source.url 換成你自己的服務（出勤系統、
天氣 API...）即可，不需要改任何模組程式碼。
"""

from __future__ import annotations
from flask import Blueprint, jsonify

bp = Blueprint("mock", __name__, url_prefix="/api/mock")


@bp.get("/leave-balance")
def leave_balance():
    return jsonify({"data": {"days": 8.5}})
