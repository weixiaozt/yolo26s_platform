import unittest

import numpy as np

from core.inference import _class_aware_nms


class ClassAwareNmsTests(unittest.TestCase):
    def test_is_translation_invariant(self):
        """平移不应改变框间 IoU，更不能导致不相交的框被误删。"""
        scores = np.array([0.9, 0.8], dtype=np.float32)
        classes = np.array([0, 0], dtype=np.int64)
        boxes = np.array(
            [
                [0, 0, 100, 100],
                [150, 0, 250, 100],
            ],
            dtype=np.float32,
        )
        shifted_boxes = boxes + np.array([1000, 1000, 1000, 1000], dtype=np.float32)

        self.assertEqual(_class_aware_nms(boxes, scores, classes, iou_thresh=0.5), [0, 1])
        self.assertEqual(_class_aware_nms(shifted_boxes, scores, classes, iou_thresh=0.5), [0, 1])

    def test_suppresses_overlapping_same_class_boxes(self):
        """坐标格式修复后仍应正常抑制同类别高重叠框。"""
        boxes = np.array(
            [
                [1000, 1000, 1100, 1100],
                [1010, 1010, 1110, 1110],
            ],
            dtype=np.float32,
        )
        scores = np.array([0.9, 0.8], dtype=np.float32)
        classes = np.array([0, 0], dtype=np.int64)

        self.assertEqual(_class_aware_nms(boxes, scores, classes, iou_thresh=0.5), [0])

    def test_keeps_overlapping_different_class_boxes(self):
        """class-aware NMS 不应让不同类别相互抑制。"""
        boxes = np.array(
            [
                [1000, 1000, 1100, 1100],
                [1010, 1010, 1110, 1110],
            ],
            dtype=np.float32,
        )
        scores = np.array([0.9, 0.8], dtype=np.float32)
        classes = np.array([0, 1], dtype=np.int64)

        self.assertEqual(_class_aware_nms(boxes, scores, classes, iou_thresh=0.5), [0, 1])


if __name__ == "__main__":
    unittest.main()
