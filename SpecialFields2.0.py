from aqt import mw
from anki.exporting import AnkiExporter
from aqt.utils import showInfo
import re, os, zipfile, shutil, unicodedata
from anki.lang import _
from anki import Collection
import json

from anki.utils import ids2str, splitFields, json, namedtmp
from anki.importing import Anki2Importer

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
SPECIAL_FIELD = [u"Lecture Notes",u"Rx/UWORLD Details",u"Boards and Beyond Expansion",u"Pathoma Details"]# add more between the brackets eg. u"Text",u"Extra",u"Front",u"Back"
COMBINE_TAGGING = False # change this to True if you would like to concatenate tags 
GUID = 1
MID = 2
MOD = 3

def newExportInto(self, path):
    # sched info+v2 scheduler not compatible w/ older clients
    # showInfo("newtype of import")
    try:
        self._v2sched = self.col.schedVer() != 1 and self.includeSched
    except AttributeError:
        pass
    # create a new collection at the target
    try:
        os.unlink(path)
    except (IOError, OSError):
        pass
    self.dst = Collection(path)
    self.src = self.col
    # find cards
    if not self.did:
        cids = self.src.db.list("select id from cards")
    else:
        cids = self.src.decks.cids(self.did, children=True)
    # copy cards, noting used nids
    nids = {}
    data = []
    for row in self.src.db.execute(
        "select * from cards where id in "+ids2str(cids)):
        nids[row[1]] = True
        data.append(row)
        # clear flags
        row = list(row)
        row[-2] = 0
    self.dst.db.executemany(
        "insert into cards values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        data)
    # notes
    ########################################################################
    # check if any models with special field exist
    midCheck= []
    models = mw.col.db.scalar("""select models from col""")
    b = json.loads(models)
    a = list(b.values())
    # showInfo("%s"%SPECIAL_FIELD)
    for i in a:
        fields = i["flds"]
        for n in fields:
            if n['name'] in SPECIAL_FIELD:
                midCheck.append(str(i["id"]))
    ########################################################################

    # showInfo("%s"%midCheck)
    strnids = ids2str(list(nids.keys()))
    notedata = []
    for row in self.src.db.all(
        "select * from notes where id in "+strnids):
        # remove system tags if not exporting scheduling info
        if not self.includeSched:
            row = list(row)
            row[5] = self.removeSystemTags(row[5])

        if str(row[2]) in midCheck: 
            trow = list(row)                     # if this note belongs to a model with "Special Field"
            
            for i in SPECIAL_FIELD:
                try:
                    row = list(row)
                    
                    items = mw.col.getNote(row[0]).items()
                    fieldOrd = [item for item in items if item[0] == i]
                    fieldOrd = items.index(fieldOrd[0])

                    fields = [item[1] for item in items]
                    splitRow = row[6].split("\x1f")
                    splitRow = splitRow[:len(fields)]

                    finalrow = ''
                    count = 0
                    for i in items:
                        if count == fieldOrd:
                            finalrow += "\x1f"
                        else:
                            i = list(i)
                            finalrow += str(i[1].encode("utf-8"))+"\x1f"
                        count= count+1
                    def rreplace(s, old, new, occurrence):
                        li = s.rsplit(old, occurrence)
                        return new.join(li)

                    finalrow= rreplace(finalrow, """\x1f""", '', 1)
                    row[6] = str(finalrow)
                    row = tuple(row)
                except IndexError:
                    pass
        notedata.append(row)

                #FOR TROUBLE SHOOTING ! Change to the card.id you are uncertain about

    # showInfo("%s" % str(notedata))
    self.dst.db.executemany(
        "insert into notes values (?,?,?,?,?,?,?,?,?,?,?)",
        notedata)
    # models used by the notes
    mids = self.dst.db.list("select distinct mid from notes where id in "+
                            strnids)
    # card history and revlog
    if self.includeSched:
        data = self.src.db.all(
            "select * from revlog where cid in "+ids2str(cids))
        self.dst.db.executemany(
            "insert into revlog values (?,?,?,?,?,?,?,?,?)",
            data)
    else:
        # need to reset card state
        self.dst.sched.resetCards(cids)
    # models - start with zero
    self.dst.models.models = {}
    for m in self.src.models.all():
        if int(m['id']) in mids:
            self.dst.models.update(m)
    # decks
    if not self.did:
        dids = []
    else:
        dids = [self.did] + [
            x[1] for x in self.src.decks.children(self.did)]
    dconfs = {}
    for d in self.src.decks.all():
        if str(d['id']) == "1":
            continue
        if dids and d['id'] not in dids:
            continue
        if not d['dyn'] and d['conf'] != 1:
            if self.includeSched:
                dconfs[d['conf']] = True
        if not self.includeSched:
            # scheduling not included, so reset deck settings to default
            d = dict(d)
            d['conf'] = 1
        self.dst.decks.update(d)
    # copy used deck confs
    for dc in self.src.decks.allConf():
        if dc['id'] in dconfs:
            self.dst.decks.updateConf(dc)
    # find used media
    media = {}
    self.mediaDir = self.src.media.dir()
    if self.includeMedia:
        for row in notedata:
            flds = row[6]
            mid = row[2]
            for file in self.src.media.filesInStr(mid, flds):
                # skip files in subdirs
                if file != os.path.basename(file):
                    continue
                media[file] = True
        if self.mediaDir:
            for fname in os.listdir(self.mediaDir):
                path = os.path.join(self.mediaDir, fname)
                if os.path.isdir(path):
                    continue
                if fname.startswith("_"):
                    # Scan all models in mids for reference to fname
                    for m in self.src.models.all():
                        if int(m['id']) in mids:
                            if self._modelHasMedia(m, fname):
                                media[fname] = True
                                break
    self.mediaFiles = list(media.keys())
    self.dst.crt = self.src.crt
    # todo: tags?
    self.count = self.dst.cardCount()
    self.dst.setMod()
    self.postExport()
    self.dst.close()


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
    ########################################################################
    # check if any models with special field exist
    midCheck= []
    models = mw.col.db.scalar("""select models from col""")
    b = json.loads(models)
    a = list(b.values())
    for i in a:
        fields = i["flds"]
        for n in fields:
            if n['name'] in SPECIAL_FIELD:
                midCheck.append(str(i["id"]))
    ########################################################################

    for note in self.src.db.execute(
        "select * from notes"):
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
                if oldMod < note[MOD]:
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
    if dupes:
        up = len(update)
        self.log.append(_("Updated %(a)d of %(b)d existing notes.") % dict(
            a=len(update), b=dupes))
        if dupesIgnored:
            self.log.append(_("Some updates were ignored because note type has changed:"))
            self.log.extend(dupesIgnored)

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
        if str(row[2]) in midCheck: 
            trow = list(row)                     # if this note belongs to a model with "Special Field"
            for i in SPECIAL_FIELD:
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
                    
                    # showInfo("%s"%str(splitRow))
                    # showInfo("%s"%str(indexOfField))
                    # showInfo("%s"%str(valueLocal))
                except:
                    pass
        if COMBINE_TAGGING:
            row=list(row)
            row[5] = togetherTags
            row=tuple(row)
        newUpdate.append(row)

    self.dupes = dupes
    self.added = len(add)
    self.updated = len(update)

    # add to col
    self.dst.db.executemany(
        "insert or replace into notes values (?,?,?,?,?,?,?,?,?,?,?)",
        add)
    self.dst.db.executemany(
        "insert or replace into notes values (?,?,?,?,?,?,?,?,?,?,?)",
        newUpdate)
    self.dst.updateFieldCache(dirty)
    self.dst.tags.registerNotes(dirty)


Anki2Importer._importNotes = newImportNotes
AnkiExporter.exportInto = newExportInto


