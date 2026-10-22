"""原生默认、模型列表与独立导出产物回归；不触碰业务库或下载权重。"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.export import run_export
from core.model_modes import supports_native_head, use_native_pytorch_head
from server.database import Base
from server.models import Project, TrainTask
from server.models.exported_model import ExportedModel
from server.routers.inference import list_models


class NativeModelPolicyTests(unittest.TestCase):
    def test_pytorch_compat_checkpoint_is_explicitly_switched_to_native(self):
        head = SimpleNamespace(one2one_cv2=object(), one2one_cv3=object())
        model = SimpleNamespace(model=SimpleNamespace(model=[head], end2end=False), overrides={"end2end": False})
        self.assertTrue(supports_native_head(model))
        use_native_pytorch_head(model)
        self.assertTrue(model.model.end2end)
        self.assertTrue(model.overrides["end2end"])

    def test_classification_legacy_and_fixed_export_graphs_are_not_switched(self):
        for network in [SimpleNamespace(model=[SimpleNamespace()]), "best_openvino_model", Path("best.onnx")]:
            with self.subTest(network=network):
                model = SimpleNamespace(model=network, overrides={"end2end": False})
                self.assertFalse(supports_native_head(model))
                use_native_pytorch_head(model)
                self.assertEqual(model.overrides, {"end2end": False})

    def test_list_prioritizes_yolo26_native_and_reads_actual_export_mode(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with tempfile.TemporaryDirectory() as directory, Session(engine) as db:
            root = Path(directory)
            project = Project(name="native defaults", task_type="seg")
            db.add(project)
            db.flush()
            paths = [root / "eleven.pt", root / "twentysix.pt"]
            for path in paths:
                path.write_bytes(b"fixture")
            old = TrainTask(project_id=project.id, task_name="11", status="completed", config={"model_name": "yolo11s-seg"}, best_model_path=str(paths[0]))
            new = TrainTask(project_id=project.id, task_name="26", status="completed", config={"model_name": "yolo26s-seg"}, best_model_path=str(paths[1]))
            db.add_all([old, new])
            db.flush()
            exported = root / "best_openvino_model"
            exported.mkdir()
            (exported / "metadata.yaml").write_text("end2end: false\n", encoding="utf-8")
            for mode in ["native", "compat"]:
                db.add(ExportedModel(task_id=new.id, source_path=str(paths[1]), export_format="openvino", status="completed", source_type="best", head_mode=mode, export_path=str(exported)))
            db.commit()
            result = list_models(project.id, db)
            self.assertEqual(len(result), 3, "shared old artifact is shown once")
            self.assertEqual(result[0]["model_path"], str(paths[1]))
            self.assertEqual(result[0]["head_mode"], "native")
            self.assertEqual(result[1]["model_path"], str(paths[0]))
            self.assertEqual(result[-1]["head_mode"], "compat")
            self.assertIn("[兼容]", result[-1]["label"])
        engine.dispose()

    def test_native_and_compat_exports_do_not_overwrite_each_other_or_source(self):
        calls = []

        class ExportModel:
            def __init__(self, path):
                self.path = Path(path)
                head = SimpleNamespace(one2one_cv2=object(), one2one_cv3=object(), end2end=False)
                self.model = SimpleNamespace(model=[head])

            def export(self, **kwargs):
                calls.append(kwargs)
                target = self.path.with_suffix(".onnx")
                target.write_text(json.dumps(kwargs), encoding="utf-8")
                return str(target)

        with tempfile.TemporaryDirectory() as directory, patch("ultralytics.YOLO", ExportModel):
            root = Path(directory)
            source = root / "best.pt"
            source.write_bytes(b"unchanged checkpoint")
            old_artifact = root / "best.onnx"
            old_artifact.write_bytes(b"existing deployment")
            native = run_export(str(source), str(root / "exports/export_1"), export_format="onnx", head_mode="native")
            native_bytes = Path(native["export_path"]).read_bytes()
            compat = run_export(str(source), str(root / "exports/export_2"), export_format="onnx", head_mode="compat")
            self.assertNotEqual(native["export_path"], compat["export_path"])
            self.assertEqual(Path(native["export_path"]).read_bytes(), native_bytes)
            self.assertTrue(calls[0]["end2end"])
            self.assertFalse(calls[1]["end2end"])
            self.assertFalse(calls[0]["nms"])
            self.assertEqual(source.read_bytes(), b"unchanged checkpoint")
            self.assertEqual(old_artifact.read_bytes(), b"existing deployment")


if __name__ == "__main__":
    unittest.main()
