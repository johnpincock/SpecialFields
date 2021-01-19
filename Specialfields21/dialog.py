import copy
import webbrowser
import aqt
from anki.consts import *
from anki.utils import json
from aqt import mw
from aqt.qt import *
from aqt.utils import askUser, getOnlyText, openHelp, showInfo, showWarning

from .config import getDefaultConfig, getUserOption, writeConfig

# #########################################################
#
# See this video for how to use this add-on: https://youtu.be/cg-tQ6Ut0IQ
#
# #########################################################



fullconfig = getUserOption()
configs = getUserOption("configs")

addon = __name__.split(".")[0]


class FieldDialog(QDialog):

    def __init__(self, mw, fields, ord=0, parent=None):
        QDialog.__init__(self, parent or mw)  # , Qt.Window)
        self.specialFields = fields

        self.mw = aqt.mw
        self.parent = parent or mw

        self.col = self.mw.col
        self.mw.checkpoint(_("Fields"))
        self.form = aqt.forms.fields.Ui_Dialog()
        self.form.setupUi(self)
        self.setWindowTitle(_("Special Fields"))
        self.form.buttonBox.button(QDialogButtonBox.Help).setAutoDefault(False)
        if self.form.buttonBox.button(QDialogButtonBox.Close):
            self.form.buttonBox.button(QDialogButtonBox.Close).setAutoDefault(False)
        else:
            self.form.buttonBox.button(QDialogButtonBox.Close)
        self.currentIdx = None
        self.fillFields()
        self.setupSignals()
        self.form.fieldList.setCurrentRow(0)

        self.setupOptions()
        # self.form.buttonBox.button(QRadioButton("Upload Collection", self))
        # self.upload_but.clicked.connect(self.uploadBut)

        # removing irrelevant stuff from general "fields.ui" template
        # self.form._2.setParent(None)
        self.form.rtl.setParent(None)
        self.form.fontFamily.setParent(None)
        self.form.fontSize.setParent(None)
        self.form.sticky.setParent(None)
        self.form.label_18.setParent(None)
        self.form.fontFamily.setParent(None)
        self.form.fieldRename.setParent(None)
        self.form.fieldPosition.setParent(None)
        self.form.label_5.setParent(None)
        self.form.sortField.setParent(None)
        self.resize(500, 300)

        self.exec_()

    ##########################################################################
    def setupOptions(self):

        allSpecial = configs["current config"]["All fields are special"]
        combTaging = configs["current config"]["Combine tagging"]
        updateDesc = configs["current config"]["update deck description"]
        updateStyle = configs["current config"]["update note styling"]
        upOnlyIfNewer = configs["current config"]["update only if newer"]

        self.b1 = QCheckBox("All fields are special", self)
        self.form._2.addWidget(self.b1)
        self.b1.setChecked(allSpecial)

        self.b2 = QCheckBox("Combine tagging", self)
        self.form._2.addWidget(self.b2)
        self.b2.setChecked(combTaging)
        self.b2.setToolTip('<div style="background:red;">If this is unchecked, all tags except those containing %%keep%% will be updated</div>')

        self.b3 = QCheckBox("Update deck description", self)
        self.form._2.addWidget(self.b3)
        self.b3.setChecked(updateDesc)

        self.b4 = QCheckBox("Update note styling", self)
        self.form._2.addWidget(self.b4)
        self.b4.setChecked(updateStyle)

        self.b5 = QCheckBox("Update only if newer", self)
        self.form._2.addWidget(self.b5)
        self.b5.setChecked(upOnlyIfNewer)

        self.b6 = QPushButton("Set Defaults", self)
        self.form._2.addWidget(self.b6)

        self.b7 = QPushButton("'Update' Settings", self)
        self.form._2.addWidget(self.b7)

        self.b8 = QPushButton("'Import Tags' Settings", self)
        self.form._2.addWidget(self.b8)

        self.b9 = QPushButton("Restore Defaults", self)
        self.form._2.addWidget(self.b9)

        self.b1.clicked.connect(self.b1_press)
        self.b2.clicked.connect(self.b2_press)
        self.b3.clicked.connect(self.b3_press)
        self.b4.clicked.connect(self.b4_press)
        self.b5.clicked.connect(self.b5_press)
        self.b6.clicked.connect(self.setConfig)  # make this class
        self.b7.clicked.connect(self.updatePresetConfig)
        self.b8.clicked.connect(self.importPresetConfig)
        self.b9.clicked.connect(self.restoreConfig)  # change this class

    def fillFields(self):
        self.currentIdx = None
        self.form.fieldList.clear()

        fields = configs["current config"]["Special field"]

        for c, f in enumerate(fields):
            self.form.fieldList.addItem("{}: {}".format(c+1, f
                                                        ))

    def setupSignals(self):
        f = self.form
        f.fieldList.currentRowChanged.connect(self.onRowChange)
        f.fieldAdd.clicked.connect(self.onAdd)
        f.fieldDelete.clicked.connect(self.onDelete)
        f.buttonBox.helpRequested.connect(self.onHelp)

    def b1_press(self):
        val = self.b1.isChecked()
        configs["current config"]["All fields are special"] = val
        mw.addonManager.writeConfig(__name__, fullconfig)

    def b2_press(self):
        val = self.b2.isChecked()
        configs["current config"]["Combine tagging"] = val
        mw.addonManager.writeConfig(__name__, fullconfig)

    def b3_press(self):
        val = self.b3.isChecked()
        configs["current config"]["update deck description"] = val
        mw.addonManager.writeConfig(__name__, fullconfig)

    def b4_press(self):
        val = self.b4.isChecked()
        configs["current config"]["update note styling"] = val
        mw.addonManager.writeConfig(__name__, fullconfig)

    def b5_press(self):
        val = self.b5.isChecked()
        configs["current config"]["update only if newer"] = val
        mw.addonManager.writeConfig(__name__, fullconfig)

    def restoreConfig(self):
        addon = __name__.split(".")[0]
        configs["current config"] = copy.deepcopy(
            configs["user default config"])

        mw.addonManager.writeConfig(__name__, fullconfig)

        allSpecial = configs["current config"]["All fields are special"]
        combTaging = configs["current config"]["Combine tagging"]
        updateDesc = configs["current config"]["update deck description"]
        updateStyle = configs["current config"]["update note styling"]
        upOnlyIfNewer = configs["current config"]["update only if newer"]

        self.b1.setChecked(allSpecial)
        self.b2.setChecked(combTaging)
        self.b3.setChecked(updateDesc)
        self.b4.setChecked(updateStyle)
        self.b5.setChecked(upOnlyIfNewer)
        showInfo("Settings Restored")
        self.close()
        onFieldsExecute()

    def setConfig(self):
        configs["user default config"] = copy.deepcopy(
            configs["current config"])
        mw.addonManager.writeConfig(__name__, fullconfig)

        allSpecial = configs["current config"]["All fields are special"]
        combTaging = configs["current config"]["Combine tagging"]
        updateDesc = configs["current config"]["update deck description"]
        updateStyle = configs["current config"]["update note styling"]
        upOnlyIfNewer = configs["current config"]["update only if newer"]

        self.b1.setChecked(allSpecial)
        self.b2.setChecked(combTaging)
        self.b3.setChecked(updateDesc)
        self.b4.setChecked(updateStyle)
        self.b5.setChecked(upOnlyIfNewer)
        showInfo("Settings Restored")
        self.close()
        onFieldsExecute()

    def importPresetConfig(self):
        addon = __name__.split(".")[0]

        configs["current config"]["All fields are special"] = True
        configs["current config"]["Combine tagging"] = True
        configs["current config"]["update deck description"] = False
        configs["current config"]["update note styling"] = False
        configs["current config"]["update only if newer"] = False

        mw.addonManager.writeConfig(__name__, fullconfig)

        allSpecial = configs["current config"]["All fields are special"]
        combTaging = configs["current config"]["Combine tagging"]
        updateDesc = configs["current config"]["update deck description"]
        updateStyle = configs["current config"]["update note styling"]
        upOnlyIfNewer = configs["current config"]["update only if newer"]

        if self.b1.isChecked() != allSpecial:
            self.b1.click()
        if self.b2.isChecked() != combTaging:
            self.b2.click()
        if self.b3.isChecked() != updateDesc:
            self.b3.click()
        if self.b4.isChecked() != updateStyle:
            self.b4.click()
        if self.b5.isChecked() != upOnlyIfNewer:
            self.b5.click()

        showInfo("Settings applied for importing tags")

    def updatePresetConfig(self):
        addon = __name__.split(".")[0]
        # mw.addonManager.writeAddonMeta(addon, conf)

        configs["current config"]["All fields are special"] = False
        configs["current config"]["Combine tagging"] = False
        configs["current config"]["update deck description"] = True
        configs["current config"]["update note styling"] = True
        configs["current config"]["update only if newer"] = False

        mw.addonManager.writeConfig(__name__, fullconfig)

        allSpecial = configs["current config"]["All fields are special"]
        combTaging = configs["current config"]["Combine tagging"]
        updateDesc = configs["current config"]["update deck description"]
        updateStyle = configs["current config"]["update note styling"]
        upOnlyIfNewer = configs["current config"]["update only if newer"]

        if self.b1.isChecked() != allSpecial:
            self.b1.click()
        if self.b2.isChecked() != combTaging:
            self.b2.click()
        if self.b3.isChecked() != updateDesc:
            self.b3.click()
        if self.b4.isChecked() != updateStyle:
            self.b4.click()
        if self.b5.isChecked() != upOnlyIfNewer:
            self.b5.click()

        showInfo("Settings applied for updating a deck")

    def onRowChange(self, idx):
        if idx == -1:
            return
        self.saveField()

    def _uniqueName(self, prompt, ignoreOrd=None, old=""):
        txt = getOnlyText(prompt, default=old)
        if not txt:
            return
        for f in self.specialFields:
            if f == txt:
                showWarning(_("That field name is already used."))
                return
        return txt

    def onAdd(self):
        name = self._uniqueName(_("Field name:"))
        if not name:
            return
        self.specialFields = self.specialFields.append(name)
        self.saveField()
        self.fillFields()
        fields = configs["current config"]["Special field"]
        self.specialFields = fields
        self.form.fieldList.setCurrentRow(len(self.specialFields)-1)
        mw.addonManager.writeConfig(__name__, fullconfig)

    def onDelete(self):
        f = self.specialFields[self.form.fieldList.currentRow()]
        self.specialFields.remove(f)
        self.saveField()
        self.fillFields()
        mw.addonManager.writeConfig(__name__, fullconfig)

    def saveField(self):

        if self.currentIdx is None:
            return

        fields = configs["current config"]["Special field"]
        fields = self.specialFields
        mw.addonManager.writeConfig(__name__, fullconfig)

    def onHelp(self):
        #openHelp("fields")
        webbrowser.open('https://youtu.be/cg-tQ6Ut0IQ')



def onFields(self):
    # Use existing FieldDialog as template for UI.
    fields = configs["current config"]["Special field"]
    FieldDialog(mw, fields, parent=self)


def onFieldsExecute():
    onFields(mw)


mw.addonManager.setConfigAction(__name__, onFieldsExecute)
action = QAction("Special Fields", mw)
action.setShortcut(QKeySequence("Ctrl+shift+s"))
action.triggered.connect(onFields)
mw.form.menuTools.addAction(action)
