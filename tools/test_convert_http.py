# -*- coding: utf-8 -*-
"""HTTP 端到端测试 — 项目类型转换 API"""

import requests
import sys
from pathlib import Path

API = "http://localhost:8000/api"


def login() -> str:
    for pw in ["admin123", "admin", "123456"]:
        r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": pw}, timeout=10)
        if r.status_code == 200:
            return r.json()["token"]
    raise RuntimeError("登录失败")


TOKEN = login()
H = {"Authorization": f"Bearer {TOKEN}"}


def create_test_det_project(name: str) -> int:
    """创建一个 det 测试项目"""
    r = requests.post(f"{API}/projects", json={
        "name": name,
        "task_type": "det",
        "crop_size": 640,
        "class_names": [{"class_index": 0, "name": "panel", "color": "#FF0000"}]
    }, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def get_project(pid: int) -> dict:
    r = requests.get(f"{API}/projects/{pid}", headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def delete_project(pid: int):
    requests.delete(f"{API}/projects/{pid}", headers=H)


def test_copy_mode():
    print("=== Test 1: HTTP copy 模式 det → seg ===")
    src_id = create_test_det_project("__HTTP_TEST_DET__")
    print(f"  创建源项目 #{src_id}")

    try:
        r = requests.post(
            f"{API}/projects/{src_id}/convert-task-type",
            data={"target_type": "seg", "mode": "copy", "new_name": "__HTTP_TEST_SEG__"},
            headers=H,
            timeout=60,
        )
        print(f"  HTTP {r.status_code}: {r.json()}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "copy"
        assert data["task_type"] == "seg"
        assert data["target_project_id"] != src_id
        new_id = data["target_project_id"]

        # 验证新项目
        new_p = get_project(new_id)
        assert new_p["task_type"] == "seg"
        print(f"  [OK] 新项目 #{new_id} 已创建，task_type=seg")

        # 验证原项目未变
        src_p = get_project(src_id)
        assert src_p["task_type"] == "det"
        print(f"  [OK] 原项目 #{src_id} 仍为 det")

        delete_project(new_id)
    finally:
        delete_project(src_id)


def test_inplace_mode():
    print("=== Test 2: HTTP inplace 模式 det → seg ===")
    src_id = create_test_det_project("__HTTP_TEST_INPLACE__")
    print(f"  创建源项目 #{src_id}")

    try:
        r = requests.post(
            f"{API}/projects/{src_id}/convert-task-type",
            data={"target_type": "seg", "mode": "inplace"},
            headers=H,
        )
        print(f"  HTTP {r.status_code}: {r.json()}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["mode"] == "inplace"
        assert data["target_project_id"] == src_id

        # 验证已转 seg
        p = get_project(src_id)
        assert p["task_type"] == "seg"
        print(f"  [OK] 项目 #{src_id} 已原地转为 seg")
    finally:
        delete_project(src_id)


def test_error_handling():
    print("=== Test 3: HTTP 错误处理 ===")

    # 3.1 项目不存在
    r = requests.post(
        f"{API}/projects/999999/convert-task-type",
        data={"target_type": "seg", "mode": "inplace"},
        headers=H,
    )
    print(f"  项目不存在: HTTP {r.status_code}: {r.json()}")
    assert r.status_code == 400

    # 3.2 同类型转换
    src_id = create_test_det_project("__HTTP_TEST_SAME__")
    try:
        r = requests.post(
            f"{API}/projects/{src_id}/convert-task-type",
            data={"target_type": "det", "mode": "inplace"},
            headers=H,
        )
        print(f"  同类型: HTTP {r.status_code}: {r.json()}")
        assert r.status_code == 400
    finally:
        delete_project(src_id)

    # 3.3 非法 target_type
    src_id = create_test_det_project("__HTTP_TEST_BAD__")
    try:
        r = requests.post(
            f"{API}/projects/{src_id}/convert-task-type",
            data={"target_type": "invalid", "mode": "inplace"},
            headers=H,
        )
        print(f"  非法类型: HTTP {r.status_code}: {r.json()}")
        assert r.status_code == 400
    finally:
        delete_project(src_id)

    print("  [OK] 全部错误场景正确返回 400")


def test_unauthenticated():
    print("=== Test 4: 未登录拒绝访问 ===")
    r = requests.post(
        f"{API}/projects/1/convert-task-type",
        data={"target_type": "seg", "mode": "inplace"},
    )  # 无 Authorization header
    print(f"  HTTP {r.status_code}")
    assert r.status_code in (401, 403), f"期望 401/403, got {r.status_code}"
    print("  [OK] 未登录被拒绝")


if __name__ == "__main__":
    test_copy_mode()
    print()
    test_inplace_mode()
    print()
    test_error_handling()
    print()
    test_unauthenticated()
    print()
    print("=== 全部 HTTP 测试通过 ===")
