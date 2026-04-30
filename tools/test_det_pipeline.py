# -*- coding: utf-8 -*-
"""
端到端测试目标检测集成：
1. 通过 VOC import API 导入数据
2. 验证数据库记录
3. 调用 dataset_service 准备训练数据集
4. 验证生成的 YOLO 格式正确
5. (可选) 触发训练任务
"""

import sys
import requests
from pathlib import Path

# 项目根路径
sys.path.insert(0, str(Path(__file__).parent.parent))

API = "http://localhost:8000/api"
DATA_DIR = Path(r"D:\EasyLabel_x64\EasyLabelData\Style\ObjectDetect\光伏面板检测\Data")

# 登录获取 token
def login_admin():
    """用 admin 账号登录获取 token"""
    resp = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"}, timeout=10)
    if resp.status_code != 200:
        # 尝试常用密码
        for pw in ["123456", "admin123", "yolo26"]:
            resp = requests.post(f"{API}/auth/login", json={"username": "admin", "password": pw}, timeout=10)
            if resp.status_code == 200:
                break
    if resp.status_code != 200:
        raise RuntimeError(f"登录失败: {resp.status_code} {resp.text}")
    return resp.json()["token"]

TOKEN = login_admin()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def test_voc_scan():
    """Step 1: 测试 VOC 类别扫描"""
    print("\n" + "=" * 60)
    print("Step 1: 测试 voc-scan 端点")
    print("=" * 60)

    xml_files = sorted(DATA_DIR.glob("*.xml"))[:5]  # 只取前 5 个测试
    print(f"上传 {len(xml_files)} 个 XML 文件...")

    files = [("files", (f.name, open(f, "rb"), "application/xml")) for f in xml_files]
    resp = requests.post(f"{API}/import/voc-scan", files=files, headers=HEADERS, timeout=30)
    for _, (_, fp, _) in files:
        fp.close()

    print(f"HTTP {resp.status_code}: {resp.text[:200]}")
    assert resp.status_code == 200, f"voc-scan 失败: {resp.text}"
    data = resp.json()
    print(f"识别到类别: {data['classes']}")
    return data["classes"]


def test_voc_import():
    """Step 2: 测试完整 VOC 导入"""
    print("\n" + "=" * 60)
    print("Step 2: 测试 voc-run 完整导入")
    print("=" * 60)

    bmp_files = sorted(DATA_DIR.glob("*.bmp"))
    xml_files = sorted(DATA_DIR.glob("*.xml"))
    print(f"BMP: {len(bmp_files)}, XML: {len(xml_files)}")

    images_data = [("images", (f.name, open(f, "rb"), "image/bmp")) for f in bmp_files]
    xmls_data = [("xmls", (f.name, open(f, "rb"), "application/xml")) for f in xml_files]

    import json as _json
    form_data = {
        "project_name": "测试_光伏检测_自动",
        "description": "自动测试导入",
        "crop_size": "640",
        "class_mapping_json": _json.dumps({
            "panel": {"class_index": 0, "color": "#FF0000"}
        }),
    }

    try:
        resp = requests.post(
            f"{API}/import/voc-run",
            data=form_data,
            files=images_data + xmls_data,
            headers=HEADERS,
            timeout=180,
        )
    finally:
        for _, (_, fp, _) in images_data:
            fp.close()
        for _, (_, fp, _) in xmls_data:
            fp.close()

    print(f"HTTP {resp.status_code}: {resp.text[:500]}")
    assert resp.status_code == 200, f"voc-run 失败: {resp.text}"
    data = resp.json()
    print(f"项目 ID: {data['project_id']}")
    print(f"任务类型: {data['task_type']}")
    print(f"统计: {data['stats']}")

    # 校验
    assert data["task_type"] == "det"
    assert data["stats"]["total"] == len(bmp_files)
    assert data["stats"]["with_ann"] == len(xml_files)
    assert data["stats"]["total_boxes"] > 1000  # 数据集有 1423 个 bbox

    return data["project_id"]


