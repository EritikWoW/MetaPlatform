from PySide6.QtWidgets import QApplication

from src.ui_qt.widgets.circular_progress_dialog import CircularProgressDialog


def test_circular_progress_dialog_updates_value_and_labels() -> None:
    app = QApplication.instance() or QApplication([])

    dialog = CircularProgressDialog()
    dialog.setValue(67)
    dialog.setLabelText("Importing metadata...")
    dialog.setPhaseText("Збагачення")
    dialog.show()
    app.processEvents()

    assert dialog._ring.value() == 67
    assert dialog._message_label.text() == "Importing metadata..."
    assert dialog._phase_label.text() == "Збагачення"
    dialog.close()
