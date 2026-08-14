"""Export the optional CreditCard-OCR YOLO detector to ONNX for production.

This script is intentionally separate from the service runtime. It needs
ultralytics and torch only on the build/development machine; the OCR service
loads the exported ONNX through OpenCV DNN and does not require either package.
"""
import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export CreditCard-OCR YOLO model to ONNX")
    parser.add_argument("--weights", type=Path, required=True, help="yolo_best.pt path")
    parser.add_argument(
        "--output", type=Path,
        default=Path("models/bank_card_roi/yolo_best.onnx"),
        help="output ONNX model path",
    )
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--opset", type=int, default=12)
    parser.add_argument(
        "--simplify",
        action="store_true",
        help="optionally simplify the exported graph; requires extra onnxslim dependency",
    )
    args = parser.parse_args()

    if not args.weights.is_file():
        raise SystemExit("weights file does not exist: {}".format(args.weights))
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit(
            "Missing export dependency. Install on this development machine only: "
            "python -m pip install ultralytics onnx"
        ) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(args.weights))
    # Export first, then run onnxslim ourselves. Ultralytics' built-in
    # simplify path may attempt to install a different onnxslim/runtime pair
    # and can produce a graph that OpenCV DNN cannot load.
    exported = Path(
        model.export(
            format="onnx",
            imgsz=args.imgsz,
            opset=args.opset,
            simplify=False,
        )
    )
    if not exported.is_file():
        raise SystemExit("YOLO export did not produce an ONNX file")
    if args.simplify:
        try:
            import onnxslim
        except ImportError as exc:
            raise SystemExit(
                "Missing simplify dependency. Install on this development machine only: "
                "python -m pip install onnxslim"
            ) from exc
        onnxslim.slim(str(exported), str(args.output))
    elif exported.resolve() != args.output.resolve():
        shutil.copy2(exported, args.output)
    print("Exported ONNX model: {}".format(args.output.resolve()))


if __name__ == "__main__":
    main()
