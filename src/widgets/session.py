from PyQt5.QtWidgets import QFileDialog, QMessageBox
from PyQt5.QtCore import QThread, QTimer
from datatypes import create_lmf, ConverterData, Transcription
from datetime import datetime
from enum import Enum
from tempfile import mkdtemp
from utilities.output import create_lmf_files
from utilities.files import open_folder_dialogue
from widgets.converter import ConverterWidget
from windows.manifest import ManifestWindow
from widgets.table import TABLE_COLUMNS
from widgets.warning import WarningMessage

import json
import logging
import os


class SessionManager(object):
    """
    Session Manager handles session operations, providing functionality for Save, Save As, and Open.
    """

    def __init__(self, converter: ConverterWidget):
        self._file_dialog = QFileDialog()
        self.session_log = logging.getLogger("SessionManager")

        # Converter widget that runs hermes' main operations
        self.converter = converter

        # Save file parameters
        self.session_filename = None

        # Template parameters
        self.template_name = None
        self.template_type = None

        # Autosave parameters
        self.autosave = AutosaveThread(self)
        self.autosaveOn = False
        self.autosave_timer = QTimer()
        # self.autosave.start()

    def open_file(self):
        """Open a .hermes json file and parse into table."""
        if self.template_type:
            self.template_name, _ = self._file_dialog.getOpenFileName(self._file_dialog,
                                                                         "Open Hermes Session", "", "hermes template (*.htemp)")
            self.session_log.info(f"File opened from: {self.template_name}")
            if not self.template_name:
                file_not_found_msg()
                self.session_log.warn("No file selected for open function.")
                return
        else:
            self.session_filename, _ = self._file_dialog.getOpenFileName(self._file_dialog,
                                                             "Open Hermes Session", "", "hermes (*.hermes)")
            self.session_log.info(f"File opened from: {self.session_filename}")
            if not self.session_filename:
                file_not_found_msg()
                self.session_log.warn("No file selected for open function.")
                return

        self.exec_open()

    def exec_open(self):
        """Execs open functionality. Assumes that a file has been successfully found by user."""
        if self.template_type:
            with open(self.template_name, 'r') as f:
                loaded_data = json.loads(f.read())
                self.session_log.info(f"Data loaded: {loaded_data}")
        else:
            with open(self.session_filename, 'r') as f:
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

            if word.get('audio'):
                # An audio file exists, add it.
                self.converter.data.transcriptions[i].set_blank_sample()
                self.converter.data.transcriptions[i].sample.set_sample(word.get('audio')[0])

            self.session_log.info(f"Transcription loaded: {self.converter.data.transcriptions[i]}")

        # Populate table, add an extra blank row for convenience at end.
        for n in range(len(loaded_data['words']) + 1):
            self.converter.components.filter_table.add_blank_row()
        self.converter.components.filter_table.populate_table(self.converter.data.transcriptions)

        # Update user on save success in status bar.
        self.converter.components.status_bar.clearMessage()
        if self.template_type:
            self.converter.components.status_bar.showMessage(f"Data opened from: {self.template_name}", 5000)
        else:
            self.converter.components.status_bar.showMessage(f"Data opened from: {self.session_filename}", 5000)

    def save_as_file(self):
        """User sets new file name + location with QFileDialog, if set then initialise save process."""
        if self.template_type:
            self.template_name, _ = self._file_dialog.getSaveFileName(self._file_dialog,
                                                             "Save Template", "template.htemp", "hermes template (*.htemp)")
        else:
            self.session_filename, _ = self._file_dialog.getSaveFileName(self._file_dialog,
                                                             "Save As", "mysession.hermes", "hermes save (*.hermes)")

        if (self.template_type and not self.template_name) or (not self.template_type and not self.session_filename):
            file_not_found_msg()
            self.session_log.warning("No export location was selected, aborting save.")
            return

        self.save_file()

    def save_file(self):
        # If no file then restart from save as
        if (self.template_type and not self.template_name) or (not self.template_type and not self.session_filename):
            self.save_as_file()
            return

        # User to set export location if it does not exist, abort if not set.
        if not self.export_location():
            no_export_msg()
            self.session_log.warning("No export location was selected, aborting save.")
            return

        # All conditions met at this point, save is ready.
        self.exec_save()

    def exec_save(self):
        """Executes the save function. Assumes that all conditions are ready.

        All saves require a file name setup or loaded, and an export location set in prior steps.
        """
        # Create LMF for this session
        if not self.template_type:
            self.create_session_lmf(self.converter.data)
            # Empty lmf word list first, otherwise it will duplicate entries.
            self.converter.data.lmf['words'] = list()
        else:
            template_data = self.prepare_template_file()
            self.create_session_lmf(template_data)
            template_data.lmf['words'] = list()

        # Progress bar
        self.converter.components.status_bar.clearMessage()
        self.converter.components.progress_bar.show()
        complete_count = 0
        to_save_count = self.converter.components.table.rowCount()

        # Transfer data to lmf file.
        for row in range(self.converter.components.table.rowCount()):
            if self.template_type:
                create_lmf_files(row, template_data)
            elif self.converter.components.table.get_cell_value(row, TABLE_COLUMNS["Transcription"])\
                    or self.converter.components.table.get_cell_value(row, TABLE_COLUMNS["Translation"]):
                create_lmf_files(row, self.converter.data)
            complete_count += 1
            self.converter.components.progress_bar.update_progress(complete_count / to_save_count)

        # Save to json format
        if self.template_type and self.template_name:
            # save template
            with open(self.template_name, 'w+') as f:
                json.dump(template_data.lmf, f, indent=4)
                self.converter.components.status_bar.showMessage(f"Template saved at: {self.template_name}", 5000)
                self.session_log.info(f"File saved at {self.template_name}")
        elif self.session_filename:
            with open(self.session_filename, 'w+') as f:
                # save normal save file
                json.dump(self.converter.data.lmf, f, indent=4)
                self.converter.components.status_bar.showMessage(f"Data saved at: {self.session_filename}", 5000)
                self.session_log.info(f"File saved at {self.session_filename}")
        else:
            self.session_log.error("File not found on exec_save().")
            file_not_found_msg()

        self.converter.components.progress_bar.hide()

    def create_session_lmf(self, data: ConverterData):
        """Creates a new language manifest file prior to new save file."""
        lmf_manifest_window = ManifestWindow(data)
        _ = lmf_manifest_window.exec()
        self.populate_initial_lmf_fields(lmf_manifest_window)
        lmf_manifest_window.close()

    def populate_initial_lmf_fields(self, source) -> None:
        """
        Populates a language manifest file's descriptive data.

        If source is a new ManifestWindow, then user will enter information for languages, and authorship.

        Otherwise, source is a loaded file.

        Args:
            source: ManifestWindow for input, or loaded .hermes (json) file with information to be extracted.
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

    def export_location(self) -> str:
        """User sets an export location if one is not already set.

        Returns:
            Path to export location, else None.
        """
        if self.template_type:
            self.converter.data.export_location = mkdtemp()
        if not self.converter.data.export_location:
            export_init_msg()
            self.converter.data.export_location = open_folder_dialogue()
        self.session_log.info(f'Export location set: {self.converter.data.export_location}')
        return self.converter.data.export_location

    def autosave_thread_function(self):
        """TODO, this is to test that thread initialised"""
        print("Entered Thread")
        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self.run_autosave)
        self.autosave_timer.start(1000 * 60)
        print(f'Time remaining {self.autosave_timer.remainingTime()}')
        print(f'Time active {self.autosave_timer.isActive()}')

    def run_autosave(self):
        """TODO"""
        print(f'Autosaved! {datetime.now().time()}')

    def prepare_template_file(self) -> ConverterData:
        """Prepares template files based on user selection.

        Template files can have the following fields prepared:
        - Transcription
        - Translation
        - Both

        Resources such as audio and images are best added in a resource creation
        session as opposed to fixed with template to allow for transferal of
        templates to other users and/or computers.

        Returns:
            ConverterData with only relevant information as requested by user.
        """
        if not self.template_type:
            no_template_msg()

        # Prepare custom converter data to save
        data = ConverterData()
        data.transcriptions = self.converter.data.transcriptions

        for i in range(len(data.transcriptions)):
            # Clear transcription or translation if only one type wanted.
            if self.template_type is TemplateType.TRANSCRIPTION:
                self.session_log.info(f"We have transcriptions {data.transcriptions}")
                data.transcriptions[i].translation = ""
            elif self.template_type is TemplateType.TRANSLATION:
                data.transcriptions[i].transcription = ""

            # Clear images and sounds
            data.transcriptions[i].image = None
            data.transcriptions[i].sample = None

        return data

    def save_template(self):
        """Asks user to save a template file, user will need to name the template
        file, and then select fields they wish to use for this template.
        """
        self.template_type = TemplateType.TRANSLATION
        self.save_as_file()
        # Go back to normal saving mode.
        self.template_type = None

    def open_template(self):
        """Asks user to open a template file, user will need to name the template
        file, and then select fields they wish to use for this template.
        """
        self.template_type = TemplateType.TRANSLATION
        self.open_file()
        # Go back to normal saving mode.
        self.template_type = None


class AutosaveThread(QThread):
    """Threaded autosave to avoid interruption."""

    def __init__(self, session: SessionManager):
        QThread.__init__(self)
        self.session = session

    def run(self):
        self.session.autosave_thread_function()
        self.exec_()


class TemplateType(Enum):
    """Template types that a user can save."""
    TRANSCRIPTION = 0
    TRANSLATION = 1
    # Represents a template of both transcription and translation types.
    TRANSCRIPT_TRANSLATE = 2


def file_not_found_msg():
    file_not_found_warn = WarningMessage()
    file_not_found_warn.warning(file_not_found_warn, 'Warning',
                                f'No file was found.\n',
                                QMessageBox.Ok)


def no_save_file_msg():
    no_save_file_warn = WarningMessage()
    no_save_file_warn.warning(no_save_file_warn, 'Warning',
                              f"No save file was selected. You must specify a file to save to.\n",
                              QMessageBox.Ok)


def no_export_msg():
    no_save_file_warn = WarningMessage()
    no_save_file_warn.warning(no_save_file_warn, 'Warning',
                              f"No export location found. You must specify an export location.\n",
                              QMessageBox.Ok)


def export_init_msg():
    export_msg = WarningMessage()
    export_msg.information(export_msg, 'Export Location Needed',
                           f"Export location not set, a file dialog will now open. Please choose an export location.\n",
                           QMessageBox.Ok)

def no_template_msg():
    export_msg = WarningMessage()
    export_msg.information(export_msg, 'Warning',
                           f"No Template Type selected, template creation aborted.\n",
                           QMessageBox.Ok)
