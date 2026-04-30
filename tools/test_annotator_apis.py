# -*- coding: utf-8 -*-
"""测试标注 API 在前端 clamp + 后端原校验下的端到端行为"""

import requests
import sys
from pathlib import Path

API = "http://localhost:8000/api"

def login() -> str:
    for pw in ["admin123", "admin", "123456"]:
        r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": pw})
        if r.status_code == 200:
            return r.json()["token"]
    raise RuntimeError("登录失败")

TOKEN = login()
H = {"Authorization": f"Bearer {TOKEN}"}


def test_save_clamped_polygon():
    """前端 clamp 后保存：所有顶点都在 [0,1]"""
    print("=== Test 1: 标准范围内 polygon 保存 ===")
    # 找一张光伏板项目（#16）的图片
    imgs = requests.get(f"{API}/projects/16/images?page=1&page_size=1", headers=H).json()
    img_id = imgs["items"][0]["id"]
    print(f"  using image #{img_id}")

    classes = requests.get(f"{API}/projects/16", headers=H).json()["defect_classes"]
    cls_id = classes[0]["id"]

    # 模拟前端 clamp 后的 polygon（边缘贴齐）
    poly = [
        {"x": 0.0, "y": 0.0},
        {"x": 1.0, "y": 0.0},
        {"x": 1.0, "y": 1.0},
        {"x": 0.0, "y": 1.0},
    ]
    r = requests.post(
        f"{API}/images/{img_id}/annotations",
        json={"annotations": [{"class_id": cls_id, "polygon": poly}]},
        headers=H,
    )
    print(f"  HTTP {r.status_code}: {r.json() if r.ok else r.text[:200]}")
    assert r.status_code == 200, f"边缘 polygon 保存失败: {r.text}"

    # 验证读回
    r = requests.get(f"{API}/images/{img_id}/annotations", headers=H)
    anns = r.json()
    assert len(anns) == 1
    print(f"  [OK] 已成功保存边缘贴齐的 polygon")


def test_reject_out_of_range():
    """后端原校验：超出 [0,1] 拒绝（前端如果忘记 clamp 会被这里拦下）"""
    print("\n=== Test 2: 后端拒绝越界 polygon (兜底校验) ===")
    imgs = requests.get(f"{API}/projects/16/images?page=1&page_size=1", headers=H).json()
    img_id = imgs["items"][0]["id"]
    classes = requests.get(f"{API}/projects/16", headers=H).json()["defect_classes"]
    cls_id = classes[0]["id"]

    # 故意越界
    poly = [
        {"x": -0.1, "y": 0.0},  # 越界
        {"x": 1.5, "y": 0.0},   # 越界
        {"x": 0.5, "y": 0.5},
    ]
    r = requests.post(
        f"{API}/images/{img_id}/annotations",
        json={"annotations": [{"class_id": cls_id, "polygon": poly}]},
        headers=H,
    )
    print(f"  HTTP {r.status_code}: {r.text[:150]}")
    assert r.status_code == 422, f"应当返回 422 (后端校验), got {r.status_code}"
    print(f"  [OK] 越界值被后端拒绝（这就是用户之前看到的报错，前端 clamp 后不会再触发）")


def test_min_3_points():
    """后端要求至少 3 点"""
    print("\n=== Test 3: 后端要求 polygon 至少 3 点 ===")
    imgs = requests.get(f"{API}/projects/16/images?page=1&page_size=1", headers=H).json()
    img_id = imgs["items"][0]["id"]
    classes = requests.get(f"{API}/projects/16", headers=H).json()["defect_classes"]
    cls_id = classes[0]["id"]

    poly = [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.5}]  # 2 点
    r = requests.post(
        f"{API}/images/{img_id}/annotations",
        json={"annotations": [{"class_id": cls_id, "polygon": poly}]},
        headers=H,
    )
    print(f"  HTTP {r.status_code}: {r.text[:120]}")
    assert r.status_code == 422
    print(f"  [OK] 2 点 polygon 被拒绝")


