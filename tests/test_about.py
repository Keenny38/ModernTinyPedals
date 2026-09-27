import sys

sys.path.append(".")


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication

    root = QApplication(sys.argv)

    from tinypedal.ui.about import About

    about = About(None)
    sys.exit(about.exec())
