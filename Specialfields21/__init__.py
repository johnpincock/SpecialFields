from aqt import mw
from anki.lang import _

from anki.utils import json
from anki.importing import Anki2Importer

from .config import getUserOption

# #########################################################
# How to use:
# Go Tools -> Manage Note types..
# add a new note type 
# choose a name
# select note type
# click "Fields.."
# Add Field
# Use the exact same name as you have set for SPECIAL_FIELD below... default is "Lecture Notes"
# Now when you export, your special field notes will be kept with you and not exported
# #########################################################

GUID = 1
MID = 2
MOD = 3


def newImportNotes(self):
    # build guid -> (id,mod,mid) hash & map of existing note ids
    self._notes = {}
    existing = {}
    for id, guid, mod, mid in self.dst.db.execute(
        "select id, guid, mod, mid from notes"):
        self._notes[guid] = (id, mod, mid)
        existing[id] = True
    # we may need to rewrite the guid if the model schemas don't match,
    # so we need to keep track of the changes for the card import stage
    self._changedGuids = {}
    # we ignore updates to changed schemas. we need to note the ignored
    # guids, so we avoid importing invalid cards
    self._ignoredGuids = {}
    # iterate over source collection
    add = []
    update = []
    dirty = []
    usn = self.dst.usn()
    dupes = 0
    dupesIgnored = []
    dupesIdentical = []
    total = 0
    ########################################################################
    # check if any models with special field exist
    midCheck= []
    models = mw.col.db.scalar("""select models from col""")
    b = json.loads(models)
    a = list(b.values())
    for i in a:
        fields = i["flds"]
        for n in fields:
            if n['name'] in getUserOption("Special field", []) or getUserOption("All fields are special", False):
                midCheck.append(str(i["id"]))
    ########################################################################

    for note in self.src.db.execute(
        "select * from notes"):
        total += 1
        # turn the db result into a mutable list
        note = list(note)
        shouldAdd = self._uniquifyNote(note)
        if shouldAdd:
            # ensure id is unique
            while note[0] in existing:
                note[0] += 999
            existing[note[0]] = True
            # bump usn
            note[4] = usn
            # update media references in case of dupes
            note[6] = self._mungeMedia(note[MID], note[6])
            add.append(note)
            dirty.append(note[0])
            # note we have the added the guid
            self._notes[note[GUID]] = (note[0], note[3], note[MID])
        else:
            # a duplicate or changed schema - safe to update?
            dupes += 1
            if self.allowUpdate:
                oldNid, oldMod, oldMid = self._notes[note[GUID]]
                # will update if incoming note more recent
                if oldMod < note[MOD] or (not getUserOption("update only if newer", True)):
                    # safe if note types identical
                    if oldMid == note[MID]:
                        # incoming note should use existing id
                        note[0] = oldNid
                        note[4] = usn
                        note[6] = self._mungeMedia(note[MID], note[6])
                        update.append(note)
                        dirty.append(note[0])
                    else:
                        dupesIgnored.append("%s: %s" % (
                            self.col.models.get(oldMid)['name'],
                            note[6].replace("\x1f", ",")
                        ))
                        self._ignoredGuids[note[GUID]] = True
                else:
                        dupesIdentical.append(note)


    newUpdate = []
    for row in update:
        oldnote = mw.col.getNote(row[0]) 
        newTags = [t for t in row[5].replace('\u3000', ' ').split(" ") if t]
        for tag in oldnote.tags:
            for i in newTags:
                if i.lower() == tag.lower():
                    tag = i
            newTags.append(tag)

        newTags = set(newTags)
        togetherTags = " %s " % " ".join(newTags)
        mid = str(row[2])
        if mid in midCheck:
            model = mw.col.models.get(mid)
            specialFields = getUserOption("Special field", [])
            if getUserOption("All fields are special", False):
                specialFields = [fld['name'] for fld in model['flds']]
            trow = list(row)                     # if this note belongs to a model with "Special Field"
            for i in specialFields:
                try:
                    row = list(row)
                    items = mw.col.getNote(row[0]).items()
                    fieldOrd = [item for item in items if item[0] == i]
                    fieldOrd = items.index(fieldOrd[0])
                    fields = [item[1] for item in items]
                    splitRow = row[6].split("\x1f")


                    # valueLocal = mw.col.getNote(row[0]).values()
                    # splitRow[indexOfField] = valueLocal[indexOfField]

                    finalrow = ''
                    count=0
                    for a in splitRow:
                        if count == fieldOrd:
                            finalrow += str(fields[fieldOrd]) +"\x1f"
                        else:
                            finalrow += a+"\x1f"
                        count = count + 1

                    def rreplace(s, old, new, occurrence):
                        li = s.rsplit(old, occurrence)
                        return new.join(li)
                    finarow= rreplace(finalrow, """\x1f""", '', 1)
                    row[6] = str(finarow)
                    row = tuple(row)
                    # if row[0] == 1558556384609: #FOR TROUBLE SHOOTING ! Change to the card.id you are uncertain about
                    
                except:
                    pass
        if getUserOption("Combine tagging", False):
            row=list(row)
            row[5] = togetherTags
            row=tuple(row)
        newUpdate.append(row)

    self.log.append(_("Notes found in file: %d") % total)

    if dupesIgnored:
        self.log.append(
            _("Notes that could not be imported as note type has changed: %d") %
            len(dupesIgnored))
    if update:
        self.log.append(
            _("Notes updated, as file had newer version: %d") %
            len(newUpdate))
    if add:
        self.log.append(
            _("Notes added from file: %d") %
            len(add))
    if dupesIdentical:
        self.log.append(
            _("Notes skipped, as they're already in your collection: %d") %
            len(dupesIdentical))

    self.log.append("")

    if dupesIgnored:
        for row in dupesIgnored:
            self._logNoteRow(_("Skipped"), row)
    if update:
        for row in update:
            self._logNoteRow(_("Updated"), row)
    if add:
        for row in add:
            self._logNoteRow(_("Added"), row)
    if dupesIdentical:
        for row in dupesIdentical:
            self._logNoteRow(_("Identical"), row)
    self.dupes = dupes
    self.added = len(add)
    self.updated = len(newUpdate)

    # add to col
    self.dst.db.executemany(
        "insert or replace into notes values (?,?,?,?,?,?,?,?,?,?,?)",
        add)
    self.dst.db.executemany(
        "insert or replace into notes values (?,?,?,?,?,?,?,?,?,?,?)",
        newUpdate)
    self.dst.updateFieldCache(dirty)
    self.dst.tags.registerNotes(dirty)

    # deal with deck description
    if getUserOption("update deck description", False):
        for importedDid, importedDeck in self.src.decks.decks.items():
            localDid = self._did(importedDid)
            localDeck = self.dst.decks.get(localDid)
            localDeck['desc'] = importedDeck['desc']
            self.dst.decks.save(localDeck)


