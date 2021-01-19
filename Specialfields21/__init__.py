from anki.importing import Anki2Importer
from anki.lang import _
from anki.utils import json
from anki.hooks import schema_will_change
from aqt import mw
from aqt.utils import showWarning

from . import dialog
from .config import getUserOption
from .note_type_mapping import create_mapping_on_field_name_equality

# #########################################################
#
# See this video for how to use this add-on: https://youtu.be/cg-tQ6Ut0IQ
#
KEEPTAGTEXT = "%%keep%%"
#
# #########################################################

NID = 0
GUID = 1
MID = 2
MOD = 3

configs = getUserOption("configs")
current_config = configs["current config"]


def getUserOptionSpecial(key=None, default=None):
    if key is None:
        return configs["current config"]
    if key in configs["current config"]:
        return configs["current config"][key]
    else:
        return default


def newImportNotes(self) -> None:
    # build guid -> (id,mod,mid) hash & map of existing note ids
    self._notes = {}
    existing = {}
    for id, guid, mod, mid in self.dst.db.execute(
        "select id, guid, mod, mid from notes"
    ):
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
    self.dupes = 0
    dupesIdentical = []
    dupesIgnored = []
    total = 0

    ######### note type mapping
    schema_will_change.remove(mw.onSchemaMod)
    ######### /note type mapping

    for note in self.src.db.execute("select * from notes"):
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
            self.dupes += 1
            if self.allowUpdate:
                oldNid, oldMod, oldMid = self._notes[note[GUID]]
                # will update if incoming note more recent

                if oldMod < note[MOD] or (
                    not getUserOptionSpecial("update only if newer", True)
                ):
                    # safe if note types identical
                    if oldMid == note[MID]:
                        # incoming note should use existing id
                        note[0] = oldNid
                        note[4] = usn
                        note[6] = self._mungeMedia(note[MID], note[6])
                        update.append(note)
                        dirty.append(note[0])
                    else:
                        ######### note type mapping
                        updateNoteType = getUserOptionSpecial("update note styling")

                        old_model = self.dst.models.get(oldMid)
                        target_model = self.dst.models.get(note[MID])

                        mapping = create_mapping_on_field_name_equality(
                            old_model, target_model
                        )

                        if updateNoteType and mapping:
                            self.dst.models.change(
                                old_model,
                                [note[NID]],
                                target_model,
                                mapping.get_field_map(),
                                mapping.get_card_type_map(),
                            )

                            note[0] = oldNid
                            note[4] = usn
                            note[6] = self._mungeMedia(note[MID], note[6])
                            update.append(note)
                            dirty.append(note[0])

                        ######### /note type mapping
                        else:
                            dupesIgnored.append(note)
                            self._ignoredGuids[note[GUID]] = True
                else:
                    dupesIdentical.append(note)

    self.log.append(_("Notes found in file: %d") % total)

    ######### note type mapping
    schema_will_change.append(mw.onSchemaMod)
    ######### /note type mapping

    ########################################################################
    # check if any models with special field exist
    midCheck = []
    a = mw.col.models.all()
    for i in a:
        fields = i["flds"]
        for n in fields:
            if n["name"] in getUserOptionSpecial(
                "Special field", []
            ) or getUserOptionSpecial("All fields are special", False):
                midCheck.append(str(i["id"]))
    ########################################################################

    for note in update:
        oldnote = mw.col.getNote(note[0])
        newTags = [t for t in note[5].replace("\u3000", " ").split(" ") if t]
        for tag in oldnote.tags:
            for i in newTags:
                if i.lower() == tag.lower():
                    tag = i
            newTags.append(tag)

        newTags = set(newTags)
        togetherTags = " %s " % " ".join(newTags)

        ######### KEEP tags
        keepTags = [t for t in note[5].replace("\u3000", " ").split(" ") if t]
        for tag in oldnote.tags:
            for i in keepTags:
                if i.lower() == tag.lower():
                    tag = i

            if KEEPTAGTEXT in tag:
                keepTags.append(tag)

        keepTags = set(keepTags)
        keepTagsTogether = " %s " % " ".join(keepTags)
        ######### /KEEP tags

        mid = str(note[2])
        if mid in midCheck:
            model = mw.col.models.get(mid)
            specialFields = getUserOptionSpecial("Special field", [])
            if getUserOptionSpecial("All fields are special", False):
                specialFields = [fld["name"] for fld in model["flds"]]
            # if this note belongs to a model with "Special Field"
            trow = list(note)
            for i in specialFields:
                try:
                    items = mw.col.getNote(note[0]).items()
                    fieldOrd = [item for item in items if item[0] == i]
                    fieldOrd = items.index(fieldOrd[0])
                    fields = [item[1] for item in items]
                    splitRow = note[6].split("\x1f")

                    # valueLocal = mw.col.getNote(note[0]).values()
                    # splitRow[indexOfField] = valueLocal[indexOfField]

                    finalrow = ""
                    count = 0
                    for a in splitRow:
                        if count == fieldOrd:
                            finalrow += str(fields[fieldOrd]) + "\x1f"
                        else:
                            finalrow += a + "\x1f"
                        count = count + 1

                    def rreplace(s, old, new, occurrence):
                        li = s.rsplit(old, occurrence)
                        return new.join(li)

                    finarow = rreplace(finalrow, """\x1f""", "", 1)
                    note[6] = str(finarow)
                    # if note[0] == 1558556384609: #FOR TROUBLE SHOOTING ! Change to the card.id you are uncertain about

                except:
                    pass
        if getUserOptionSpecial("Combine tagging", False):
            note[5] = togetherTags
        else:
            note[5] = keepTagsTogether

    self.log.append(_("Notes found in file: %d") % total)

    if dupesIgnored:
        self.log.append(
            _("Notes that could not be imported as note type has changed: %d")
            % len(dupesIgnored)
        )
    if update:
        self.log.append(_("Notes updated, as file had newer version: %d") % len(update))
    if add:
        self.log.append(_("Notes added from file: %d") % len(add))
    if dupesIdentical:
        self.log.append(
            _("Notes skipped, as they're already in your collection: %d")
            % len(dupesIdentical)
        )

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

    # export info for calling code
    self.added = len(add)
    self.updated = len(update)
    # add to col
    self.dst.db.executemany(
        "insert or replace into notes values (?,?,?,?,?,?,?,?,?,?,?)", add
    )
    self.dst.db.executemany(
        "insert or replace into notes values (?,?,?,?,?,?,?,?,?,?,?)", update
    )
    self.dst.updateFieldCache(dirty)
    self.dst.tags.registerNotes(dirty)

    # deal with deck description

    # if getUserOption("update deck description", False):
    if getUserOptionSpecial("update deck description", False):
        for importedDid, importedDeck in ((d["id"], d) for d in self.src.decks.all()):
            localDid = self._did(importedDid)
            localDeck = self.dst.decks.get(localDid)
            localDeck["desc"] = importedDeck["desc"]
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
    # getUserOption("update note styling")
    updateNoteType = getUserOptionSpecial("update note styling")
    while True:
        # missing from target col?
        if not self.dst.models.have(mid):
            # copy it over
            model = srcModel.copy()
            model["id"] = mid
            model["usn"] = self.col.usn()
            self.dst.models.update(model)
            break
        # there's an existing model; do the schemas match?
        dstModel = self.dst.models.get(mid)
        dstScm = self.dst.models.scmhash(dstModel)
        if srcScm == dstScm:
            # copy styling changes over if newer
            if updateNoteType or (
                updateNoteType is None and srcModel["mod"] > dstModel["mod"]
            ):
                model = srcModel.copy()
                model["mod"] = max(srcModel["mod"], dstModel["mod"])
                model["id"] = mid
                model["usn"] = self.col.usn()
                self.dst.models.update(model)
            break
        # as they don't match, try next id
        mid += 1
    # save map and return new mid
    self._modelMap[srcMid] = mid
    return mid