def test_sanitize_simulates_frontend():
    """模拟前端 sanitize 后能保存原本越界的标注"""
    print("\n=== Test 5: 越界 polygon 经前端 sanitize 后能保存 ===")
    img_id = get_image_for_test()
    classes = requests.get(f"{API}/projects/16", headers=H).json()["defect_classes"]
    cls_id = classes[0]["id"]

    def sanitize(poly):
        out = []
        for p in poly:
            x = max(0.0, min(1.0, p["x"]))
            y = max(0.0, min(1.0, p["y"]))
            out.append({"x": round(x, 6), "y": round(y, 6)})
        return out

    raw_poly = [{"x": -0.001, "y": 0.1}, {"x": 1.005, "y": 0.1}, {"x": 0.5, "y": 0.9}]
    safe_poly = sanitize(raw_poly)
    r = requests.post(
        f"{API}/images/{img_id}/annotations",
        json={"annotations": [{"class_id": cls_id, "polygon": safe_poly}]},
        headers=H,
    )
    assert r.status_code == 200, r.text
    print(f"  [OK] 原始越界 ({raw_poly[0]['x']}) → sanitize → 0.0，保存成功")


def test_rect_4_points():
    """前端矩形工具产生的 4 点 polygon 能正常保存"""
    print("\n=== Test 4: 矩形工具的 4 点 polygon ===")
    imgs = requests.get(f"{API}/projects/16/images?page=1&page_size=1", headers=H).json()
    img_id = imgs["items"][0]["id"]
    classes = requests.get(f"{API}/projects/16", headers=H).json()["defect_classes"]
    cls_id = classes[0]["id"]

    # 模拟矩形工具产生的格式：左上→右上→右下→左下
    rect_poly = [
        {"x": 0.2, "y": 0.3}, {"x": 0.7, "y": 0.3},
        {"x": 0.7, "y": 0.8}, {"x": 0.2, "y": 0.8},
    ]
    r = requests.post(
        f"{API}/images/{img_id}/annotations",
        json={"annotations": [{"class_id": cls_id, "polygon": rect_poly}]},
        headers=H,
    )
    assert r.status_code == 200, r.text
    print(f"  [OK] 矩形 4 点 polygon 保存成功")


def get_image_for_test():
    imgs = requests.get(f"{API}/projects/16/images?page=1&page_size=1", headers=H).json()
    return imgs["items"][0]["id"]


def backup_annotations(img_id):
    r = requests.get(f"{API}/images/{img_id}/annotations", headers=H)
    return r.json()


def _sanitize_poly(poly):
    out = []
    for p in poly:
        if isinstance(p, list):
            x, y = p[0], p[1]
        else:
            x, y = p["x"], p["y"]
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        out.append({"x": round(x, 6), "y": round(y, 6)})
    return out


def restore_annotations(img_id, anns):
    """把原标注恢复（自动 sanitize 兼容历史越界数据）"""
    payload = []
    for a in anns:
        poly = _sanitize_poly(a["polygon"])
        if len(poly) < 3:
            continue
        payload.append({
            "class_id": a["class_id"],
            "polygon": poly,
            "area": a.get("area"),
            "bbox": a.get("bbox"),
        })
    r = requests.post(
        f"{API}/images/{img_id}/annotations",
        json={"annotations": payload},
        headers=H,
    )
    if not r.ok:
        print(f"  [WARN] restore HTTP {r.status_code}: {r.text[:200]}")


if __name__ == "__main__":
    img_id = get_image_for_test()
    backup = backup_annotations(img_id)
    print(f"备份了 {len(backup)} 个原标注，测试完会恢复\n")
    try:
        test_save_clamped_polygon()
        test_reject_out_of_range()
        test_min_3_points()
        test_sanitize_simulates_frontend()
        test_rect_4_points()
        print("\n=== 全部 API 测试通过 ===")
    finally:
        restore_annotations(img_id, backup)
        # 验证恢复
        after = requests.get(f"{API}/images/{img_id}/annotations", headers=H).json()
        print(f"已恢复 {len(after)} 个标注（原来 {len(backup)} 个）")