Anki2Importer._importNotes = newImportNotes
def _mid(self, srcMid):
    """Return local id for remote MID.

    Two models are assumed to be compatible if they have the same
    names of fields and of card type. If imported model is
    compatible with local model of the same id, then both models
    are "merged". I.e. the lastly changed model is used.

    Otherwise the model of imported note is imported in the
    collection.

    """
    # already processed this mid?
    if srcMid in self._modelMap:
        return self._modelMap[srcMid]
    mid = srcMid
    srcModel = self.src.models.get(srcMid)
    srcScm = self.src.models.scmhash(srcModel)
    updateNoteType = getUserOption("update note type")
    while True:
        # missing from target col?
        if not self.dst.models.have(mid):
            # copy it over
            model = srcModel.copy()
            model['id'] = mid
            model['usn'] = self.col.usn()
            self.dst.models.update(model)
            break
        # there's an existing model; do the schemas match?
        dstModel = self.dst.models.get(mid)
        dstScm = self.dst.models.scmhash(dstModel)
        if srcScm == dstScm:
            # copy styling changes over if newer
            if updateNoteType or (updateNoteType is None and srcModel['mod'] > dstModel['mod']):
                model = srcModel.copy()
                model['id'] = mid
                model['usn'] = self.col.usn()
                self.dst.models.update(model)
            break
        # as they don't match, try next id
        mid += 1
        # save map and return new mid
    self._modelMap[srcMid] = mid
    return mid
Anki2Importer._mid = _mid