Anki2Importer._mid = _mid


def _did(self, did: int):
    "Given did in src col, return local id."
    # already converted?
    if did in self._decks:
        return self._decks[did]
    # get the name in src
    g = self.src.decks.get(did)
    name = g["name"]
    # if there's a prefix, replace the top level deck
    if self.deckPrefix:
        tmpname = "::".join(name.split("::")[1:])
        name = self.deckPrefix
        if tmpname:
            name += "::" + tmpname
    # manually create any parents so we can pull in descriptions
    head = ""
    for parent in name.split("::")[:-1]:
        if head:
            head += "::"
        head += parent
        idInSrc = self.src.decks.id(head)
        self._did(idInSrc)
    # if target is a filtered deck, we'll need a new deck name
    deck = self.dst.decks.byName(name)

    is_new = not bool(deck)

    if deck and deck["dyn"]:
        name = "%s %d" % (name, intTime())
    # create in local
    newid = self.dst.decks.id(name)
    # pull conf over
    if "conf" in g and g["conf"] != 1:
        conf = self.src.decks.getConf(g["conf"])
        self.dst.decks.save(conf)
        self.dst.decks.updateConf(conf)
        g2 = self.dst.decks.get(newid)
        g2["conf"] = g["conf"]
        self.dst.decks.save(g2)
    # save desc
    # only change
    if is_new or getUserOption("update deck description", False):
        deck = self.dst.decks.get(newid)
        deck["desc"] = g["desc"]
        self.dst.decks.save(deck)
    # add to deck map and return
    self._decks[did] = newid
    return newid


Anki2Importer._did = _did
