# -*- coding: utf-8 -*-
#
# Copyright © Spyder Project Contributors
# Licensed under the terms of the MIT License
# (see spyder/__init__.py for details)

"""
Working Directory widget.
"""

# Standard library imports
import logging
import os
import os.path as osp
import re

# Third party imports
from qtpy.compat import getexistingdirectory
from qtpy.QtCore import QSize, Signal, Slot
from qtpy.QtWidgets import QSizePolicy, QWidget

# Local imports
from spyder.api.config.decorators import on_conf_change
from spyder.api.translations import _
from spyder.api.widgets.main_container import PluginMainContainer
from spyder.api.widgets.toolbars import ApplicationToolbar
from spyder.config.base import get_home_dir
from spyder.plugins.toolbar.api import ApplicationToolbars
from spyder.utils.misc import getcwd_or_home
from spyder.utils.stylesheet import APP_TOOLBAR_STYLESHEET
from spyder.widgets.comboboxes import PathComboBox


# Logging
logger = logging.getLogger(__name__)


# ---- Constants
# ----------------------------------------------------------------------------
class WorkingDirectoryActions:
    Previous = 'previous_action'
    Next = "next_action"
    Browse = "browse_action"
    Parent = "parent_action"


class WorkingDirectoryToolbarSections:
    Main = "main_section"


class WorkingDirectoryToolbarItems:
    PathComboBox = 'path_combo'


# ---- Widgets
# ----------------------------------------------------------------------------
class WorkingDirectoryComboBox(PathComboBox):
    """Working directory combo box."""

    edit_goto = Signal(str, int, str)

    def __init__(self, parent):
        super().__init__(
            parent,
            adjust_to_contents=False,
            id_=WorkingDirectoryToolbarItems.PathComboBox,
            elide_text=True
        )

        # Set min width
        self.setMinimumWidth(140)

    def sizeHint(self):
        """Recommended size when there are toolbars to the right."""
        return QSize(400, 10)

    def enterEvent(self, event):
        """Set current path as the tooltip of the widget on hover."""
        self.setToolTip(self.currentText())

    def focusOutEvent(self, event):
        """
        Handle focus out event validating current path.
        """
        self.add_current_text_if_valid()
        super().focusOutEvent(event)

    # ---- Own methods
    def valid_text(self):
        """Get valid version of current text."""
        directory = self.currentText()
        file = None
        line_number = None

        if directory:
            # Search for path/to/file.py:10 where 10 is the line number
            match = re.fullmatch(r"(?:(\d+):)?(.+)", directory[::-1])
            if match:
                line_number, directory = match.groups()
                if line_number:
                    line_number = int(line_number[::-1])
                directory = directory[::-1]

            directory = osp.abspath(directory)

            # If the directory is actually a file, open containing directory
            if osp.isfile(directory):
                file = directory
                directory = osp.dirname(directory)

            # If the directory name is malformed, open parent directory
            if not osp.isdir(directory):
                directory = osp.dirname(directory)

            if self.is_valid(directory):
                return directory, file, line_number

        return self.selected_text, file, line_number

    def add_current_text_if_valid(self):
        """Add current text to combo box history if valid."""
        directory, file, line_number = self.valid_text()
        if file:
            self.edit_goto.emit(file, line_number, "")
        if directory and directory != self.currentText():
            self.add_text(directory)
            self.selected()
        if directory:
            return True


# ---- Container
# ----------------------------------------------------------------------------
class WorkingDirectorySpacer(QWidget):
    ID = 'working_directory_spacer'

    def __init__(self, parent):
        super().__init__(parent)

        # Make it expand
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Set style
        self.setStyleSheet(str(APP_TOOLBAR_STYLESHEET))


