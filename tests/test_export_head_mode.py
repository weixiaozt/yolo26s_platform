import unittest

from core.export import _resolve_head_export_args


class ExportHeadModeTests(unittest.TestCase):
    def test_yolo11_without_nms_keeps_legacy_kwargs(self):
        mode, kwargs = _resolve_head_export_args(
            is_end2end=False,
            head_mode="legacy",
            nms=False,
        )

        self.assertEqual(mode, "legacy")
        self.assertEqual(kwargs, {})
        self.assertNotIn("end2end", kwargs)

    def test_yolo11_with_nms_keeps_existing_export_kwargs(self):
        mode, kwargs = _resolve_head_export_args(
            is_end2end=False,
            head_mode="legacy",
            nms=True,
        )

        self.assertEqual(mode, "legacy")
        self.assertEqual(kwargs, {"nms": True, "conf": 0.001})
        self.assertNotIn("end2end", kwargs)

    def test_yolo11_ignores_end2end_only_mode(self):
        mode, kwargs = _resolve_head_export_args(
            is_end2end=False,
            head_mode="compat",
            nms=False,
        )

        self.assertEqual(mode, "legacy")
        self.assertEqual(kwargs, {})
        self.assertNotIn("end2end", kwargs)

    def test_yolo26_compat_uses_one_to_many_and_runtime_nms(self):
        mode, kwargs = _resolve_head_export_args(
            is_end2end=True,
            head_mode="compat",
            nms=False,
        )

        self.assertEqual(mode, "compat")
        self.assertEqual(kwargs, {"end2end": False})
        self.assertNotIn("nms", kwargs)
        self.assertNotIn("conf", kwargs)

    def test_yolo26_native_does_not_inject_traditional_nms(self):
        mode, kwargs = _resolve_head_export_args(
            is_end2end=True,
            head_mode="native",
            nms=True,
        )

        self.assertEqual(mode, "native")
        self.assertEqual(kwargs, {})

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            _resolve_head_export_args(
                is_end2end=True,
                head_mode="invalid",
                nms=False,
            )


if __name__ == "__main__":
    unittest.main()
