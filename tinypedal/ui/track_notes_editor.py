#  TinyPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of TinyPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Track & pace notes editor
"""

from __future__ import annotations

import os

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..api_control import api
from ..const_common import EMPTY_DICT
from ..i18n import tr, trm, untr
from ..setting import cfg
from ..userfile.track_notes import (
    COLUMN_DISTANCE,
    COLUMN_TAGS,
    NOTESTYPE_PACE,
    NOTESTYPE_TRACK,
    TAG_PITNOTES,
    create_notes_metadata,
    load_notes_file,
    save_notes_file,
    set_notes_filter,
    set_notes_header,
    set_notes_header_by_filter,
    set_notes_parser,
    set_notes_writer,
)
from ._common import (
    QVAL_FILENAME,
    BaseDialog,
    BaseEditor,
    BatchOffset,
    CompactButton,
    FloatTableItem,
    TableBatchReplace,
    UIScaler,
    table_item,
)
from .track_map_viewer import MapView

DECIMALS = 2


def set_file_path(notes_type: str, filename: str = "") -> str:
    """Set file path"""
    if notes_type == NOTESTYPE_PACE:
        filepath = cfg.path.pace_notes
    else:
        filepath = cfg.path.track_notes
    return f"{filepath}{filename}"


class TrackNotesEditor(BaseEditor):
    """Track & pace notes editor"""

    def __init__(self, parent):
        super().__init__(parent)
        self.set_utility_title(tr("Track Notes Editor"))

        self.notes_type: str = ""
        self.notes_header: tuple[str, ...] = ()
        self.notes_metadata = create_notes_metadata()
        self._verify_enabled = True

        # Set status bar
        self.status_bar = QStatusBar(self)

        # Set panels
        self.trackmap_panel = self.set_layout_trackmap()
        self.editor_panel = self.set_layout_editor()
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(5)
        splitter.addWidget(self.trackmap_panel)
        splitter.addWidget(self.editor_panel)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        #splitter.setStretchFactor(0,1)

        # Undo history, reset after each new or loaded file
        self.enable_undo(self.capture_notes, self.restore_notes)

        # Init setting & table
        self.create_pacenotes()

        # Set layout
        layout_main = QVBoxLayout()
        layout_main.setContentsMargins(self.MARGIN, self.MARGIN, self.MARGIN, 0)
        layout_main.addWidget(splitter, stretch=1)
        layout_main.addWidget(self.status_bar)
        self.setLayout(layout_main)

    def toggle_trackmap_panel(self, checked: bool):
        """Toggle trackmap panel"""
        self.trackmap_panel.setHidden(not checked)
        self.button_showmap.setText("Hide Map" if checked else "Show Map")

    def set_layout_trackmap(self):
        """Set track map panel"""
        self.trackmap = MapView(self)
        self.trackmap.reloaded.connect(self.mark_positions_on_map)

        layout_map_wrap = QVBoxLayout()
        layout_map_wrap.addWidget(self.trackmap)
        layout_map_wrap.setContentsMargins(0, 0, 0, 0)

        frame_trackmap = QFrame(self)
        frame_trackmap.setLayout(layout_map_wrap)
        frame_trackmap.setFrameShape(QFrame.Shape.StyledPanel)

        layout_trackmap = QVBoxLayout()
        layout_trackmap.addLayout(self.trackmap.set_button_layout())
        layout_trackmap.addWidget(frame_trackmap)
        layout_trackmap.addLayout(self.trackmap.set_control_layout())
        layout_trackmap.setContentsMargins(0, 0, 0, 0)

        trackmap_panel = QFrame(self)
        trackmap_panel.setMinimumSize(UIScaler.size(38), UIScaler.size(38))
        trackmap_panel.setLayout(layout_trackmap)
        return trackmap_panel

    def set_layout_editor(self):
        """Set editor panel"""
        # Notes table
        self.table_notes = QTableWidget(self)
        self.table_notes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_notes.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table_notes.cellChanged.connect(self.verify_input)

        self.table_context_menu = self.set_context_menu()
        self.table_notes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table_notes.customContextMenuRequested.connect(self.open_context_menu)

        # Notes filename edit
        self.filename_entry = QLineEdit()
        self.filename_entry.setValidator(QVAL_FILENAME)

        # File menu
        file_menu = QMenu(self)

        create_pacenotes = file_menu.addAction(tr("New Pace Notes"))
        create_pacenotes.triggered.connect(self.create_pacenotes)

        create_tracknotes = file_menu.addAction(tr("New Track Notes"))
        create_tracknotes.triggered.connect(self.create_tracknotes)

        file_menu.addSeparator()

        open_pacenotes = file_menu.addAction(tr("Open Pace Notes"))
        open_pacenotes.triggered.connect(self.load_pacenotes_file)

        open_tracknotes = file_menu.addAction(tr("Open Track Notes"))
        open_tracknotes.triggered.connect(self.load_tracknotes_file)

        button_file = CompactButton(tr("File"), has_menu=True)
        button_file.setMenu(file_menu)

        # Set position menu
        setpos_menu = QMenu(self)

        setpos_frommap = setpos_menu.addAction(tr("From Map"))
        setpos_frommap.triggered.connect(self.set_position_from_map)

        setpos_fromtele = setpos_menu.addAction(tr("From Telemetry"))
        setpos_fromtele.triggered.connect(self.set_position_from_tele)

        button_setpos = CompactButton(tr("Set Pos"), has_menu=True)
        button_setpos.setMenu(setpos_menu)

        # Button
        self.button_showmap = CompactButton(tr("Hide Map"))
        self.button_showmap.setCheckable(True)
        self.button_showmap.setChecked(True)
        self.button_showmap.clicked.connect(self.toggle_trackmap_panel)

        button_add = CompactButton(tr("Add"))
        button_add.clicked.connect(self.add_notes)

        button_insert = CompactButton(tr("Insert"))
        button_insert.clicked.connect(self.insert_notes)

        button_sort = CompactButton(tr("Sort"))
        button_sort.clicked.connect(self.sort_notes)

        button_delete = CompactButton(tr("Delete"))
        button_delete.clicked.connect(self.delete_notes)

        button_replace = CompactButton(tr("Replace"))
        button_replace.clicked.connect(self.open_replace_dialog)

        button_offset = CompactButton(tr("Offset"))
        button_offset.clicked.connect(self.open_offset_dialog)

        button_metadata = CompactButton(tr("Info"))
        button_metadata.clicked.connect(self.open_metadata_dialog)

        button_save = CompactButton(tr("Save As"))
        button_save.clicked.connect(self.saving)

        button_close = CompactButton(tr("Close"))
        button_close.clicked.connect(self.close)

        layout_top = QHBoxLayout()
        layout_top.addWidget(self.button_showmap)
        layout_top.addWidget(button_file)
        layout_top.addWidget(self.filename_entry, stretch=1)
        layout_top.addWidget(button_metadata)
        layout_top.addWidget(button_save)

        layout_button = QHBoxLayout()
        layout_button.addWidget(button_setpos)
        layout_button.addWidget(button_add)
        layout_button.addWidget(button_insert)
        layout_button.addWidget(button_sort)
        layout_button.addWidget(button_delete)
        layout_button.addWidget(button_replace)
        layout_button.addWidget(button_offset)
        self.add_undo_buttons(layout_button)
        layout_button.addStretch(1)
        layout_button.addWidget(button_close)

        layout_editor = QVBoxLayout()
        layout_editor.addLayout(layout_top)
        layout_editor.addWidget(self.table_notes)
        layout_editor.addLayout(layout_button)
        layout_editor.setContentsMargins(0, 0, 0, 0)

        editor_panel = QFrame(self)
        editor_panel.setMinimumSize(UIScaler.size(40), UIScaler.size(38))
        editor_panel.setLayout(layout_editor)
        return editor_panel

    def set_notes_type(self, notes_type: str):
        """Set notes type"""
        self.notes_type = notes_type
        self.notes_header = set_notes_header(notes_type)
        self.status_bar.showMessage(trm(f"Edit Mode: {notes_type}"), 0)
        self.filename_entry.setPlaceholderText(trm(f"{notes_type} Name"))

    def create_pacenotes(self):
        """Create pace notes file"""
        self.create_new_file(NOTESTYPE_PACE)

    def create_tracknotes(self):
        """Load track notes file"""
        self.create_new_file(NOTESTYPE_TRACK)

    def create_new_file(self, notes_type: str):
        """Create new file"""
        if not self.confirm_discard():
            return

        self.set_notes_type(notes_type)
        self.filename_entry.setText(self.get_track_name())
        self.notes_metadata.update(create_notes_metadata())
        self.refresh_table([])
        self.add_notes()
        self.set_unmodified()
        self.reset_undo()

    def load_pacenotes_file(self):
        """Load pace notes file"""
        self.load_from_file(NOTESTYPE_PACE)

    def load_tracknotes_file(self):
        """Load track notes file"""
        self.load_from_file(NOTESTYPE_TRACK)

    def load_from_file(self, notes_type: str):
        """Load notes from file"""
        if not self.confirm_discard():
            return

        filename_full, file_filter = QFileDialog.getOpenFileName(
            self,
            dir=set_file_path(notes_type),
            filter=set_notes_filter(notes_type),
        )
        if not filename_full:
            return

        filepath = os.path.dirname(filename_full) + "/"
        filename = os.path.basename(filename_full)
        notes_header = set_notes_header(notes_type)
        notes_parsed = load_notes_file(
            filepath=filepath,
            filename=filename,
            table_header=notes_header,
            parser=set_notes_parser(file_filter),
        )

        if notes_parsed is None:
            msg_text = "Cannot open selected file.<br><br>Invalid notes file."
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            return

        notes_sorted, meta_info = notes_parsed
        self.set_notes_type(notes_type)
        self.notes_metadata.update(meta_info)
        self.filename_entry.setText(filename)
        self.refresh_table(notes_sorted)
        self.set_unmodified()
        self.reset_undo()
        self.mark_positions_on_map()

    def refresh_table(self, notes_sorted: list[dict]):
        """Refresh notes table"""
        self.table_notes.setRowCount(0)
        self.table_notes.setColumnCount(len(self.notes_header))
        self.table_notes.setHorizontalHeaderLabels(self.notes_header)
        self.table_notes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_notes.setColumnWidth(0, UIScaler.size(6))
        self.table_notes.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table_notes.setColumnWidth(3, UIScaler.size(3))

        self._verify_enabled = False
        for row_index, note_line in enumerate(notes_sorted):
            self.add_table_row(row_index, note_line)
        self._verify_enabled = True

    def add_table_row(self, row_index: int, note_data: dict = EMPTY_DICT):
        """Add new table row"""
        self.table_notes.insertRow(row_index)
        for column_index, fieldname in enumerate(self.notes_header):
            if fieldname == COLUMN_DISTANCE:
                value = note_data.get(fieldname, 0)
                item = FloatTableItem(round(value, DECIMALS))
            elif fieldname == COLUMN_TAGS:
                value = note_data.get(fieldname, "")
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setForeground(Qt.GlobalColor.red)
            else:
                value = note_data.get(fieldname, "")
                item = QTableWidgetItem(value)
            self.table_notes.setItem(row_index, column_index, item)

    def open_replace_dialog(self):
        """Open replace dialog"""
        excludes = (COLUMN_DISTANCE, COLUMN_TAGS)
        selector = {name: index for index, name in enumerate(self.notes_header) if name not in excludes}
        _dialog = TableBatchReplace(self, selector, self.table_notes)
        _dialog.open()

    def open_metadata_dialog(self):
        """Open metadata dialog"""
        _dialog = MetaDataEditor(self, self.notes_metadata)
        _dialog.open()

    def open_offset_dialog(self):
        """Open offset dialog"""
        if self.column_selection_count(0) == 0:
            msg_text = (
                "Select <b>one or more values</b> from <b>distance</b> "
                "column to apply offset."
            )
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            return

        _dialog = BatchOffset(self, self.apply_batch_offset)
        _dialog.config(2, 0.1, -99999, 99999)
        _dialog.open()

    def apply_batch_offset(self, offset: float, is_scale_mode: bool):
        """Apply batch offset"""
        self._verify_enabled = False
        for item in self.table_notes.selectedItems():
            value = item.value()
            if is_scale_mode:
                value *= offset
            else:
                value += offset
            item.setValue(round(value, DECIMALS))
        self._verify_enabled = True
        self.set_modified()
        self.mark_positions_on_map()

    def set_position_from_map(self):
        """Set position from map"""
        self.set_position(float(self.trackmap.map_seek_dist), "from map")

    def set_position_from_tele(self):
        """Set position from telemetry"""
        self.set_position(api.read.lap.distance(), "from telemetry")

    def set_position(self, position: float, source: str):
        """Set position to selected cell"""
        if self.column_selection_count(0) != 1:  # limit to one selected cell
            msg_text = (
                "Select <b>one value</b> from <b>distance</b> column to set position."
            )
            QMessageBox.warning(self, tr("Error"), trm(msg_text))
            return

        if not self.confirm_operation(message=f"Set position at <b>{position}</b> {source}?"):
            return

        pos_curr = round(position, DECIMALS)
        row_index = self.table_notes.currentRow()
        table_item(self.table_notes, row_index, 0, FloatTableItem).setValue(pos_curr)
        self.mark_positions_on_map()
        self.highlight_position_on_map()
        self.table_notes.setCurrentCell(-1, -1)  # deselect to avoid mis-clicking

    def add_notes(self):
        """Add new notes entry"""
        row_index = self.table_notes.rowCount()
        self.add_table_row(row_index)
        self.table_notes.setCurrentCell(row_index, 0)

    def insert_notes(self, row_offset: int = 0):
        """Insert new notes entry"""
        row_index = self.table_notes.currentRow() + row_offset
        self.add_table_row(row_index)
        self.table_notes.setCurrentCell(row_index, 0)

    def sort_notes(self):
        """Sort notes by distance in ascending order"""
        if self.table_notes.rowCount() > 1:
            self.table_notes.sortItems(0)
            self.set_modified()

    def delete_notes(self):
        """Delete notes entry"""
        selected_rows = set(data.row() for data in self.table_notes.selectedIndexes())
        if not selected_rows:
            QMessageBox.warning(self, tr("Error"), tr("No data selected."))
            return

        if not self.confirm_operation(message=tr("<b>Delete selected rows?</b>")):
            return

        for row_index in sorted(selected_rows, reverse=True):
            self.table_notes.removeRow(row_index)
        self.set_modified()
        self.mark_positions_on_map()

    def capture_notes(self) -> tuple:
        """Capture notes table for undo history"""
        return tuple(self.notes_header), tuple(
            tuple(note.items()) for note in self.update_notes_temp(self.notes_header)
        )

    def restore_notes(self, state: tuple):
        """Restore notes table from undo history"""
        header, notes = state
        self.notes_header = header
        self.refresh_table([dict(note) for note in notes])

    def update_notes_temp(self, table_header: tuple[str, ...]):
        """Update temporary changes to notes temp"""
        temp = (
            {
                fieldname: self.parse_notes(
                    self.table_notes.item(row_index, column_index), column_index
                )
                for column_index, fieldname in enumerate(table_header)
            }
            for row_index in range(self.table_notes.rowCount())
        )
        return list(temp)

    @staticmethod
    def parse_notes(item, index: int):
        """Parse notes"""
        if index == 0:
            return round(item.value(), DECIMALS)
        return item.text()

    def saving(self):
        """Save notes"""
        self.save_notes(self.notes_type)

    def save_notes(self, notes_type: str):
        """Save notes"""
        self.sort_notes()

        filename = self.filename_entry.text()
        if not filename:  # try find track name if file name was not set
            filename = self.get_track_name()

        filename_full, file_filter = QFileDialog.getSaveFileName(
            self,
            dir=set_file_path(notes_type, filename),
            filter=set_notes_filter(notes_type),
        )
        if not filename_full:  # save canceled
            return

        output_header = set_notes_header_by_filter(file_filter)
        if not output_header:  # fallback to current header
            output_header = self.notes_header
        output_notes = self.update_notes_temp(output_header)

        if not output_notes:
            QMessageBox.warning(self, tr("Error"), tr("Nothing to save."))
            return

        filepath = os.path.dirname(filename_full) + "/"
        filename = os.path.basename(filename_full)
        save_notes_file(
            filepath=filepath,
            filename=filename,
            table_header=output_header,
            dataset=output_notes,
            metadata=self.notes_metadata,
            writer=set_notes_writer(file_filter),
        )
        self.filename_entry.setText(filename)
        self.set_unmodified()
        msg_text = f"Notes saved at:<br><b>{filename_full}</b>"
        QMessageBox.information(self, tr("Saved"), trm(msg_text))

    def column_selection_count(self, column_index: int = 0) -> int:
        """Column selection count"""
        row_count = 0
        for data in self.table_notes.selectedIndexes():
            if data.column() == column_index:
                row_count += 1
            else:
                return 0
        return row_count

    def verify_input(self, row_index: int, column_index: int):
        """Verify input value"""
        if self._verify_enabled:
            self.set_modified()
            if column_index == 0:
                item = table_item(self.table_notes, row_index, column_index)
                item.validate()
                self.mark_positions_on_map()

    def set_context_menu(self):
        """Set context menu"""
        menu = QMenu(self)
        menu.addAction(tr("Highlight on Map"))
        menu.addSeparator()
        tag_menu = menu.addMenu(tr("Add Tag"))
        tag_menu.addAction(tr("Pit"))
        menu.addAction(tr("Clear Tag"))
        menu.addSeparator()
        menu.addAction(tr("Set from Map"))
        menu.addAction(tr("Set from Telemetry"))
        menu.addSeparator()
        menu.addAction(tr("Insert Row Above"))
        menu.addAction(tr("Insert Row Below"))
        menu.addAction(tr("Delete Rows"))
        return menu

    def open_context_menu(self, position: QPoint):
        """Open context menu"""
        item = self.table_notes.itemAt(position)
        if not item or item.column() == 3:
            return

        position += QPoint(  # position correction from header
            self.table_notes.verticalHeader().width(),
            self.table_notes.horizontalHeader().height(),
        )
        selected_action = self.table_context_menu.exec(
            self.table_notes.mapToGlobal(position))
        if not selected_action:
            return

        action = untr(selected_action.text())
        if action == "Highlight on Map":
            self.mark_positions_on_map()
            self.highlight_position_on_map()
        elif action == "Pit":
            self.add_tag(TAG_PITNOTES)
        elif action == "Clear Tag":
            self.clear_tag()
        elif action == "Set from Map":
            self.set_position_from_map()
        elif action == "Set from Telemetry":
            self.set_position_from_tele()
        elif action == "Insert Row Above":
            self.insert_notes(0)
        elif action == "Insert Row Below":
            self.insert_notes(1)
        elif action == "Delete Rows":
            self.delete_notes()

    def add_tag(self, tag_name: str):
        """Add tag"""
        column_index = 3
        row_indexes = set(data.row() for data in self.table_notes.selectedIndexes())
        for row_index in row_indexes:
            item = table_item(self.table_notes, row_index, column_index)
            text = item.text()
            if tag_name not in text:
                item.setText(text + tag_name)

    def clear_tag(self):
        """Remove all tags"""
        if self.confirm_operation(tr("Clear Tag"), tr("Clear all tags from selected notes?")):
            column_index = 3
            row_indexes = set(data.row() for data in self.table_notes.selectedIndexes())
            for row_index in row_indexes:
                item = table_item(self.table_notes, row_index, column_index)
                item.setText("")
                #item.setText(item.text().replace(tag_name, ""))

    def highlight_position_on_map(self):
        """Highlight selected position on map"""
        value = table_item(self.table_notes, self.table_notes.currentRow(), 0, FloatTableItem).value()
        self.trackmap.spinbox_pos_dist.setValue(int(value))
        self.trackmap.update_highlighted_coords()

    def mark_positions_on_map(self):
        """Mark all positions on map"""
        temp_coords = set(
            table_item(self.table_notes, row_index, 0, FloatTableItem).value()
            for row_index in range(self.table_notes.rowCount())
        )
        self.trackmap.update_marked_coords(temp_coords)

    def get_track_name(self) -> str:
        """Get track name"""
        track_name = api.read.session.track_name()
        if not track_name:
            return self.trackmap.map_filename
        return track_name


class MetaDataEditor(BaseDialog):
    """Metadata editor"""

    def __init__(self, parent, metadata: dict):
        super().__init__(parent)
        self.setWindowTitle(tr("Metadata Info"))

        self.metadata = metadata
        self.option_metadata = {}

        # Label & Edit
        layout_option = QGridLayout()
        layout_option.setAlignment(Qt.AlignmentFlag.AlignTop)

        for index, fieldname in enumerate(metadata):
            desc_label = QLabel(f"{fieldname.capitalize()}:")
            edit_entry = QLineEdit()
            edit_entry.setText(metadata[fieldname])
            layout_option.addWidget(desc_label, index, 0)
            layout_option.addWidget(edit_entry, index, 1)
            self.option_metadata[fieldname] = edit_entry

        # Button
        button_save = QPushButton(tr("Ok"))
        button_save.clicked.connect(self.saving)

        button_close = QPushButton(tr("Close"))
        button_close.clicked.connect(self.reject)

        layout_button = QHBoxLayout()
        layout_button.addStretch(1)
        layout_button.addWidget(button_save)
        layout_button.addWidget(button_close)

        # Set layout
        layout_main = QVBoxLayout()
        layout_main.addLayout(layout_option)
        layout_main.addLayout(layout_button)
        self.setLayout(layout_main)
        self.setMinimumWidth(UIScaler.size(38))
        self.setFixedHeight(self.sizeHint().height())

    def saving(self):
        """Save metadata"""
        self.metadata.update({key:edit.text() for key, edit in self.option_metadata.items()})
        self.accept()
