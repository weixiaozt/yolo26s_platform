"""标注置信度回归：内存数据库和模拟模型，不修改业务数据或加载权重。"""
import unittest
import tempfile
from pathlib import Path
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from server.database import Base
from server.models import Project, Image, DefectClass, Annotation
from server.routers.annotations import get_annotations, save_annotations
from server.routers import inference
from server.schemas.annotation import AnnotationBatchSave, AnnotationCreate


POLYGON = [{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.1}, {"x": 0.3, "y": 0.3}]


class AnnotationConfidenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.project = Project(name="confidence regression", task_type="det")
        self.db.add(self.project)
        self.db.flush()
        self.cls = DefectClass(project_id=self.project.id, name="裂纹", class_index=0)
        self.image = Image(project_id=self.project.id, filename="test.png",
                           file_path="test.png", width=100, height=100)
        self.db.add_all([self.cls, self.image])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_mixed_annotations_keep_confidence_after_save_reload_and_edit(self):
        data = [{"class_id": self.cls.id, "polygon": POLYGON, "confidence": score}
                for score in [None, 0.0, 0.9137]]
        saved = save_annotations(self.image.id, AnnotationBatchSave(annotations=data), self.db)
        self.assertEqual([a.confidence for a in saved], [None, 0.0, 0.9137])
        self.db.expire_all()
        loaded = get_annotations(self.image.id, self.db)
        # 模拟移动顶点后再次全量保存，分数和人工来源不应丢失。
        edited = [a.model_dump() for a in loaded]
        edited[2]["polygon"][0] = {"x": 0.15, "y": 0.1}
        result = save_annotations(self.image.id, AnnotationBatchSave(annotations=edited), self.db)
        self.assertEqual([a.confidence for a in result], [None, 0.0, 0.9137])
        self.assertEqual(result[2].polygon[0]["x"], 0.15)

    def test_legacy_manual_annotation_and_invalid_scores(self):
        ann = AnnotationCreate(class_id=self.cls.id, polygon=POLYGON)
        self.assertIsNone(ann.confidence)
        for value in [-0.01, 1.01, float("nan"), float("inf")]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                AnnotationCreate(class_id=self.cls.id, polygon=POLYGON, confidence=value)

    def test_project_pack_and_conversion_preserve_inference_scores(self):
        from server.services import project_package, project_convert
        data = [{"class_id": self.cls.id, "polygon": POLYGON, "confidence": score}
                for score in [None, 0.88]]
        save_annotations(self.image.id, AnnotationBatchSave(annotations=data), self.db)
        with tempfile.TemporaryDirectory(prefix="annotation-confidence-") as directory:
            root = Path(directory)
            (root / "test.png").write_bytes(b"small fixture; no image decoding in package service")
            settings = SimpleNamespace(upload_path=root)
            with patch.object(project_package, "settings", settings), patch.object(project_convert, "settings", settings):
                pack = root / "fixture.zip"
                result = project_package.export_project_to_zip(self.project.id, self.db, pack)
                self.assertEqual(result["annotation_count"], 2)
                with pack.open("rb") as stream:
                    project_package.import_project_from_zip(stream, self.db)
                imported = self.db.query(Annotation).filter(Annotation.image_id != self.image.id).order_by(Annotation.id).all()
                self.assertEqual([a.confidence for a in imported], [None, 0.88])
                converted = project_convert.convert_project_task_type(
                    self.project.id, "seg", "copy", self.db)
                copied = self.db.query(Annotation).join(Image).filter(
                    Image.project_id == converted["target_project_id"]).order_by(Annotation.id).all()
                self.assertEqual([a.confidence for a in copied], [None, 0.88])

    def test_threshold_default_zero_and_validation(self):
        self.assertEqual(inference._annotation_confidence({}), 0.35)
        self.assertEqual(inference._annotation_confidence({"conf": 0}), 0)
        self.assertEqual(inference._annotation_confidence({"conf": 1}), 1)
        for value in [None, True, "", "oops", -0.1, 1.1, "NaN", "Infinity"]:
            with self.subTest(value=value), self.assertRaises(HTTPException) as caught:
                inference._annotation_confidence({"conf": value})
            self.assertEqual(caught.exception.status_code, 422)

    def mock_context(self, stack, task_type, model):
        self.project.task_type = task_type
        stack.enter_context(patch.object(inference, "_read_project_image",
                            return_value=(self.image, np.zeros((100, 100, 3), dtype=np.uint8), b"")))
        stack.enter_context(patch.object(inference, "_annotation_model_context",
                            return_value=(self.project, None, task_type, "mock.pt")))
        stack.enter_context(patch.object(inference, "_get_model", return_value=model))

    def test_seg_and_det_threshold_reaches_model_and_filters_results(self):
        result = {
            "num_detections": 3, "scores": [0.2, 0.75, 0.9], "classes": [0, 0, 0],
            "boxes": [[10, 10, 30, 30]] * 3, "masks": [],
        }
        for task_type in ["seg", "det"]:
            with self.subTest(task_type=task_type), ExitStack() as stack:
                self.mock_context(stack, task_type, Mock())
                predict = stack.enter_context(patch("core.inference.infer_single_image", return_value=result))
                output = inference.infer_annotation_current(
                    {"image_id": self.image.id, "project_id": self.project.id,
                     "conf": 0.75, "device": "cpu"}, self.db)
                self.assertEqual(predict.call_args.kwargs["conf_thresh"], 0.75)
                self.assertEqual([a["confidence"] for a in output["annotations"]], [0.75, 0.9])
                self.assertTrue(all(a["class_id"] == self.cls.id for a in output["annotations"]))

    def test_obb_threshold_reaches_model_and_filters_results(self):
        obb = Mock()
        obb.xyxyxyxy = np.array([[[10, 10], [30, 10], [30, 30], [10, 30]]] * 2)
        obb.cls = np.array([0, 0])
        obb.conf = np.array([0.4, 0.8])
        # SimpleNamespace 不支持 len，使用实际容器类型表示结果。
        class ObbResult:
            xyxyxyxy, cls, conf = obb.xyxyxyxy, obb.cls, obb.conf

            def __len__(self):
                return 2

        model = Mock()
        model.predict.return_value = [SimpleNamespace(obb=ObbResult())]
        with ExitStack() as stack:
            self.mock_context(stack, "obb", model)
            output = inference.infer_annotation_current(
                {"image_id": self.image.id, "project_id": self.project.id,
                 "conf": 0.7, "device": "cpu"}, self.db)
        self.assertEqual(model.predict.call_args.kwargs["conf"], 0.7)
        self.assertEqual([a["confidence"] for a in output["annotations"]], [0.8])
        self.assertEqual(len(output["annotations"][0]["polygon"]), 4)

    def test_classification_leaves_low_confidence_images_unlabeled(self):
        second = Image(project_id=self.project.id, filename="second.png", file_path="second.png")
        self.db.add(second)
        self.db.commit()
        model = Mock()
        model.names = {0: "裂纹"}
        model.predict.side_effect = [
            [SimpleNamespace(probs=SimpleNamespace(top1=0, top1conf=0.6))],
            [SimpleNamespace(probs=SimpleNamespace(top1=0, top1conf=0.9))],
        ]
        with ExitStack() as stack:
            self.mock_context(stack, "cls", model)
            output = inference.infer_annotation_cls_batch(
                {"project_id": self.project.id, "image_ids": [self.image.id, second.id],
                 "conf": 0.8, "device": "cpu"}, self.db)
        self.assertEqual(output["updated"], 1)
        self.assertEqual(output["skipped_low_confidence"], 1)
        self.assertEqual(output["failed"], 0)
        self.assertIsNone(self.image.class_id)
        self.assertEqual(second.class_id, self.cls.id)


if __name__ == "__main__":
    unittest.main()
