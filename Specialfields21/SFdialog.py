from aqt import mw
from aqt.qt import *
from anki.consts import *
import aqt
from aqt.utils import showWarning, openHelp, getOnlyText, askUser, showInfo
from anki.utils import json
from .config import getUserOption, writeConfig

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

        # removing irrelevant stuff from general "fields.ui" template
        self.form._2.setParent(None)
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