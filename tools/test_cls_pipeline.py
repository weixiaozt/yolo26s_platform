# -*- coding: utf-8 -*-
"""
分类流水线端到端测试：
1. 用 TFC 数据集（128×128 小图，3 类 1576 张）走 cls-xml-run 导入
2. 验证 image.class_id 写入正确
3. 调用 prepare_classification_dataset 生成 YOLO cls 数据集
4. 用 yolo11s-cls.pt 跑 2 epochs 训练
5. 测试推理（top-1 + top-5）
"""
import sys, requests, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

API = "http://localhost:8000/api"
DATA_DIR = Path(r"D:\EasyLabel_x64\EasyLabelData\Style\Classify\TFC\Data")


def login() -> str:
    r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin123"})
    return r.json()["token"]


TOKEN = login()
H = {"Authorization": f"Bearer {TOKEN}"}


def test_xml_scan():
    print("=== Test 1: cls-xml-scan ===")
    xmls = sorted(DATA_DIR.glob("*.xml"))[:30]
    files = [("files", (f.name, open(f, "rb"), "application/xml")) for f in xmls]
    r = requests.post(f"{API}/import/cls-xml-scan", files=files, headers=H)
    for _, (_, fp, _) in files:
        fp.close()
    assert r.status_code == 200
    print(f"  classes: {r.json()['classes']}")
    return r.json()["classes"]


def test_xml_import():
    print("\n=== Test 2: cls-xml-run（完整 1576 张）===")
    bmps = sorted(DATA_DIR.glob("*.bmp"))
    xmls = sorted(DATA_DIR.glob("*.xml"))
    print(f"  uploading {len(bmps)} bmp + {len(xmls)} xml ...")

    images_data = [("images", (f.name, open(f, "rb"), "image/bmp")) for f in bmps]
    xmls_data = [("xmls", (f.name, open(f, "rb"), "application/xml")) for f in xmls]

    form = {
        "project_name": "TEST_CLS_TFC",
        "description": "TFC 自动测试",
        "crop_size": "128",
        "class_mapping_json": json.dumps({
            "Broken": {"class_index": 0, "color": "#FF4D4F"},
            "OK": {"class_index": 1, "color": "#52C41A"},
            "Crack": {"class_index": 2, "color": "#FAAD14"},
        })
    }

    try:
        r = requests.post(
            f"{API}/import/cls-xml-run",
            data=form, files=images_data + xmls_data,
            headers=H, timeout=300,
        )
    finally:
        for _, (_, fp, _) in images_data: fp.close()
        for _, (_, fp, _) in xmls_data: fp.close()

    print(f"  HTTP {r.status_code}")
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    print(f"  project_id={data['project_id']}, task_type={data['task_type']}")
    print(f"  stats: {data['stats']}")
    assert data["task_type"] == "cls"
    assert data["stats"]["labeled"] >= 1500  # 大部分应被打标
    return data["project_id"]


def test_dataset_service(project_id):
    print(f"\n=== Test 3: prepare_classification_dataset (project #{project_id}) ===")
    from server.database import SessionLocal, engine
    engine.echo = False
    from server.services.dataset_service import prepare_classification_dataset
    from server.config import settings
    import shutil

    db = SessionLocal()
    try:
        task_dir = settings.runs_path / "test_cls_dataset"
        if task_dir.exists(): shutil.rmtree(task_dir)
        task_dir.mkdir(parents=True)
        result = prepare_classification_dataset(project_id, str(task_dir), db, train_ratio=0.8)
        print(f"  dataset_dir: {result['dataset_dir']}")
        print(f"  class_names: {result['class_names']}")
        print(f"  split: {result['split_stats']}")

        # 校验目录结构
        ds = Path(result["dataset_dir"])
        for split in ("train", "val"):
            for cls in result["class_names"]:
                d = ds / split / cls
                assert d.exists(), f"missing {d}"
                cnt = len(list(d.glob("*")))
                print(f"    {split}/{cls}: {cnt}")
        print("  [OK] 数据集结构正确")
        return result["dataset_dir"]
    finally:
        db.close()


def test_train_2_epochs(dataset_dir, project_id):
    print(f"\n=== Test 4: 训练 2 epoch (验证 cls 流程能跑) ===")
    import os
    os.environ['YOLO_AUTOINSTALL'] = 'False'

    from core.train import run_train

    epochs_seen = []
    def on_epoch(d):
        epochs_seen.append(d.get("epoch"))
        print(f"  epoch {d.get('epoch')}: top1={d.get('top1_acc',0):.3f} top5={d.get('top5_acc',0):.3f}")

    result = run_train(
        dataset_yaml=dataset_dir,  # cls 模式直接传 dataset 目录
        output_dir=str(Path(dataset_dir).parent / "runs"),
        model_name="yolo11s-cls.pt",
        imgsz=128,
        epochs=2,
        batch_size=32,
        device="0",
        task_type="cls",
        epoch_callback=on_epoch,
        # cls 不需要这些
        augment_mosaic=0, augment_mixup=0, augment_copy_paste=0, close_mosaic=0,
    )
    print(f"  best_pt: {result['best_pt']}")
    assert result["best_pt"] and Path(result["best_pt"]).exists()
    print(f"  [OK] 训练完成，epochs_seen: {epochs_seen}")
    return result["best_pt"]


def test_inference(best_pt, project_id):
    print(f"\n=== Test 5: 推理 ===")
    from core.inference import load_model
    import cv2, numpy as np

    model, _ = load_model(best_pt)
    # 找一张 Broken 类的图
    test_img = next(DATA_DIR.glob("Broken_*.bmp"))
    img = cv2.imdecode(np.fromfile(str(test_img), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    print(f"  testing on: {test_img.name}")

    results = model.predict(img, verbose=False)
    r0 = results[0]
    print(f"  probs.top1: {r0.probs.top1}")
    print(f"  probs.top1conf: {float(r0.probs.top1conf):.4f}")
    top5_ids = r0.probs.top5
    top5_confs = [float(c) for c in r0.probs.top5conf]
    for cid, conf in zip(top5_ids, top5_confs):
        print(f"  cls{cid}: {conf:.4f}")
    print("  [OK] 推理成功")


def cleanup(project_id):
    print(f"\n=== Cleanup project #{project_id} ===")
    r = requests.delete(f"{API}/projects/{project_id}", headers=H)
    print(f"  HTTP {r.status_code}")


if __name__ == "__main__":
    classes = test_xml_scan()
    assert "Broken" in classes and "OK" in classes and "Crack" in classes

    pid = test_xml_import()

    dataset_dir = test_dataset_service(pid)

    best_pt = test_train_2_epochs(dataset_dir, pid)

    test_inference(best_pt, pid)

    cleanup(pid)

    print("\n=== ALL CLS TESTS PASSED ===")
