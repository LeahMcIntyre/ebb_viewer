def main():
    import sys
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QPushButton, QTextEdit, QFileDialog
    )

    from ebb_viewer.services.masks import build_spindle_state_mask

    app = QApplication(sys.argv)

    w = QWidget()
    w.setWindowTitle("ebb_viewer — Spindle mask demo")
    layout = QVBoxLayout(w)

    out = QTextEdit()
    out.setReadOnly(True)

    btn = QPushButton("Select Spindle CSV and build WAKE mask")

    def on_click():
        path, _ = QFileDialog.getOpenFileName(
            w,
            "Select Spindle CSV",
            "",
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return

        # For now: hardcode label(s). Later: UI pick list.
        result = build_spindle_state_mask(
            path,
            labels=["w"],
            fs=250,
            winsize=4,
            include=True,
            )

        out.setPlainText(
            "\n".join([
                f"File: {result['path']}",
                f"Samples: {result['n_samples']}",
                f"True fraction: {result['true_frac']:.4f}",
                f"False fraction: {result['false_frac']:.4f}",
            ])
        )

    btn.clicked.connect(on_click)

    layout.addWidget(btn)
    layout.addWidget(out)

    w.resize(700, 400)
    w.show()

    sys.exit(app.exec())