# ---- Container
# ----------------------------------------------------------------------------
class WorkingDirectoryContainer(PluginMainContainer):
    """Container for the working directory toolbar."""

    # Signals
    sig_current_directory_changed = Signal(str)
    """
    This signal is emitted when the current directory has changed.

    Parameters
    ----------
    new_working_directory: str
        The new working directory path.
    """

    edit_goto = Signal(str, int, str)
    """
    This signal is emitted when a file has been requested.

    Parameters
    ----------
    filename: str
        The file to open.
    line: int
        The line to go to.
    word: str
        The word to go to in the line.
    """

    # ---- PluginMainContainer API
    # ------------------------------------------------------------------------
    def setup(self):
        # Variables
        self.history = self.get_conf('history', [])
        self.histindex = None
        self.server_id = None

        # Widgets
        title = _('Current working directory')
        self.toolbar = ApplicationToolbar(
            self,
            ApplicationToolbars.WorkingDirectory,
            title
        )
        self.pathedit = WorkingDirectoryComboBox(self)
        spacer = WorkingDirectorySpacer(self)

        # Widget Setup
        self.toolbar.setWindowTitle(title)
        self.toolbar.setObjectName(title)
        self.pathedit.setMaxCount(self.get_conf('working_dir_history'))
        self.pathedit.selected_text = self.pathedit.currentText()

        # Signals
        self.pathedit.open_dir.connect(self.chdir)
        self.pathedit.edit_goto.connect(self.edit_goto)
        self.pathedit.textActivated.connect(self.chdir)

        # Actions
        # TODO: Previous and Next actions not being used?
        self.previous_action = self.create_action(
            WorkingDirectoryActions.Previous,
            text=_('Back'),
            tip=_('Back'),
            icon=self.create_icon('previous'),
            triggered=self._previous_directory,
        )
        self.next_action = self.create_action(
            WorkingDirectoryActions.Next,
            text=_('Next'),
            tip=_('Next'),
            icon=self.create_icon('next'),
            triggered=self._next_directory,
        )
        self.browse_action = self.create_action(
            WorkingDirectoryActions.Browse,
            text=_('Browse a working directory'),
            tip=_('Browse a working directory'),
            icon=self.create_icon('DirOpenIcon'),
            triggered=self._select_directory,
        )
        self.parent_action = self.create_action(
            WorkingDirectoryActions.Parent,
            text=_('Change to parent directory'),
            tip=_('Change to parent directory'),
            icon=self.create_icon('up'),
            triggered=self._parent_directory,
        )

        for item in [
            spacer,
            self.pathedit,
            self.browse_action,
            self.parent_action,
        ]:
            self.add_item_to_toolbar(
                item,
                self.toolbar,
                section=WorkingDirectoryToolbarSections.Main,
            )

    def update_actions(self):
        if self.server_id:
            self.pathedit.setEnabled(False)
            self.browse_action.setEnabled(False)
            self.parent_action.setEnabled(False)
        else:
            self.pathedit.setEnabled(True)
            self.browse_action.setEnabled(True)
            self.parent_action.setEnabled(True)

            # TODO: Seems like these actions are not used
            self.previous_action.setEnabled(
                self.histindex is not None and self.histindex > 0)
            self.next_action.setEnabled(
                self.histindex is not None
                and self.histindex < len(self.history) - 1
            )

    @on_conf_change(option='history')
    def on_history_update(self, value):
        self.history = value

    # ---- Private API
    # ------------------------------------------------------------------------
    def _get_init_workdir(self):
        """
        Get the working directory from our config system or return the user
        home directory if none can be found.

        Returns
        -------
        str:
            The initial working directory.
        """
        workdir = get_home_dir()

        if self.get_conf('startup/use_project_or_home_directory'):
            workdir = get_home_dir()
        elif self.get_conf('startup/use_fixed_directory'):
            workdir = self.get_conf('startup/fixed_directory')

            # If workdir can't be found, restore default options.
            if not osp.isdir(workdir):
                self.set_conf('startup/use_project_or_home_directory', True)
                self.set_conf('startup/use_fixed_directory', False)
                workdir = get_home_dir()

        return workdir

    @Slot()
    def _select_directory(self):
        """
        Select working directory.

        Parameters
        ----------
        directory: str, optional
            The directory to change to.

        Notes
        -----
        If directory is None, a get directory dialog will be used.
        """
        self.sig_redirect_stdio_requested.emit(False)
        directory = getexistingdirectory(
            self,
            _("Select directory"),
            getcwd_or_home(),
        )
        self.sig_redirect_stdio_requested.emit(True)

        if directory:
            self.chdir(directory)

    @Slot()
    def _previous_directory(self):
        """Select the previous directory."""
        self.histindex -= 1
        self.chdir(directory='', browsing_history=True)

    @Slot()
    def _next_directory(self):
        """Select the next directory."""
        self.histindex += 1
        self.chdir(directory='', browsing_history=True)

    @Slot()
    def _parent_directory(self):
        """Change working directory to parent one."""
        self.chdir(osp.join(getcwd_or_home(), osp.pardir))

    # ---- Public API
    # ------------------------------------------------------------------------
    def get_workdir(self):
        """
        Get the current working directory.

        Returns
        -------
        str:
            The current working directory.
        """
        return self.pathedit.currentText()

    @Slot(str)
    @Slot(str, bool)
    @Slot(str, bool, bool)
    @Slot(str, bool, bool, str)
    def chdir(
        self, directory, browsing_history=False, emit=True, server_id=None
    ):
        """
        Set `directory` as working directory.

        Parameters
        ----------
        directory: str
            The new working directory.
        browsing_history: bool, optional
            Add the new `directory` to the browsing history. Default is False.
        emit: bool, optional
            Emit a signal when changing the working directory.
            Default is True.
        server_id: str, optional
            The server identification from where the directory is reachable.
            Default is None.
        """
        self.server_id = server_id

        if directory and not server_id:
            directory = osp.abspath(str(directory))

        # Working directory history management
        # TODO: Each host/server requires an independent history
        # Possibly handle current history with `history` as it is but populate it
        # with entry from a dict that contains all hosts histories depending
        # on server_id value passed:
        #       {"<server_id>": {"history": []}}
        if not server_id:
            if browsing_history:
                directory = self.history[self.histindex]
            elif directory in self.history:
                self.histindex = self.history.index(directory)
            else:
                if self.histindex is None:
                    self.history = []
                else:
                    self.history = self.history[:self.histindex + 1]

                self.history.append(directory)
                self.histindex = len(self.history) - 1

        # Changing working directory
        try:
            logger.debug(f'Setting cwd to {directory}')
            if not server_id:
                os.chdir(directory)
            self.pathedit.add_text(directory)
            self.update_actions()

            if emit:
                self.sig_current_directory_changed.emit(directory)
        except OSError:
            self.history.pop(self.histindex)

    def get_history(self):
        """
        Get the current history list.

        Returns
        -------
        list
            List of string paths.
        """
        return [str(self.pathedit.itemText(index)) for index
                in range(self.pathedit.count())]

    def set_history(self, history, cli_workdir=None):
        """
        Set the current history list.

        Parameters
        ----------
        history: list
            List of string paths.
        cli_workdir: str or None
            Working directory passed on the command line.
        """
        self.set_conf('history', history)
        if history:
            self.pathedit.addItems(history)

        if cli_workdir is None:
            workdir = self._get_init_workdir()
        else:
            logger.debug('Setting cwd passed from the command line')
            workdir = cli_workdir

            # In case users pass an invalid directory on the command line
            if not osp.isdir(workdir):
                workdir = get_home_dir()

        self.chdir(workdir)
