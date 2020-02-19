from aqt import mw
from aqt.qt import *
from anki.consts import *
import aqt
from aqt.utils import showWarning, openHelp, getOnlyText, askUser, showInfo
from anki.utils import json
from .config import getUserOption, writeConfig, getDefaultConfig

class FieldDialog(QDialog):

    def __init__(self, mw, fields, ord=0, parent=None):
        QDialog.__init__(self, parent or mw) #, Qt.Window)
        self.specialFields = fields

        self.mw = aqt.mw
        self.parent = parent or mw

        self.col = self.mw.col
        self.mw.checkpoint(_("Fields"))
        self.form = aqt.forms.fields.Ui_Dialog()
        self.form.setupUi(self)
        self.setWindowTitle(_("Special Fields") )
        self.form.buttonBox.button(QDialogButtonBox.Help).setAutoDefault(False)
        self.form.buttonBox.button(QDialogButtonBox.Close).setAutoDefault(False)
        self.currentIdx = None
        self.fillFields()
        self.setupSignals()
        self.form.fieldList.setCurrentRow(0)

        conf = getUserOption(refresh=True)
        allSpecial = conf["All fields are special"]
        combTaging = conf["Combine tagging"]
        updateDesc = conf["update deck description"]
        updateStyle = conf["update note styling"]
        upOnlyIfNewer = conf["update only if newer"]

        self.b1 = QCheckBox("All fields are special", self)
        self.form._2.addWidget(self.b1)
        self.b1.setChecked(allSpecial)

        self.b2 = QCheckBox("Combine tagging", self)
        self.form._2.addWidget(self.b2)
        self.b2.setChecked(combTaging)

        self.b3 = QCheckBox("Update deck description", self)
        self.form._2.addWidget(self.b3)
        self.b3.setChecked(updateDesc)

        self.b4 = QCheckBox("Update note styling", self)
        self.form._2.addWidget(self.b4)
        self.b4.setChecked(updateStyle)

        self.b5 = QCheckBox("Update only if newer", self)
        self.form._2.addWidget(self.b5)
        self.b5.setChecked(upOnlyIfNewer)

        self.b6 = QPushButton("Restore Defaults", self)
        self.form._2.addWidget(self.b6)

        self.b1.clicked.connect(self.b1_press)
        self.b2.clicked.connect(self.b2_press)
        self.b3.clicked.connect(self.b3_press)
        self.b4.clicked.connect(self.b4_press)
        self.b5.clicked.connect(self.b5_press)
        self.b6.clicked.connect(self.restoreConfig)
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
        self.resize(400, 200)

        self.exec_()

        

    ##########################################################################

    def fillFields(self):
        self.currentIdx = None
        self.form.fieldList.clear()

        b = getUserOption()
        fields = b["Special field"]

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
        conf = getUserOption()
        conf["All fields are special"] = val
        writeConfig()

    def b2_press(self):
        val = self.b2.isChecked()
        conf = getUserOption()
        conf["Combine tagging"] = val
        writeConfig()

    def b3_press(self):
        val = self.b3.isChecked()
        conf = getUserOption()
        conf["update deck description"] = val
        writeConfig()

    def b4_press(self):
        val = self.b4.isChecked()
        conf = getUserOption()
        conf["update note styling"] = val
        writeConfig()

    def b5_press(self):
        val = self.b5.isChecked()
        conf = getUserOption()
        conf["update only if newer"] = val
        writeConfig()

    def restoreConfig(self):
        conf = getDefaultConfig()
        addon = __name__.split(".")[0]
        mw.addonManager.writeAddonMeta(addon, conf)

        allSpecial = conf["All fields are special"]
        combTaging = conf["Combine tagging"]
        updateDesc = conf["update deck description"]
        updateStyle = conf["update note styling"]
        upOnlyIfNewer = conf["update only if newer"]

        self.b1.setChecked(allSpecial)
        self.b2.setChecked(combTaging)
        self.b3.setChecked(updateDesc)
        self.b4.setChecked(updateStyle)
        self.b5.setChecked(upOnlyIfNewer)
        

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
        conf = getUserOption()
        fields = conf["Special field"]
        self.specialFields = fields
        self.form.fieldList.setCurrentRow(len(self.specialFields)-1)
        writeConfig()

    def onDelete(self):
        f = self.specialFields[self.form.fieldList.currentRow()]
        self.specialFields.remove(f)
        self.saveField()
        self.fillFields()
        writeConfig()

    def saveField(self):

        if self.currentIdx is None:
            return
        
        conf = getUserOption()
        fields = conf["Special field"]
        fields = self.specialFields
        writeConfig()

    def onHelp(self):
        openHelp("fields")



def onFields(self):
    # Use existing FieldDialog as template for UI.
    b = getUserOption()
    fields = b["Special field"]
    FieldDialog(mw, fields, parent=self)


action = QAction("Special Fields", mw)
action.triggered.connect(onFields)
mw.form.menuTools.addAction(action)