def test_dataset_service(project_id: int):
    """Step 3: 测试 prepare_detection_dataset"""
    print("\n" + "=" * 60)
    print("Step 3: 测试 dataset_service 数据集构建")
    print("=" * 60)

    from server.database import SessionLocal
    from server.services.dataset_service import prepare_detection_dataset
    from server.config import settings

    db = SessionLocal()
    try:
        task_dir = settings.runs_path / "test_det_dataset"
        if task_dir.exists():
            import shutil
            shutil.rmtree(task_dir)
        task_dir.mkdir(parents=True)

        result = prepare_detection_dataset(
            project_id=project_id,
            task_output_dir=str(task_dir),
            db=db,
            train_ratio=0.85,
        )
        print(f"数据集目录: {result['dataset_dir']}")
        print(f"类别名: {result['class_names']}")
        print(f"导出统计: {result['export_stats']}")
        print(f"划分统计: {result['split_stats']}")

        # 校验目录结构
        ds = Path(result["dataset_dir"])
        train_imgs = list((ds / "images" / "train").glob("*"))
        val_imgs = list((ds / "images" / "val").glob("*"))
        train_lbls = list((ds / "labels" / "train").glob("*.txt"))
        val_lbls = list((ds / "labels" / "val").glob("*.txt"))

        print(f"  train images: {len(train_imgs)}, labels: {len(train_lbls)}")
        print(f"  val images: {len(val_imgs)}, labels: {len(val_lbls)}")
        assert len(train_imgs) == len(train_lbls)
        assert len(val_imgs) == len(val_lbls)

        # 检查一个 label 文件内容
        if train_lbls:
            sample = train_lbls[0].read_text().strip().split("\n")
            print(f"  sample label ({train_lbls[0].name}): {len(sample)} 行")
            print(f"    第一行: {sample[0] if sample else 'EMPTY'}")
            # 校验格式: class_id cx cy w h
            parts = sample[0].split() if sample else []
            assert len(parts) == 5, f"YOLO det 格式应为 5 列, got {len(parts)}"
            # 数值范围 0~1
            cls_id = int(parts[0])
            cx, cy, bw, bh = map(float, parts[1:])
            assert cls_id == 0
            assert 0 <= cx <= 1 and 0 <= cy <= 1
            assert 0 < bw <= 1 and 0 < bh <= 1
            print(f"    格式校验 [OK]")

        return result["dataset_dir"]
    finally:
        db.close()


def test_dataset_yaml_for_det(dataset_dir: str):
    """Step 4: 测试 dataset.yaml 生成"""
    print("\n" + "=" * 60)
    print("Step 4: 测试 dataset.yaml 生成")
    print("=" * 60)
    from core.train import generate_dataset_yaml

    out = Path(dataset_dir).parent / "dataset.yaml"
    generate_dataset_yaml(
        dataset_dir=dataset_dir,
        output_path=str(out),
        class_names=["panel"],
    )
    content = out.read_text(encoding="utf-8")
    print(f"dataset.yaml 内容:")
    print(content)
    assert "names:" in content
    assert "nc: 1" in content


def cleanup_project(project_id: int):
    """删除测试项目"""
    print("\n" + "=" * 60)
    print(f"Cleanup: 删除项目 #{project_id}")
    print("=" * 60)
    resp = requests.delete(f"{API}/projects/{project_id}", headers=HEADERS, timeout=30)
    print(f"DELETE: HTTP {resp.status_code}")


if __name__ == "__main__":
    # 1. scan
    classes = test_voc_scan()
    assert "panel" in classes

    # 2. import
    project_id = test_voc_import()

    # 3. dataset service
    dataset_dir = test_dataset_service(project_id)

    # 4. dataset.yaml
    test_dataset_yaml_for_det(dataset_dir)

    print("\n" + "=" * 60)
    print(f"[OK] 所有测试通过！项目 ID: {project_id}")
    print("=" * 60)
    print(f"\n下一步：用真实训练任务测试。或运行:")
    print(f"  curl -X DELETE {API}/projects/{project_id}")
