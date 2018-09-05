from PyQt5.QtWidgets import QFileDialog, QMessageBox
from datatypes import create_lmf, Transcription
from utilities.output import create_lmf_files
from utilities.files import open_folder_dialogue
from widgets.converter import ConverterWidget
from windows.manifest import ManifestWindow
from widgets.table import TABLE_COLUMNS
from widgets.warning import WarningMessage

import json
import logging


class SessionManager(object):
    """
    Session Manager handles session operations, providing functionality for Save, Save As, and Open.
    """

    def __init__(self, converter: ConverterWidget):
        self.session_log = logging.getLogger("SessionManager")
        self.session_filename = None
        self._file_dialog = QFileDialog()
        self.converter = converter

    def open_file(self):
        file_name, _ = self._file_dialog.getOpenFileName(self._file_dialog,
                                                         "Open Hermes Session", "", "hermes (*.hermes)")
        self.session_filename = file_name
        self.session_log.info(f"File opened from: {self.session_filename}")

        with open(file_name, 'r') as f:
            loaded_data = json.loads(f.read())
            self.session_log.info(f"Data loaded: {loaded_data}")

        # Populate manifest in converter data
        self.populate_initial_lmf_fields(loaded_data)

        # Add transcriptions
        self.converter.data.transcriptions = list()
        self.converter.components.filter_table.clear_table()
        for i, word in enumerate(loaded_data['words']):
            self.converter.data.transcriptions.append(Transcription(index=i,
                                                                    transcription=word['transcription'],
                                                                    translation=word['translation'][0],
                                                                    image=word.get('image')[0] if word.get('image') else '',
                                                                    media=word.get('audio')[0] if word.get('audio') else '')
                                                      )
            self.session_log.info(f"Transcription loaded: {self.converter.data.transcriptions[i]}")

        for n in range(len(loaded_data['words']) + 1):
            self.converter.components.filter_table.add_blank_row()
        self.converter.components.filter_table.populate_table(self.converter.data.transcriptions)

    def save_as_file(self):
        file_name, _ = self._file_dialog.getSaveFileName(self._file_dialog,
                                                         "Save As", "mysession.hermes", "hermes (*.hermes)")
        self.session_filename = file_name
        self.create_session_lmf()
        self.session_log.info(f'New File created with Save As: {self.session_filename}')
        self.save_file()

    def save_file(self):
        # If no file then save as
        if not self.session_filename:
            self.save_as_file()
            return

        if not self.converter.data.export_location:
            self.converter.data.export_location = open_folder_dialogue()
        self.session_log.info(f'Export location set: {self.converter.data.export_location}')

        # Empty lmf word list first, otherwise it will duplicate entries.
        self.converter.data.lmf['words'] = list()
        for row in range(self.converter.components.table.rowCount()):
            if self.converter.components.table.get_cell_value(row, TABLE_COLUMNS["Transcription"]):
                create_lmf_files(row, self.converter.data)

        # Save to json format
        if self.session_filename:
            with open(self.session_filename, 'w+') as f:
                json.dump(self.converter.data.lmf, f, indent=4)
        else:
            file_not_found_msg()

        self.session_log.info(f"File saved at {self.session_filename}")

    def create_session_lmf(self):
        """Creates a new language manifest file prior to new save file."""
        lmf_manifest_window = ManifestWindow(self.converter.data)
        _ = lmf_manifest_window.exec()
        self.populate_initial_lmf_fields(lmf_manifest_window)
        lmf_manifest_window.close()

    def populate_initial_lmf_fields(self, source) -> None:
        """
        Populates a language manifest file's descriptive data.

        If source is a new ManifestWindow, then user will enter information for languages, and authorship.

        Otherwise, source is a loaded file.

        Keyword arguments:
            source -- ManifestWindow for input, or loaded .hermes (json) file with information to be extracted.
        """
        if isinstance(source, ManifestWindow):
            self.converter.data.lmf = create_lmf(
                transcription_language=source.widgets.transcription_language_field.text(),
                translation_language=source.widgets.translation_language_field.text(),
                author=source.widgets.author_name_field.text()
            )
        else:
            self.converter.data.lmf = create_lmf(
                transcription_language=source['transcription-language'],
                translation_language=source['translation-language'],
                author=source['author']
            )


def file_not_found_msg():
    file_not_found_warn = WarningMessage()
    file_not_found_warn.warning(file_not_found_warn, 'Warning',
                                f'The file you selected was not found.\n',
                                QMessageBox.Ok)
