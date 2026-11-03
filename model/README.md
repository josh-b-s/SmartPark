Put your trained YOLO weights file here as `model.pt`
(i.e. `smartpark/model/model.pt`).

This directory is deliberately excluded from the Docker image (see the
assignment's "updatable model" requirement). It gets mounted in at
container/pod startup instead of being baked in.

You can export weights from the training notebook, e.g.:
    model.export(format="onnx")   # or just use the .pt directly with app/model.py
